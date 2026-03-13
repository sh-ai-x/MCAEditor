# Integrated Terminal

MCA Editor includes a built-in terminal so you can run shell commands without leaving Maya.

---

## Opening the Terminal

- Press ++ctrl+grave++ (backtick) to toggle the terminal
- Or click the terminal icon on the right tool stripe

The terminal opens as a panel on the right side of the editor.

---

## Features

- **Full shell access** — Runs your system shell (PowerShell on Windows, bash on macOS/Linux)
- **ANSI color support** — Colored output from tools like `git`, `pytest`, etc.
- **Copy/paste** — ++ctrl+c++ copies selected text (or sends interrupt if nothing is selected), ++ctrl+v++ pastes
- **Scrollback** — Scroll up to see previous output
- **Resize** — Drag the panel edge to adjust width

---

## Smart Ctrl+C

The terminal uses smart ++ctrl+c++ behavior, similar to Windows Terminal:

- **Text selected** — Copies the selection to clipboard
- **No selection** — Sends interrupt signal (Ctrl+C) to the running process
- ++ctrl+shift+c++ — Always copies, regardless of selection

---

## Use Cases

- Running `git` commands
- Installing Python packages
- Running tests
- File system operations
- Any command-line tool you'd normally use alongside Maya
