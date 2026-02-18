# MCA Editor

Cross-DCC Script IDE - spiritual successor to Charcoal Editor 2.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Launch the editor
python run.py
```

## Features

- **Dual Mode UI**: Simple (Charcoal Editor 2 style) and Advanced (full IDE)
- **Maya Integration**: Connect to Maya via command port for MEL and Python execution
- **Syntax Highlighting**: Python and MEL with dark theme
- **Code Editor**: Line numbers, bracket matching, auto-indent, auto-close brackets/quotes, toggle comment
- **Tab Management**: Multiple buffers, file tabs, always keeps at least one open
- **Output Window**: Color-coded execution results
- **Code Outline**: Navigate classes, functions, and methods
- **Workspace Tree**: Browse project folders (Advanced mode)
- **AI Panel**: Placeholder for future AI assistant integration (BYOK and managed)
- **Plugin System**: Extensible architecture for custom DCC adapters and features

## Project Structure

```
MCAEditor/
    run.py                  # Launcher
    requirements.txt        # Dependencies
    mca_editor/             # Main package
        __init__.py         # Version and app metadata
        main.py             # Application bootstrap
        config/             # Settings management
        ui/                 # All UI components
        adapters/           # DCC adapter layer (Maya)
        plugins/            # Plugin system skeleton
        ai/                 # AI integration placeholder
    tests/                  # Test suite (future)
```

## Key Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+N | New buffer |
| Ctrl+O | Open file |
| Ctrl+S | Save |
| Ctrl+W | Close tab |
| Ctrl+Shift+Enter | Execute full script |
| Ctrl+Enter | Execute selected text |
| Ctrl+Alt+Enter | Execute current line |
| Ctrl+/ | Toggle comment |
| Ctrl+B | Toggle sidebar |
| Ctrl+Shift+A | Toggle AI panel |

## Requirements

- Python 3.9+
- PySide6 >= 6.5.0
