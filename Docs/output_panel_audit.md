# Output Panel Audit & Fix Plan

## Problem Statement

The MCA Editor's output panel is not in sync with Maya's Script Editor output.
Specific symptoms:

1. **Missing Maya output** — The editor shows its own logging but not all of
   Maya's output. Maya's Script Editor and Charcoal Editor show everything.
2. **Delayed / chunked updates** — Output arrives in bursts rather than
   instantly. Charcoal Editor and Maya's Script Editor update in real-time.
3. **Not a faithful mirror** — The output panel should behave identically to
   Maya's Script Editor output, showing everything Maya produces as it happens.

---

## Current Architecture (What We Have)

### Output Pipeline (Maya Embedded — `mca_maya/maya_window.py`)

```
Maya generates output
    → MCommandMessage.addCommandOutputCallback(_on_maya_output)
    → Checks _suppress_output_hook flag (if True, skips)
    → Filters MCA log lines (regex or prefix check)
    → Routes to output panel: write_info / write_warning / write_error
```

### Output Pipeline (Standalone — `mca_qt/editor_panel.py`)

```
User executes code
    → maya_adapter._send_command() via TCP socket
    → Response returned as string
    → Written to output panel via write_output / write_error
```

### Output Panel Write Path (`mca_qt/widgets/output_window.py`)

```python
def _append_formatted(self, text, fmt):
    cursor = self._output.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    if self._show_timestamps:
        cursor.insertText(timestamp, self._fmt_timestamp)
    cursor.insertText(text + "\n", fmt)
    self._output.setTextCursor(cursor)       # ← Forces UI update
    self._output.ensureCursorVisible()        # ← Forces scroll + repaint
```

### Focus Preservation (`mca_maya/maya_window.py`)

```python
def _on_maya_output(self, msg, msg_type, ...):
    current_focus = QApplication.instance().focusWidget()
    # ... write to output panel ...
    if current_focus and current_focus is not self._panel._output:
        current_focus.setFocus(Qt.FocusReason.OtherFocusReason)
```

### Suppression Flag (`mca_core/adapters/internal_maya_adapter.py`)

```python
_suppress_output_hook = False

def _execute_python(self, code):
    global _suppress_output_hook
    _suppress_output_hook = True
    try:
        MGlobal.displayInfo(code)  # Echo to Maya's Script Editor
    finally:
        _suppress_output_hook = False
```

---

## Root Cause Analysis

### Issue 1: Missing Output — Overly Aggressive Filtering

The `_on_maya_output` callback filters "MCA log lines" to reduce noise.
This filter was added in the 2026-02-26 session. The problem is that the
filter criteria may be too broad, catching legitimate Maya output that
happens to match the filter pattern.

**What to check:**
- What is the exact filter logic? Is it prefix-based (`[mca_core]`,
  `[mca_qt]`) or broader?
- Does it filter ALL lines that contain "mca" anywhere?
- Are `kInfo` / `kResult` / `kWarning` / `kError` message types all being
  handled, or are some types dropped?

**What to check (suppress flag):**
- Is `_suppress_output_hook` being set True for the code echo AND the
  execution result? If so, the execution result itself gets suppressed.
- Is the timing right? The flag is set synchronously but Maya's output
  callback fires asynchronously — there's a race condition where the flag
  could still be True when the result callback fires.

### Issue 2: Missing Output — Message Types Not Captured

`MCommandMessage.addCommandOutputCallback` provides a `msg_type` parameter.
Maya has these message types:
- `MCommandMessage.kInfo` — general info
- `MCommandMessage.kWarning` — warnings
- `MCommandMessage.kError` — errors
- `MCommandMessage.kResult` — command results
- `MCommandMessage.kStackTrace` — stack traces
- `MCommandMessage.kDisplay` — display messages (print statements)

**The callback may not be handling `kResult` and `kDisplay`**, which are the
most common types for script execution output. If the routing only handles
kInfo/kWarning/kError, most of Maya's Script Editor output would be missing.

### Issue 3: Delayed Output — Per-Message UI Updates

Every single output message triggers this sequence:
1. `textCursor()` — get cursor
2. `movePosition(End)` — seek to end
3. `insertText(timestamp)` — insert timestamp (optional)
4. `insertText(text + "\n")` — insert message
5. `setTextCursor(cursor)` — apply cursor (triggers internal update)
6. `ensureCursorVisible()` — scroll and repaint

Steps 5 and 6 are expensive. When Maya produces rapid-fire output (e.g.
a loop with 100 print statements), each message individually forces the
QPlainTextEdit to recalculate its viewport and repaint. This is what causes
the "waits then posts in chunks" behavior — Qt batches the repaints in its
event loop, making them appear as chunks.

