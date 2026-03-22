# Session Notes — 2026-03-21: UE Plugin Pivot to PySide6 Embedding

## Summary

Pivoted the UE plugin from native Slate C++ widgets to embedding the existing PySide6 MCA Editor (same codebase as Maya) as a free-floating Qt window. This eliminates the need to recreate the entire editor UI in Slate and gives UE the exact same editor experience as Maya.

## What Changed

### Architecture Pivot
- **Deleted** all 8 Slate widget files (SMCACodeEditor, SMCAEditorPanel, SMCAOutputPanel, SMCATabBar, SMCASidebar, SMCAFindReplace, SMCAQuickOpen, SMCAToolStripe)
- **Deleted** PythonBridge.h/.cpp, MCAEditorSettings.h/.cpp, MCALicenseCheck.h/.cpp
- **Rewrote** MCAEditorModule.h/.cpp — minimal plugin that registers toolbar button + Window menu, launches Python host, pumps Qt events via OnPostTick
- **Stripped** MCAEditorCommands.h/.cpp to just `OpenMCAEditor` command
- **Stripped** MCAEditorStyle.h/.cpp to just toolbar/tab icons
- **Simplified** MCAEditor.Build.cs — removed unused deps, added PythonScriptPlugin as proper dependency
- **Created** `ue_editor_host.py` — Python host script that creates MCAEditorPanel with `dcc_version="UE5"`

### C++ Plugin (7 source files total)
- `MCAEditorModule.h/cpp` — `OnToolbarButtonClicked()` calls `RunPython("import ue_editor_host; ue_editor_host.launch()")`, `StartQtTick()` pumps Qt events via `FSlateApplication::OnPostTick`
- `MCAEditorCommands.h/cpp` — Single command: OpenMCAEditor
- `MCAEditorStyle.h/cpp` — Just Icon16.png and Icon40.png
- `MCAEditor.Build.cs` — Core, CoreUObject, Engine, Slate, SlateCore, InputCore, UnrealEd, ToolMenus, Projects, PythonScriptPlugin

### Python Host Script (`ue_editor_host.py`)
- Sets up managed venv with PySide6 via `mca_core.venv_manager`
- Creates `MCAEditorPanel(settings, adapter_manager=None, dcc_version="UE5")`
- Uses `Qt.WindowStaysOnTopHint` to keep editor above UE
- Strips MEL from language combo, hides MEL menu actions, closes MEL tabs
- Sets `_embedded_in_dcc = True` to hide "No DCC" indicator
- `UELogTailer` class tails UE's log file and pipes new lines to the output panel
- Filters noisy internal categories (LogSlate, LogStreaming, etc.)
- Routes log severity to appropriate output panel methods (error=red, warning=yellow)
- Uses `unreal.log()` for UE-visible logging (Python `logging` module doesn't route to UE)

### Execution Pipeline
- Code execution uses `_execute_locally()` in editor_panel.py (same as standalone mode)
- `exec()` with stdout/stderr redirect captures output
- Executed code is echoed to UE's Output Log: `[MCAEditor] Exec: <preview>`
- stdout/errors also echoed to UE's log for cross-reference

## Build & Deploy Process
- Source lives in `E:\Projects\MCAEditor\mca_unreal\`
- Must manually sync to `D:\Unreal-Projects\UE56Test\Plugins\MCAEditor\`
- Build: `"C:/Program Files/Epic Games/UE_5.6/Engine/Build/BatchFiles/Build.bat" UE56TestEditor Win64 Development -Project="D:/Unreal-Projects/UE56Test/UE56Test.uproject"`
- `.uplugin` has `CanContainContent: true` for Content/Python/ directory

## Bugs Fixed During Session
1. `Entry.SeverityType` → `Entry.Type` (UE 5.6 `FPythonLogOutputEntry` API difference)
2. `additional_packages=` → `requirements=` (correct `venv_manager.setup_venv()` parameter name)
3. Module-level auto-launch guard (`__name__ == "ue_editor_host"`) removed — caused double launch on import
4. Added `unreal.log()` throughout for UE Output Log visibility (Python `logging` goes to Python log, not UE)
5. Pre-installed PySide6 + deps into managed venv for Python 3.11
6. `GetForegroundWindow()` HWND ownership unreliable → switched to `Qt.WindowStaysOnTopHint`
7. MEL tabs restored from session.json → cleaned session, removed MEL_2.mel
8. "No DCC connected" indicator visible → set `_embedded_in_dcc = True`

## Known Issues / TODO
- UE log tailing not showing in MCA Editor output panel yet — tailer starts but tick may not be pumping poll() frequently enough, or the log file read isn't picking up new lines
- Qt tick pump runs every other frame (~30fps) — may need to tune frequency
- Session restore may recreate MEL buffers if session.json isn't cleaned
- No UE adapter for remote execution — all code runs locally via `exec()` in UE's Python interpreter
