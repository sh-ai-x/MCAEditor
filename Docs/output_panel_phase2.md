# Output Panel Fix — Phase 2: Content Parity with Maya's Script Editor

## Problem

After implementing batch buffering and cursor-less display (Phase 1), the
output panel's CONTENT still doesn't match Maya's Script Editor. Side-by-side
comparison reveals two clear discrepancies:

### Discrepancy 1: Missing `//` Prefixes

Maya's Script Editor shows:
```
// pymel.core : Updating pymel with pre-loaded plugins: ...
// mca_common : QMenu Mechanical Art: Found!
```

MCA Editor shows:
```
pymel.core : Updating pymel with pre-loaded plugins: ...
mca_common : QMenu Mechanical Art: Found!
```

The `//` prefix that Maya's Script Editor adds to info-type messages is
missing from MCA Editor's output.

### Discrepancy 2: Extra Logging Lines in MCA Editor

MCA Editor shows dozens of lines like these that Maya's Script Editor
does NOT show:
```
[MCA - Module: startup:85 - Function: startup_init] INFO: Creating MCA Python Common framework environment ...
[MCA - Module: startup:97 - Function: startup_init] INFO: Registering Environment Variables...
[MCA - Module: log:236 - Function: setup_file_logging] INFO: File logging enabled: ...
[MCA - Module: ai_envs:34 - Function: create_envs] INFO: MCA_AI_DEPEND set to: ...
```

Maya's Script Editor doesn't show ANY of these. They should not appear in
MCA Editor's output panel either.

---

## Root Cause

Both issues have the SAME root cause: **the internal Maya adapter's
`_execute_python()` redirects `sys.stdout` to a `StringIO` buffer during
code execution.**

Here's what happens during startup script execution:

1. Internal adapter wraps execution with `sys.stdout = StringIO()`
2. The startup script runs. It imports modules that call `print()` and
   use Python's `logging` module.
3. `print()` calls (like pymel's status messages) → captured by StringIO
   → written directly to MCA output panel **WITHOUT** going through Maya's
   output system → no `//` prefix
4. `logging` module output → if any handler writes to stdout, captured by
   StringIO → written to MCA output panel. Maya's Script Editor never sees
   these because they never reach Maya's output system.
5. StringIO content is dumped to MCA output panel as plain text.

Meanwhile, **Maya's Script Editor** works like this:
- `print()` → Maya's hooked `sys.stdout` → `cmdScrollFieldReporter` → shows
  with `// ` prefix for info messages
- `logging` module → Python logging handlers (stderr/file) → **never reaches
  Maya's output system** → doesn't appear

The stdout redirect is SHORT-CIRCUITING Maya's output pipeline. Output
goes directly from Python to MCA's panel, bypassing the entire Maya output
system that both the Script Editor and `MCommandMessage` callback rely on.

---

## Fix

### Core Principle

**In embedded mode (running inside Maya), STOP capturing stdout. Let
`MCommandMessage.addCommandOutputCallback` be the SOLE source of output
for the MCA output panel.**

This is how Charcoal Editor works — it hooks into Maya's output system
rather than trying to capture stdout separately.

### Step 1: Remove stdout redirect from `_execute_python()` in `internal_maya_adapter.py`

**Current code** (conceptual):
```python
def _execute_python(self, code):
    old_stdout = sys.stdout
    sys.stdout = StringIO()
    try:
        exec(compile(code, '<mca>', 'exec'), self._namespace)
        output = sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout
    return output  # → written to MCA output panel
```

**New code** (conceptual):
```python
def _execute_python(self, code):
    # Try eval first for single expressions (variable inspection)
    try:
        code_obj = compile(code.strip(), '<mca>', 'eval')
        result = eval(code_obj, self._namespace)
        if result is not None:
            # Route through Maya's output system so MCommandMessage captures it
            # and it appears in BOTH Script Editor and MCA Editor
            from maya.api.OpenMaya import MGlobal
            MGlobal.displayInfo(repr(result))
        return ""
    except SyntaxError:
        pass

    # Statement execution — just run it, no stdout capture
    exec(compile(code, '<mca>', 'exec'), self._namespace)
    return ""
```

**What changes:**
- `print()` inside executed code → goes to Maya's hooked stdout → appears in
  Maya's Script Editor with `// ` prefix → `MCommandMessage` callback fires →
  appears in MCA Editor (with whatever formatting the callback applies)
- `logging` output → goes to logging handlers → does NOT appear in Maya's
  Script Editor → does NOT appear in MCA Editor → **CORRECT BEHAVIOR**
- Expression results (e.g. highlighting a variable name and executing) →
  routed through `MGlobal.displayInfo()` → appears in both Script Editor
  and MCA Editor

### Step 2: Add `//` prefix formatting in `_on_maya_output()` in `maya_window.py`

Maya's `cmdScrollFieldReporter` widget adds display formatting to messages.
The `MCommandMessage` callback delivers RAW messages without formatting.
We need to match Maya's formatting:

```python
def _on_maya_output(self, msg, msg_type, *args):
    msg = msg.rstrip('\n')
    if not msg:
        return

    # Match Maya's Script Editor formatting:
    # - kInfo messages get "// " prefix
    # - kWarning messages get "// Warning: " prefix (Maya may already include this)
    # - kError messages get "// Error: " prefix (Maya may already include this)
    # - kResult messages get "// Result: " prefix
    # - kDisplay messages (print output) get no prefix — just the raw text
    #
    # IMPORTANT: Test empirically. Run `print("hello")` and `cmds.warning("test")`
    # and compare what MCommandMessage delivers vs what the Script Editor shows.
    # The callback may or may not include prefixes depending on message type.
    # Adjust the formatting below based on actual behavior.

    if msg_type == MCommandMessage.kError:
        # Check if msg already starts with "// Error:" — don't double-prefix
        if not msg.startswith('// '):
            msg = '// ' + msg
        self._panel._output.write_error(msg)
    elif msg_type == MCommandMessage.kWarning:
        if not msg.startswith('// '):
            msg = '// ' + msg
        self._panel._output.write_warning(msg)
    elif msg_type == MCommandMessage.kResult:
        if not msg.startswith('// '):
            msg = '// Result: ' + msg
        self._panel._output.write_result(msg)
    elif msg_type == MCommandMessage.kStackTrace:
        self._panel._output.write_error(msg)
    else:
        # kInfo, kDisplay, and anything else
        # kDisplay = print() output — Maya shows this WITH "// " prefix
        # kInfo = Maya info messages — also with "// " prefix
        if not msg.startswith('// '):
            msg = '// ' + msg
        self._panel._output.write_output(msg)
```

**CRITICAL: The `//` prefix behavior needs to be verified empirically.**

Run these test commands in Maya and compare what `MCommandMessage` delivers
(add a debug print in the callback to see raw msg and msg_type) versus what
Maya's Script Editor shows:

```python
# Test 1: print statement
print("hello world")
# Script Editor shows: // hello world  (or just: hello world ?)
# What does MCommandMessage deliver?

# Test 2: Maya command result
cmds.polySphere()
# Script Editor shows: // Result: [...]
# What does MCommandMessage deliver?

# Test 3: Warning
cmds.warning("test warning")
# Script Editor shows: // Warning: test warning
# What does MCommandMessage deliver?

# Test 4: Error
cmds.error("test error")
# What does the callback receive?

# Test 5: MEL echo
# Type a MEL command and check if the echo comes through
```

**Based on the test results, adjust the prefix logic above.** The goal is
byte-for-byte parity with what Maya's Script Editor displays.

### Step 3: Handle code echo (the blue text showing what code was executed)

Currently MCA Editor shows executed code in blue via `write_code_echo()`.
Maya's Script Editor also echoes executed code. With stdout redirect removed,
Maya will now echo the code through its output system, and `MCommandMessage`
will fire for it.

Options:
- **Option A (recommended):** Keep MCA's `write_code_echo()` for the blue
  formatted echo. Detect and suppress the duplicate echo from `MCommandMessage`
  by matching the exact code text.
- **Option B:** Remove MCA's echo entirely and let Maya's echo come through
  `MCommandMessage`. Loses the blue formatting.

For Option A, use content-based dedup:
```python
# In the class that handles execution:
self._pending_echo = None

def _execute(self, code):
    self._pending_echo = code.strip()
    self._output.write_code_echo(code)
    result = self._adapter.execute(code, language)
    # ...

# In _on_maya_output:
def _on_maya_output(self, msg, msg_type, *args):
    if self._pending_echo and msg.strip() == self._pending_echo:
        self._pending_echo = None
        return  # Skip — we already showed this as blue code echo
    # ... normal routing ...
```

### Step 4: Verify the return value path

With stdout redirect removed, `_execute_python()` returns an empty string.
The calling code in `editor_panel.py` or `maya_window.py` that writes the
return value to the output panel needs to handle this:

- If result is empty string → don't write anything (output came through
  `MCommandMessage` callback already)