**How Charcoal Editor / Maya's Script Editor avoid this:**
Maya's `cmdScrollFieldReporter` is a native MEL widget backed by C++ that
uses an internal text buffer with batch updates. It doesn't use
QPlainTextEdit's cursor API for each message. Charcoal Editor likely
uses `appendPlainText()` or accumulates text in a buffer and flushes
on a timer.

### Issue 4: Delayed Output — Focus Save/Restore Overhead

Every output write does `focusWidget()` save and `setFocus()` restore.
`setFocus()` can trigger focus-change events that cascade through Maya's
UI. This adds latency per message and can cause Qt's event loop to process
focus events between output writes, breaking the flow.

### Issue 5: Standalone TCP — No Live Output Hook

In standalone mode (connected via TCP), there is NO `MCommandMessage`
callback. Output only appears when a command completes and returns its
result through the socket. There is no streaming — if a script takes 10
seconds and prints 50 lines, you see nothing until it finishes, then get
all 50 lines at once.

This is a fundamental architectural limitation of TCP command port
communication. Charcoal Editor likely uses a different approach (possibly
reading Maya's script editor history on a timer, or using a more
sophisticated socket protocol).

---

## Behavioral Requirement: Match Maya's Script Editor Output

The output panel must behave identically to Maya's Script Editor output
(the `cmdScrollFieldReporter` widget):

- **Read-only** — no editing, no pasting, no typing
- **No visible cursor** — no blinking text cursor at all
- **Selectable** — user can click and drag to select text
- **Copyable** — Ctrl+C / right-click Copy works on selected text
- **Auto-scroll** — scrolls to bottom on new output (unless user has
  scrolled up to read history)
- **No focus stealing** — clicking in the output panel should NOT show
  a text insertion cursor

Currently the output panel is a `QPlainTextEdit` with `setReadOnly(True)`,
which still shows a blinking cursor and accepts focus with a text cursor
visible. Maya's reporter widget has none of that — it looks and feels like
a log viewer, not a text editor.

---

## Fix Plan

### Fix 0: Make Output Panel Cursor-Less and Read-Only (Maya Parity)

The `QPlainTextEdit` with `setReadOnly(True)` still shows a blinking text
cursor. Maya's output has no cursor at all — it's a log viewer, not an editor.

```python
# In OutputWindow.__init__ or _setup_ui, after creating self._output:

# Read-only, no editing, no pasting
self._output.setReadOnly(True)
self._output.setTextInteractionFlags(
    Qt.TextInteractionFlag.TextSelectableByMouse
    | Qt.TextInteractionFlag.TextSelectableByKeyboard
)

# Hide the blinking cursor entirely
self._output.setCursorWidth(0)

# Don't accept drops
self._output.setAcceptDrops(False)
```

**Key points:**
- `setCursorWidth(0)` hides the blinking text cursor completely
- `TextSelectableByMouse | TextSelectableByKeyboard` allows click-drag
  selection and Ctrl+C copy, but blocks typing, pasting, and all editing
- `setAcceptDrops(False)` prevents drag-and-drop text into the panel
- The right-click context menu should only offer Copy, Select All, and Clear
  (already implemented per 2026-02-26 session — verify Paste is NOT included)

**Files to modify:** `mca_qt/widgets/output_window.py`

### Fix 1: Rewrite `_append_formatted()` with Batch Buffering

Replace per-message cursor manipulation with a buffered approach:

```python
class OutputWindow(QWidget):
    def __init__(self, ...):
        # ...
        self._pending_messages = []       # Buffer: list of (text, fmt) tuples
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(16)  # ~60fps
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._flush_pending)

    def _append_formatted(self, text, fmt):
        """Queue a message for batch rendering."""
        self._pending_messages.append((text, fmt))
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush_pending(self):
        """Write all queued messages in one UI update."""
        if not self._pending_messages:
            return

        messages = self._pending_messages
        self._pending_messages = []

        # Block signals to prevent per-insert updates
        self._output.blockSignals(True)
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        for text, fmt in messages:
            if self._show_timestamps:
                ts = datetime.now().strftime("[%H:%M:%S] ")
                cursor.insertText(ts, self._fmt_timestamp)
            cursor.insertText(text + "\n", fmt)

        self._output.blockSignals(False)
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()
```

**Why this fixes the chunking:**
- Messages that arrive within 16ms are batched into a single UI update
- `blockSignals(True)` prevents intermediate repaints
- Only ONE `setTextCursor()` + `ensureCursorVisible()` per batch
- 16ms interval matches ~60fps — updates feel instant to humans

**Files to modify:** `mca_qt/widgets/output_window.py`

### Fix 2: Audit and Fix MCommandMessage Type Handling

Open `mca_maya/maya_window.py` and verify the `_on_maya_output` callback
handles ALL message types. The callback signature is:

