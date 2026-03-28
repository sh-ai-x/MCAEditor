# MCA Editor

<div style="text-align: center; margin: 2em 0;">
  <img src="assets/images/logo_animated.gif" alt="MCA Editor" width="200">
</div>

**A professional code editor for Maya and Unreal Engine** — built for artists and technical directors who want more from their scripting workflow.

MCA Editor is a modern, full-featured code editor that lives inside your DCC. Write scripts faster, manage projects, and extend the editor with plugins — the same editor, the same workflow, across Maya and Unreal Engine.

---

## Features

- **Maya + Unreal Engine** — One editor across both DCCs, same features, same workflow
- **Dual Mode** — Quick script execution or full project mode with file trees and multi-tab editing
- **AI Integration** — Orange Slice, a built-in AI assistant that understands your scene and code
- **Plugin Architecture** — Extend the editor with Python plugins using a clean, documented API
- **Integrated Terminal** — Run shell commands without leaving your DCC
- **Syntax Highlighting** — Python and MEL with automatic language detection
- **Code Completion** — Context-aware suggestions as you type
- **Find & Replace** — Search across files in your project
- **Output Panel** — Execution results, logging, and error display with full stack traces
- **Keyboard-Driven** — Comprehensive shortcuts for everything

[See pricing and try free →](pricing.md)

---

## Quick Start

[Maya — $99](pricing.md#mca-editor-for-maya){ .md-button .md-button--primary }
[Unreal — $99](pricing.md#mca-editor-for-unreal-engine){ .md-button .md-button--primary }
[Bundle — $140](pricing.md#maya-unreal-bundle){ .md-button }
[Try Free for 14 Days](download.md){ .md-button }

=== "Maya"

    1. Download `mcaEditor.py` for your Maya version
    2. Drop it into `~/Documents/maya/<version>/plug-ins/`
    3. Open Maya's Plug-in Manager and load `mcaEditor.py`
    4. Click the Script Editor button — MCA Editor opens instead

=== "Unreal Engine"

    1. Download the MCA Editor plugin zip for your UE version
    2. Extract the `MCAEditor/` folder into your project's `Plugins/` directory
    3. Open the project in UE, go to **Edit > Plugins**, and enable **MCA Editor**
    4. Restart UE — the MCA Editor button appears in the toolbar

See the [Installation Guide](getting-started/installation.md) for detailed instructions.

---

## Supported Versions

=== "Maya"

    | Maya Version | Python | Qt |
    |---|---|---|
    | Maya 2024 | Python 3.10 | PySide2 (Qt5) |
    | Maya 2025 | Python 3.11 | PySide6 (Qt6) |
    | Maya 2026 | Python 3.11 | PySide6 (Qt6) |

=== "Unreal Engine"

    | UE Version | Python | Platform |
    |---|---|---|
    | Unreal Engine 5.5 | Python 3.11 | Windows |
    | Unreal Engine 5.6 | Python 3.11 | Windows |
    | Unreal Engine 5.7 | Python 3.11 | Windows |

---

## Built By

MCA Editor is built by **<a href="https://nathancomes.com" target="_blank">Nathan Comes</a>**.

Licensed software — see the license terms included with the plugin.
