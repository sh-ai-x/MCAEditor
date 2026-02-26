# Session: 2026-02-25 — PyCharm-Style Terminal Panel UI Overhaul

## Summary
Replaced the single hidden terminal widget with a PyCharm-style multi-panel
layout: tabbed terminal panels (bottom and right), left/right tool stripes
with icon buttons, and a right-side tabbed panel hosting both AI and Terminal.

## What Was Done

### New Files
- `mca_qt/widgets/tool_stripe.py` — Left/right edge icon button bars
  (ToolStripe + ToolStripeButton). 28px wide, icon-only with tooltips,
  blue left-border highlight for active state.
- `mca_qt/widgets/terminal_tab_panel.py` — Multi-terminal tabbed container
  (TerminalTabPanel). QTabWidget with closable/movable tabs, "+" corner
  button, lazy terminal creation, `all_terminals_closed` signal for auto-hide.
- `mca_qt/widgets/terminal_factory.py` — Terminal widget factory (extracted
  from earlier session). Selects xterm.js or native terminal at runtime.
- `mca_core/venv_manager.py` — Managed venv for third-party dependencies.

### Modified Files
- `mca_qt/editor_panel.py` — Major layout restructuring:
  - Added left/right tool stripes flanking the main splitter
  - Replaced single `_terminal` widget with `_bottom_terminal_panel`
  - Added `_right_panel` (QTabWidget) with AI + Terminal tabs
  - New View menu items: "Open Terminal at Bottom" / "Open Terminal at Right"
  - New methods: `_open_terminal_bottom()`, `_open_terminal_right()`,
    stripe click dispatchers, auto-hide callbacks
  - Save/restore: `bottom_terminal_visible`, `right_terminal_visible` keys
    with legacy `terminal_visible` migration
- `mca_qt/icons.py` — Added `terminal_icon()` (>_ prompt) and `ai_icon()`
  (four-pointed sparkle) programmatic icons
- `mca_qt/widgets/terminal_native.py` — Fixed resize-induced blank lines:
  clear document and reset scrollback tracking when row count changes
- `mca_qt/widgets/terminal_backend.py` — venv path re-injection for Maya
- `mca_qt/widgets/ansi_parser.py` — Various fixes from prior sessions
- `mca_standalone/main.py` — Venv setup integration
- `mca_maya/plugin_main.py` — Venv setup integration
- `build_maya.py` — Build script updates

### Key Fixes During Session
- **QPushButton.clicked lambda**: The `clicked` signal emits a bool (checked
  state); the stripe button lambda wasn't accepting it, causing TypeError on
  every click. Fixed with `lambda _checked=False, n=name: ...`.
- **Resize blank lines**: When shrinking the terminal panel, the native
  terminal's document kept stale blocks that appeared as blank lines at the
  top. Fixed by clearing the document and resetting `_scrollback_rendered`
  in `_calculate_dimensions()` when row count changes.
- **Terminal start timing**: Changed `QTimer.singleShot(0, ...)` to 200ms
  in `add_terminal()` so the QTabWidget tab bar renders before the terminal
  measures its viewport size.

## Layout After Changes

```
QHBoxLayout:
  [_left_stripe]  [_main_splitter]  [_right_stripe]
                    |-- _sidebar
                    |-- center_widget
                    |     |-- _toolbar
                    |     +-- _center_splitter (V)
                    |           |-- _output
                    |           |-- _group_container
                    |           +-- _bottom_terminal_panel (hidden)
                    +-- _right_panel (QTabWidget, hidden)
                          |-- Tab "AI": _ai_panel
                          +-- Tab "Terminal": _right_terminal_panel
```

## Settings Keys Added
- `bottom_terminal_visible` (default False)
- `right_terminal_visible` (default False)
- Legacy `terminal_visible` migrated to `bottom_terminal_visible` on first load