- The callback handles all output display now

Check all callers of `adapter.execute()` and ensure they don't write empty
results to the output panel.

---

## Files to Modify

| File | Changes |
|------|---------|
| `mca_core/adapters/internal_maya_adapter.py` | Remove stdout redirect from `_execute_python()`. Use bare `exec()`. Route eval results through `MGlobal.displayInfo()`. Return empty string. |
| `mca_maya/maya_window.py` | Add `//` prefix formatting to `_on_maya_output()` based on msg_type. Add code echo dedup. |
| `mca_qt/editor_panel.py` | Handle empty result from adapter.execute() — don't write empty string to output. |

---

## Verification

### Empirical prefix test (do this FIRST)

Before implementing Step 2, add a temporary debug print to `_on_maya_output`:
```python
def _on_maya_output(self, msg, msg_type, *args):
    print(f"[DEBUG] type={msg_type}, msg={repr(msg)}")
    # ... rest of callback ...
```

Then run the test commands above and record exactly what `msg_type` and
`msg` values arrive for each. This tells you the exact prefix formatting
needed. Remove the debug print after.

### Functional tests

1. Execute `print("hello")` — MCA shows same text as Maya Script Editor
2. Execute `cmds.polySphere()` — result format matches Script Editor
3. Execute `cmds.warning("test")` — warning format matches Script Editor
4. Open a project with startup script — NO `[MCA - Module: ...]` logging
   lines appear in MCA output. Only output that also appears in Maya's
   Script Editor should show in MCA.
5. `pymel` messages show with `// ` prefix (matching Script Editor)
6. Code echo appears in blue (MCA's formatting), not duplicated
7. Output streams smoothly (batch timer still working from Phase 1)

### Content parity test

After all fixes, open Maya's Script Editor and MCA Editor side by side.
Execute various commands and verify the output content is IDENTICAL
(formatting colors can differ, but the TEXT must match line for line).

---

## Important Notes

- This fix ONLY applies to embedded mode (`internal_maya_adapter.py`).
  Standalone TCP mode (`maya_adapter.py`) still needs stdout redirect because
  output comes back through the socket, not through `MCommandMessage`.
- The `MCommandMessage` callback must remain installed for the entire editor
  lifetime — it's now the sole output source in embedded mode.
- Don't remove stdout redirect from the TCP adapter's base64 wrapper — that's
  a completely different execution path for standalone mode.
