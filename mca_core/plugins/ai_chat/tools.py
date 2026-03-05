"""
MCA Core - AI Chat Tool Definitions.

OpenAI function-calling schema for 16 tools that map to MCAPluginAPI
methods.  These definitions are passed to the chat completions API
so the AI assistant can interact with the editor and connected DCC.

Each tool follows the OpenAI function-calling JSON schema format:
    {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}

Dependencies:
    - None (pure data definitions)
"""

import logging

# Module-level logger.
logger = logging.getLogger(__name__)


# --- Tool Definitions --------------------------------------------------------
# Organized by category: State, Read, Write, Navigate, Execute, Output.

TOOLS = [
    # --- State Tools ---
    {
        "type": "function",
        "function": {
            "name": "get_editor_state",
            "description": (
                "Get a comprehensive snapshot of the editor's current state "
                "including active file, cursor position, selection, open tabs, "
                "project info, DCC connection status, and server info."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_open_files",
            "description": (
                "List all open tabs across editor groups. Returns name, path, "
                "language, and modified status for each tab."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_output",
            "description": (
                "Get recent text from the editor's output panel. Useful for "
                "checking execution results or editor messages."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "max_lines": {
                        "type": "integer",
                        "description": "Maximum number of lines to return (default: 100).",
                        "default": 100,
                    },
                },
                "required": [],
            },
        },
    },

    # --- Read Tools ---
    {
        "type": "function",
        "function": {
            "name": "get_editor_text",
            "description": (
                "Get the full text content of the active editor buffer. "
                "Returns the in-memory content including unsaved changes."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_selected_text",
            "description": (
                "Get the currently selected text in the active editor. "
                "Returns the selected text or empty string if nothing is selected."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_disk_file",
            "description": (
                "Read a file directly from disk, bypassing editor buffers. "
                "If the file is open with unsaved edits, this returns the "
                "on-disk version."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Absolute path to the file to read.",
                    },
                },
                "required": ["filepath"],
            },
        },
    },

    # --- Write Tools ---
    {
        "type": "function",
        "function": {
            "name": "set_editor_text",
            "description": (
                "Replace the entire content of the active editor buffer "
                "with new text. This modifies the buffer in-memory; "
                "use save_file to persist."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The new content to replace the entire buffer with.",
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_text",
            "description": (
                "Insert text at a specific position in the active editor. "
                "If line/col are omitted, inserts at the current cursor position. "
                "Line and column numbers are 1-based."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to insert.",
                    },
                    "line": {
                        "type": "integer",
                        "description": "1-based line number to insert at (optional).",
                    },
                    "col": {
                        "type": "integer",
                        "description": "1-based column number to insert at (optional).",
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_range",
            "description": (
                "Replace a range of text in the active editor. Selects from "
                "(start_line, start_col) to (end_line, end_col) and replaces "
                "with the given text. All positions are 1-based. "
                "Pass empty text to delete."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_line": {
                        "type": "integer",
                        "description": "1-based start line number.",
                    },
                    "start_col": {
                        "type": "integer",
                        "description": "1-based start column number.",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "1-based end line number.",
                    },
                    "end_col": {
                        "type": "integer",
                        "description": "1-based end column number.",
                    },
                    "text": {
                        "type": "string",
                        "description": "Replacement text (empty string to delete).",
                    },
                },
                "required": ["start_line", "start_col", "end_line", "end_col", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_disk_file",
            "description": (
                "Write content directly to a file on disk. Creates parent "
                "directories if they don't exist. Does not update editor buffers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Absolute path to the file to write.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file.",
                    },
                },
                "required": ["filepath", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_file",
            "description": "Save the currently active file in the editor.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },

    # --- Navigate Tools ---
    {
        "type": "function",
        "function": {
            "name": "open_file",
            "description": (
                "Open a file in the editor. If the file is already open "
                "in a tab, switches to that tab."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Absolute path to the file to open.",
                    },
                },
                "required": ["filepath"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "navigate_to",
            "description": (
                "Open a file in the editor and jump to a specific line. "
                "Combines open_file + go_to_line in one call."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Absolute path to the file to open.",
                    },
                    "line": {
                        "type": "integer",
                        "description": "1-based line number to jump to (default: 1).",
                        "default": 1,
                    },
                },
                "required": ["filepath"],
            },
        },
    },

    # --- Execute Tools ---
    {
        "type": "function",
        "function": {
            "name": "execute_in_dcc",
            "description": (
                "Execute code in the connected DCC application (e.g. Maya). "
                "Returns success status, stdout output, and any error messages. "
                "The DCC must be connected for this to work."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Source code to execute in the DCC.",
                    },
                    "language": {
                        "type": "string",
                        "description": "Language: 'python' or 'mel' (default: 'python').",
                        "default": "python",
                        "enum": ["python", "mel"],
                    },
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_locally",
            "description": (
                "Execute Python code locally in the editor's process with "
                "stdout capture. Uses a persistent namespace so variables "
                "survive across calls."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python source code to execute locally.",
                    },
                },
                "required": ["code"],
            },
        },
    },

    # --- Output Tools ---
    {
        "type": "function",
        "function": {
            "name": "write_output",
            "description": (
                "Write a message to the editor's output panel. "
                "Supports different levels: 'output', 'info', 'warning', "
                "'error', 'success'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The message text to display.",
                    },
                    "level": {
                        "type": "string",
                        "description": "Message level (default: 'info').",
                        "default": "info",
                        "enum": ["output", "info", "warning", "error", "success"],
                    },
                },
                "required": ["text"],
            },
        },
    },
]


def get_tool_names():
    """
    Return the list of all available tool names.

    :return: List of tool name strings.
    :rtype: list
    """
    return [t["function"]["name"] for t in TOOLS]
