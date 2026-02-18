"""
MCA Editor - UI sub-package (backward-compat re-exports).

All widget functionality has moved to ``mca_qt.widgets``.
The main window has moved to ``mca_qt.editor_panel`` and
``mca_standalone.standalone_window``.
"""

from mca_qt.widgets.code_editor import MCACodeEditor
from mca_qt.widgets.output_window import OutputWindow
from mca_qt.widgets.sidebar import MCASidebar
from mca_qt.widgets.ai_panel import AIPanel
