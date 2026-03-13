# Output Panel

The Output Panel displays execution results, print output, errors, and log messages. It sits below the editor area and is always visible by default.

---

## What Appears Here

- **Print statements** — `print()` output from your scripts
- **Return values** — Shown as `# Result: <value> #` when a script evaluates to a value
- **Errors** — Full Python tracebacks with syntax highlighting
- **Log messages** — From MCA Editor internals and plugins

---

## Controls

| Action | How |
|---|---|
| Clear output | Right-click > Clear, or the clear button |
| Copy text | Select and ++ctrl+c++ |
| Scroll to bottom | Output auto-scrolls; click to pause, scroll down to resume |

---

## Execution Flow

When you execute code:

1. Code is sent to Maya's Python (or MEL) interpreter
2. `stdout` and `stderr` are captured
3. Results stream back to the Output Panel in real time
4. Errors display full stack traces with file paths and line numbers

!!! tip
    Click on file paths in error tracebacks to navigate directly to the source location.
