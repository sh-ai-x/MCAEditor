# Script Mode

Script Mode is MCA Editor's default mode — a lightweight, tab-based script editor designed for quick Maya scripting. Think of it as Maya's Script Editor, but better.

---

## Overview

In Script Mode, each tab is an independent script buffer. You can have multiple tabs open, each with its own code and language. Tabs are not tied to files on disk — they're scratch pads for quick experiments.

---

## Creating and Managing Tabs

- **New tab:** ++ctrl+n++ or **File > New Tab**
- **Close tab:** ++ctrl+w++
- **Switch tabs:** ++ctrl+tab++ / ++ctrl+shift+tab++ or click the tab header
- **Drag to reorder:** Click and drag tab headers to rearrange

When creating a new tab, you can choose the language (Python or MEL).

---

## Writing Code

MCA Editor provides a modern editing experience:

- **Syntax highlighting** for Python and MEL
- **Auto-indentation** that follows Python conventions
- **Bracket matching** — highlights matching `()`, `[]`, `{}`
- **Bracket auto-close** — typing `(` automatically inserts `)`
- **Line numbers** in the left gutter
- **Code completion** — context-aware suggestions as you type (++ctrl+space++ to trigger manually)

---

## Executing Code

| Action | Shortcut |
|---|---|
| Execute all | ++ctrl+enter++ |
| Execute selected text | ++ctrl+shift+enter++ |

Execution results appear in the [Output Panel](output-panel.md) below the editor. Python code runs in Maya's Python interpreter, MEL code runs in Maya's MEL interpreter.

!!! tip "Execute selection"
    Select a portion of your code and press ++ctrl+shift+enter++ to run just that selection. Great for testing individual lines or blocks.

---

## Saving and Loading

Even in Script Mode, you can save your scripts to disk:

- **Save:** ++ctrl+s++
- **Save As:** ++ctrl+shift+s++
- **Open file:** ++ctrl+o++

Saved files remember their path — ++ctrl+s++ saves back to the same location.

---

## When to Use Script Mode

Script Mode is ideal for:

- Quick one-off scripts
- Testing code snippets
- Running MEL commands
- Interactive Maya exploration

For larger projects with multiple files, see [Project Mode](project-mode.md).
