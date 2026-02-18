"""
MCA Qt - Shared Qt Widget Layer.

Provides PySide2/PySide6-compatible widgets, theme, and the compatibility
shim for MCA Editor. All Qt-using modules import from this package.

Sub-modules:
    - qt_compat: PySide2/6 detection and compatibility patches
    - theme: Dark palette and global stylesheet
    - widgets: All reusable UI widgets (code editor, output, sidebar, etc.)
    - editor_panel: The core MCAEditorPanel (QWidget) for embedding

Dependencies:
    - PySide6 >= 6.5.0 (preferred)
    - OR PySide2 >= 5.15.0 (Maya 2024 and earlier)
"""
