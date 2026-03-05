"""
MCA Core - AI Chat Worker Thread.

Runs the AI API call loop off the main thread to keep the UI responsive
during streaming responses.  Communicates with the main thread via Qt
signals for token streaming, tool call requests, and completion/error
notifications.

The worker **never** touches EditorAPI directly.  Tool execution happens
on the main thread — the worker emits ``tool_call_requested`` and waits
on a ``threading.Event`` for the main thread to provide the result.

Build note:
    This file subclasses QThread and overrides ``run()`` — a Qt virtual
    method.  It must ship as ``.pyc`` (not ``.pyd``) due to the Shiboken
    enum crash issue with compiled Qt virtual overrides.

Dependencies:
    - PySide6 (QThread, Signal) — via qt_compat
    - threading (stdlib) — for Event synchronization
    - openai (managed venv) — lazy-imported in run()
"""

import json
import logging
import threading

from mca_qt.qt_compat import QThread, Signal

from mca_core.plugins.ai_chat.tools import TOOLS

# Module-level logger.
logger = logging.getLogger(__name__)

# Timeout (seconds) for waiting on tool results from the main thread.
# Prevents the worker from hanging indefinitely if tool execution stalls.
_TOOL_RESULT_TIMEOUT = 60


# --- Chat Worker -------------------------------------------------------------

class ChatWorker(QThread):
    """
    Background thread that streams AI responses and handles tool use.

    The worker runs the API call loop in ``run()``, streaming tokens
    back to the UI via signals.  When the AI requests a tool call,
    the worker pauses and waits for the main thread to execute the
    tool and provide the result.

    Signals:
        token_received(str):
            Emitted for each text token during streaming.
        tool_call_requested(str, str, str):
            Emitted when the AI requests a tool call.
            Arguments: (call_id, tool_name, arguments_json).
        response_complete(str):
            Emitted when the full response is finished.
            Argument: final assistant message text.
        error_occurred(str):
            Emitted when an error occurs during the API call.
    """

    # Qt signals for cross-thread communication.
    token_received = Signal(str)
    tool_call_requested = Signal(str, str, str)
    response_complete = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, client, model, messages, parent=None):
        """
        Initialize the chat worker.

        :param openai.OpenAI client: Configured OpenAI client.
        :param str model: Model name to use for completions.
        :param list messages: Conversation history (list of message dicts).
        :param QWidget parent: Optional parent for QThread ownership.
        """
        super().__init__(parent)
        self._client = client
        self._model = model
        self._messages = list(messages)  # Copy to avoid mutation.
        self._stop_requested = False

        # Synchronization for tool results.
        # The main thread calls provide_tool_result() which sets the event.
        self._tool_event = threading.Event()
        self._tool_results = {}  # call_id -> result_json

    def request_stop(self):
        """
        Request the worker to stop after the current API call.

        Does not forcefully kill the thread — just sets a flag that
        the run loop checks between iterations.
        """
        self._stop_requested = True
        # Unblock any pending tool wait so the thread can exit.
        self._tool_event.set()

    def provide_tool_result(self, call_id, result_json):
        """
        Provide a tool execution result from the main thread.

        Called by the chat widget after executing the tool on the main
        thread.  Unblocks the worker so it can continue the conversation.

        :param str call_id: The tool call ID from the API response.
        :param str result_json: JSON string with the tool result.
        """
        self._tool_results[call_id] = result_json
        self._tool_event.set()

    def run(self):
        """
        Main worker loop — streams API responses and handles tool calls.

        This method runs on a background thread.  It makes streaming
        API calls, emits tokens, handles tool call requests by pausing
        and waiting for main-thread execution, then loops until the AI
        finishes (no more tool calls).

        Overrides QThread.run() — ships as .pyc.
        """
        try:
            self._run_loop()
        except Exception as exc:
            logger.error("ChatWorker error: %s", exc, exc_info=True)
            self.error_occurred.emit(str(exc))

    def _run_loop(self):
        """
        Inner API call loop with tool use handling.

        Each iteration makes one streaming API call.  If the response
        contains tool calls, we pause for main-thread execution and
        then make another call with the tool results appended.
        """
        while not self._stop_requested:
            # Make the streaming API call.
            assistant_text, tool_calls = self._stream_response()

            if self._stop_requested:
                break

            # If no tool calls, the response is complete.
            if not tool_calls:
                self.response_complete.emit(assistant_text)
                return

            # Build the assistant message with tool calls for the history.
            assistant_msg = {"role": "assistant", "content": assistant_text or None}
            # Attach the tool_calls to the assistant message.
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                    },
                }
                for tc in tool_calls
            ]
            self._messages.append(assistant_msg)

            # Request execution for each tool call and wait for results.
            for tc in tool_calls:
                if self._stop_requested:
                    return

                # Signal the main thread to execute this tool.
                self._tool_event.clear()
                self.tool_call_requested.emit(
                    tc["id"], tc["name"], tc["arguments"]
                )

                # Wait for the main thread to provide the result.
                got_result = self._tool_event.wait(timeout=_TOOL_RESULT_TIMEOUT)

                if self._stop_requested:
                    return

                # Get the result or use a timeout error.
                if got_result and tc["id"] in self._tool_results:
                    result = self._tool_results.pop(tc["id"])
                else:
                    result = json.dumps({"error": "Tool execution timed out after {}s".format(
                        _TOOL_RESULT_TIMEOUT
                    )})
                    logger.warning("Tool '%s' timed out", tc["name"])

                # Append the tool result to the conversation.
                self._messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

            # Loop back to make another API call with the tool results.

        # If we get here, stop was requested.
        self.response_complete.emit("")

    def _stream_response(self):
        """
        Make a single streaming API call and collect the response.

        Emits ``token_received`` for each text delta.  Collects tool
        call deltas into complete tool call objects.

        :return: Tuple of (assistant_text, tool_calls).
        :rtype: tuple(str, list)
        """
        assistant_text = ""
        tool_calls_by_index = {}  # index -> {id, name, arguments}

        try:
            stream = self._client.chat.completions.create(
                model=self._model,
                messages=self._messages,
                tools=TOOLS,
                stream=True,
            )
        except Exception as exc:
            self.error_occurred.emit("API call failed: {}".format(str(exc)))
            return "", []

        try:
            for chunk in stream:
                if self._stop_requested:
                    break

                # Skip empty chunks.
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta

                # --- Text content ---
                if delta.content:
                    assistant_text += delta.content
                    self.token_received.emit(delta.content)

                # --- Tool call deltas ---
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_calls_by_index:
                            tool_calls_by_index[idx] = {
                                "id": "",
                                "name": "",
                                "arguments": "",
                            }
                        tc = tool_calls_by_index[idx]

                        # Accumulate deltas — id and name come in the first
                        # chunk, arguments stream across multiple chunks.
                        if tc_delta.id:
                            tc["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tc["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                tc["arguments"] += tc_delta.function.arguments

        except Exception as exc:
            # Stream errors (network, timeout, etc.).
            self.error_occurred.emit("Stream error: {}".format(str(exc)))
            return assistant_text, []

        # Convert tool calls dict to a sorted list.
        tool_calls = [
            tool_calls_by_index[idx]
            for idx in sorted(tool_calls_by_index.keys())
        ]

        return assistant_text, tool_calls
