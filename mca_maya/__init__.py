"""
MCA Maya - Maya Plugin Integration.

Provides the Maya plugin (initializePlugin/uninitializePlugin), the
dockable window wrapper, and an installer script.

Sub-modules:
    - plugin_main: Maya plugin entry points
    - maya_window: MayaQWidgetDockableMixin wrapper around MCAEditorPanel
    - install: Helper to install the plugin into Maya's module path

Dependencies:
    - maya.cmds, maya.mel (only available inside Maya's Python interpreter)
    - maya.OpenMayaMPx or maya.api.OpenMaya (plugin registration)
    - maya.app.general.mayaMixin (MayaQWidgetDockableMixin)
    - mca_qt (editor panel, theme, widgets)
    - mca_core (adapters, settings)
"""