```python
def _on_maya_output(self, msg, msg_type, *args):
```

Ensure the routing covers:

```python
from maya.api.OpenMaya import MCommandMessage

def _on_maya_output(self, msg, msg_type, *args):
    if _suppress_output_hook:
        return

    msg = msg.strip()
    if not msg:
        return

    # Do NOT filter by message content here (no MCA log filter)
    # Route ALL messages by type

    if msg_type == MCommandMessage.kError:
        self._panel._output.write_error(msg)
    elif msg_type == MCommandMessage.kWarning:
        self._panel._output.write_warning(msg)
    elif msg_type == MCommandMessage.kResult:
        self._panel._output.write_result(msg)
    elif msg_type == MCommandMessage.kStackTrace:
        self._panel._output.write_error(msg)
    else:
        # kInfo, kDisplay, and anything else
        self._panel._output.write_output(msg)
```

**Critical: Remove or drastically narrow the MCA log line filter.**
The current filter was added to reduce noise from `logger.info()` calls
inside mca_core/mca_qt/mca_maya modules. Instead of filtering in the
output callback, fix the source: set MCA loggers to WARNING level so
they don't produce info-level output that reaches Maya's Script Editor
in the first place. The output hook should be a transparent passthrough.

**Files to modify:** `mca_maya/maya_window.py`

### Fix 3: Fix the `_suppress_output_hook` Race Condition

The current pattern is:

```python
_suppress_output_hook = True
try:
    MGlobal.displayInfo(code_echo)
finally:
    _suppress_output_hook = False
```

The problem: `MGlobal.displayInfo()` posts to Maya's message queue. The
`MCommandMessage` callback may fire **during** or **after** the finally
block, depending on Maya's internal threading. This creates a race where:

1. `_suppress_output_hook = True`
2. `MGlobal.displayInfo("print('hello')")`  ← echo of code
3. `_suppress_output_hook = False`
4. Maya's output callback fires for the echo  ← suppression flag is ALREADY False
5. Output panel shows the echo (duplicate)

OR the inverse — the flag is still True when the actual execution result
arrives, causing it to be suppressed (lost output).

**Fix: Use message content matching instead of a timing-based flag.**

```python
_suppress_next_echo = None  # The exact string to suppress

def _execute_python(self, code):
    global _suppress_next_echo
    echo_text = code.strip()
    _suppress_next_echo = echo_text
    MGlobal.displayInfo(echo_text)
    # Don't clear the flag here — let the callback clear it

def _on_maya_output(self, msg, msg_type, *args):
    global _suppress_next_echo
    msg_stripped = msg.strip()

    if _suppress_next_echo and msg_stripped == _suppress_next_echo:
        _suppress_next_echo = None
        return  # Skip this exact echo message

    # ... normal routing ...
```

This is content-based deduplication rather than timing-based suppression.
It's immune to race conditions because it matches the exact message.

**Files to modify:**
- `mca_core/adapters/internal_maya_adapter.py`
- `mca_maya/maya_window.py`

### Fix 4: Remove Focus Save/Restore from Output Writes

The focus save/restore was added because `setTextCursor()` on the output
panel could steal focus from the code editor. With the batched write
approach (Fix 1), we can avoid this entirely:

```python
def _flush_pending(self):
    # ...
    # Use a cursor that doesn't affect the widget's visible cursor
    cursor = QTextCursor(self._output.document())
    cursor.movePosition(QTextCursor.MoveOperation.End)

    for text, fmt in messages:
        cursor.insertText(text + "\n", fmt)

    # Only scroll if the user was already at the bottom
    scrollbar = self._output.verticalScrollBar()
    at_bottom = scrollbar.value() >= scrollbar.maximum() - 10
    if at_bottom:
        scrollbar.setValue(scrollbar.maximum())
```

**Key insight:** Create the cursor from `self._output.document()` instead
of `self._output.textCursor()`. A document cursor doesn't affect the
widget's selection or focus — it's a purely data-level operation. This
eliminates the need for focus save/restore entirely.

**Bonus: Auto-scroll only when at bottom.** If the user has scrolled up
to read earlier output, don't force-scroll them to the bottom on every
new message. Only auto-scroll if they were already at/near the bottom.
This is standard behavior in VS Code, PyCharm, and Maya's Script Editor.

**Files to modify:**
- `mca_qt/widgets/output_window.py`
- `mca_maya/maya_window.py` (remove focus save/restore in `_on_maya_output`)

### Fix 5: Add `write_bulk()` Optimization

For session restore and history loading, add a fast bulk write method
that bypasses the timer entirely:

```python
def write_bulk(self, text):
    """Write a large block of pre-formatted text directly.
    Used for session restore and history loading — no per-line formatting.
    """
    self._output.blockSignals(True)
    self._output.setPlainText(text)
    self._output.blockSignals(False)

    scrollbar = self._output.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum())
```

**Files to modify:** `mca_qt/widgets/output_window.py`

### Fix 6: Ensure Logger Levels Are Set Early

Instead of filtering MCA log output in the output callback, set the
logger levels at module import time:

```python
# In mca_maya/maya_window.py or mca_maya/__init__.py
import logging
for name in ("mca_core", "mca_qt", "mca_maya"):
    logging.getLogger(name).setLevel(logging.WARNING)
```

This prevents MCA debug/info messages from ever reaching Maya's output
system, so the output callback doesn't need to filter anything. It
becomes a clean, transparent passthrough.

**Files to modify:** `mca_maya/maya_window.py` (verify this is already done
and happening early enough — before any logging occurs)

### Fix 7: Standalone TCP Live Output (Stretch Goal)

This is the hardest fix and may not be needed for V1, but it's worth
documenting. In standalone mode, the TCP socket only returns output after
a command completes. For live streaming:

**Option A: Polling Maya's Script Editor History**
- After sending a command, poll Maya's `cmdScrollFieldReporter` content
  on a timer (e.g. every 100ms) until the command completes
- Diff the content to find new lines
- Display incrementally
- Downside: polling overhead, 100ms latency

**Option B: Output Redirect in the Wrapper**
- The base64 wrapper already redirects stdout to StringIO
- Instead, redirect to a custom object that both captures AND sends
  incremental output back through a second socket/channel
- Downside: complex, requires a secondary communication channel

**Option C: Accept the Limitation**
- Standalone TCP mode shows output on completion only
- Document this as a known limitation
- The embedded Maya mode (internal adapter) has live output
- Most pro users will use the embedded mode anyway

**Recommendation:** Option C for now. Focus on making embedded mode perfect.

---

## Implementation Order

### Phase 1: Critical Fixes (Do These First)
1. **Fix 0** — Make output panel cursor-less, no paste, select+copy only.
2. **Fix 2** — Audit `_on_maya_output` message type handling. Ensure ALL
   types are routed. Remove/narrow the content filter.
3. **Fix 3** — Replace `_suppress_output_hook` flag with content-based
   dedup.
4. **Fix 6** — Verify logger levels are set early.

### Phase 2: Performance (Do These Second)
4. **Fix 1** — Implement batch buffering with 16ms flush timer.
5. **Fix 4** — Switch to document cursor, remove focus save/restore,
   add smart auto-scroll.
6. **Fix 5** — Add `write_bulk()` for session restore.

### Phase 3: Verification
7. Test in Maya: execute `for i in range(100): print(i)` — output should
   appear smoothly, not in a single chunk after completion.
8. Test in Maya: create/delete objects, run scripts — output should match
   Maya's Script Editor exactly.
9. Test in Maya: type in code editor while output is streaming — no focus
   theft, no cursor jumps.
10. Test session restore — output.log loads instantly on startup.
11. Test with output panel scrolled up — new messages don't force-scroll
    to bottom unless user was already at bottom.

---

## Files to Modify (Summary)

| File | Changes |
|------|---------|
| `mca_qt/widgets/output_window.py` | Cursor-less read-only (setCursorWidth(0), TextSelectableByMouse only), batch buffer, document cursor, smart scroll, write_bulk, verify context menu has no Paste |
| `mca_maya/maya_window.py` | Audit message types, remove content filter, remove focus save/restore, verify logger levels |
| `mca_core/adapters/internal_maya_adapter.py` | Replace suppress flag with content-based dedup |

---

## Testing Checklist

- [ ] Output panel has NO blinking cursor visible at any time
- [ ] Click in output panel — no text cursor appears
- [ ] Click-drag in output panel — text selection works (highlight visible)
- [ ] Ctrl+C on selected text — copies to clipboard
- [ ] Ctrl+V in output panel — does nothing (no paste)
- [ ] Typing in output panel — does nothing (no text entry)
- [ ] Right-click context menu — only Copy, Select All, Clear (no Paste)
- [ ] Drag text onto output panel — rejected (no drop)
- [ ] `for i in range(100): print(i)` — smooth, incremental output (not chunked)
- [ ] `cmds.polySphere()` — result appears instantly in output panel
- [ ] `cmds.warning("test")` — warning appears in yellow
- [ ] `import this` — long output appears smoothly
- [ ] Type in editor while output is streaming — no focus loss
- [ ] Scroll up in output, execute code — output does NOT force-scroll
- [ ] Scroll to bottom in output, execute code — output DOES auto-scroll
- [ ] Compare output panel content with Maya Script Editor — identical
- [ ] Open project with startup script — output appears correctly
- [ ] Close and reopen editor — session output restored
- [ ] Ctrl+F in output panel — search still works with batched writes
