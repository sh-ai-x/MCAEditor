# 2026-03-20 — Unreal Engine Plugin Phase 2 Implementation

## Summary
Implemented all Phase 2 features for the UE native Slate plugin: syntax highlighting
tokenizer, line numbers gutter, cursor position tracking, toggle comment, indent/dedent,
output panel color coding, and tab context menu.

## Decision: No Remote Execution Spike
The spike (`tools/ue_remote_exec_spike.py`) was deemed unnecessary since the editor is
embedded natively in UE using Slate — PythonBridge uses `IPythonScriptPlugin` in-process,
not the Remote Execution TCP protocol.

## Changes

### `SMCACodeEditor.cpp` — Syntax Highlighting Tokenizer
- Replaced single-run placeholder `TokenizeLine()` with full character-walking tokenizer
- New `TokenizeLineIntoTokens()` method produces flat `FToken` list
- Token types: `Default`, `Keyword`, `Builtin`, `String`, `Comment`, `Number`, `Decorator`
- String handling: single/double/triple quotes, f/r/b/u prefixes, multi-line tracking
- Number handling: int, float, hex (0x), binary (0b), octal (0o), exponents, complex (j)
- Decorators: `@` detected only at line start (not matmul operator)
- Builtins: only highlighted when followed by `(` (avoids coloring variable names)
- Helper methods: `IsStringStart()`, `ConsumeString()`, `FindTripleQuoteEnd()`,
  `ConsumeNumber()`, `IsDecoratorPosition()`, `IsIdentStart()`, `IsIdentChar()`,
  `IsWordBoundary()`, `IsWordEnd()`
- Added `MultiLineQuoteChar` member to track which quote char (' or ") the multi-line uses

### `SMCACodeEditor.cpp/.h` — Line Numbers Gutter
- Added `STextBlock` line numbers widget in a 50px `SBox` to the left of the editor
- `UpdateLineNumbers()` counts newlines and rebuilds the line numbers string
- Called from `HandleTextChanged()` and `SetText()` so it stays in sync

### `SMCACodeEditor.cpp/.h` — Cursor Position Tracking
- `GetCursorLine()` / `GetCursorColumn()` now use `TextBox->GetCursorLocation()`
- Added `HandleCursorMoved()` callback wired to `SMultiLineEditableTextBox::OnCursorMoved`
- Fires `OnCursorMovedDelegate` with 1-based line/column
- Added `FTextLayout.h` include for `FTextLocation`

### `SMCAEditorPanel.cpp/.h` — Status Bar Cursor Updates
- Added `OnCursorPositionChanged(int32, int32)` handler
- Wired to `SMCACodeEditor::OnCursorMoved` delegate
- Status bar now shows live cursor position

### `SMCACodeEditor.cpp` — Toggle Comment
- `ToggleComment()` detects if all affected lines are commented (starts with `#`)
- If all commented: removes first `# ` or `#` from each line
- If not all commented: adds `# ` after leading whitespace on each line

### `SMCACodeEditor.cpp` — Indent / Dedent
- `IndentSelection()` prepends spaces or tab based on `UMCAEditorSettings`
- `DedentSelection()` removes up to TabSize leading spaces or one tab
- Both read `TabSize` and `bUseSpaces` from project settings

### `SMCAOutputPanel.cpp/.h` — Rich Text Color Coding
- Replaced `SRichTextBlock` with per-line `STextBlock` widgets in `SVerticalBox`
- Each output line gets its own color based on severity:
  - Error = `ErrorColor` (red)
  - Warning = `WarningColor` (yellow)
  - Result = `ResultColor` (cyan)
  - Info = `TextColor` (default white)
- `ClearOutput()` now calls `ClearChildren()` on the container
- Monospace font (Mono, 11pt) for output text

### `SMCATabBar.cpp/.h` — Tab Context Menu
- Implemented `BuildTabContextMenu()` with `FMenuBuilder`
- Actions: Close, Close Others, Close All, Copy Path
- `OnContextMenuClose()`, `OnContextMenuCloseOthers()`, `OnContextMenuCloseAll()`,
  `OnContextMenuCopyPath()` handler methods
- Tab buttons wrapped in `SMenuAnchor` for right-click support
- Added `SMenuAnchor.h` and `PlatformApplicationMisc.h` includes

## Files Modified
- `Source/MCAEditor/Private/Widgets/SMCACodeEditor.cpp` — tokenizer, line numbers, cursor, comment, indent
- `Source/MCAEditor/Public/Widgets/SMCACodeEditor.h` — new declarations
- `Source/MCAEditor/Private/Widgets/SMCAEditorPanel.cpp` — cursor change handler
- `Source/MCAEditor/Public/Widgets/SMCAEditorPanel.h` — new declaration
- `Source/MCAEditor/Private/Widgets/SMCAOutputPanel.cpp` — full rewrite (per-line color)
- `Source/MCAEditor/Public/Widgets/SMCAOutputPanel.h` — updated widget members
- `Source/MCAEditor/Private/Widgets/SMCATabBar.cpp` — context menu + SMenuAnchor
- `Source/MCAEditor/Public/Widgets/SMCATabBar.h` — context menu declarations

## Phase 3 (same session)

### `SMCAEditorPanel.cpp/.h` — Keyboard Shortcut Binding
- Added `FUICommandList` member and `BindCommands()` wiring all 8 shortcuts
- `OnKeyDown()` override routes through command list, plus Tab/Shift+Tab and Escape
- Lambdas wrap FReply-returning methods for FExecuteAction compatibility
- `SupportsKeyboardFocus()` returns true so shortcuts fire when panel is focused

### `SMCAEditorPanel.cpp/.h` — Go To Line Dialog
- `OnGoToLine()` spawns modal `SWindow` with line number input
- Enter commits and calls `CodeEditor->GoToLine()`, then closes dialog

### `SMCAEditorPanel.cpp/.h` — Quick Open Panel
- `SMCAQuickOpen` added as centered overlay on the code editor area
- `OnQuickOpen()` calls `QuickOpenPanel->Show()` (Ctrl+P)
- Wired `OnFileSelected` to `OnSidebarFileSelected()` (reused open logic)

### `SMCACodeEditor.cpp/.h` — SelectRange / ReplaceSelectedText
- `SelectRange(StartOffset, Length)` converts char offset to FTextLocation and selects
- `ReplaceSelectedText(NewText)` calculates selection start and does string replacement

### `SMCAFindReplace.cpp/.h` — Full Find/Replace Implementation
- `DoSearch()` now stores `MatchOffsets` array and `MatchLength`
- Selects current match in the editor after each search
- `OnFindNext()`/`OnFindPrev()` navigate through matches with selection
- `OnReplace()` replaces current match then re-runs search
- `OnReplaceAll()` replaces all matches (working backwards to preserve offsets)
- Whole-word mode implemented (boundary checks at match start/end)

### `SMCASidebar.cpp/.h` — Context Menu
- `OnContextMenuOpening()` builds `FMenuBuilder` menu from selected tree item
- 6 actions: New File, New Folder, Rename, Delete, Reveal in Explorer, Copy Path
- `OnContextMenuNewFile()` creates `untitled.py` with auto-numbering
- `OnContextMenuNewFolder()` creates `new_folder` with auto-numbering
- `OnContextMenuRename()` spawns modal dialog with current name
- `OnContextMenuDelete()` removes file or directory recursively
- `OnContextMenuRevealInExplorer()` uses `FPlatformProcess::ExploreFolder()`
- `OnContextMenuCopyPath()` copies to clipboard

## Additional Files Modified (Phase 3)
- `Source/MCAEditor/Private/Widgets/SMCAEditorPanel.cpp` — shortcuts, overlays, actions
- `Source/MCAEditor/Public/Widgets/SMCAEditorPanel.h` — command list, new methods
- `Source/MCAEditor/Private/Widgets/SMCACodeEditor.cpp` — SelectRange, ReplaceSelectedText
- `Source/MCAEditor/Public/Widgets/SMCACodeEditor.h` — new declarations
- `Source/MCAEditor/Private/Widgets/SMCAFindReplace.cpp` — full replace logic
- `Source/MCAEditor/Public/Widgets/SMCAFindReplace.h` — match tracking members
- `Source/MCAEditor/Private/Widgets/SMCASidebar.cpp` — context menu + 6 actions
- `Source/MCAEditor/Public/Widgets/SMCASidebar.h` — context menu declarations

## Phase 4 — License Check System

### `MCALicenseCheck.h` / `MCALicenseCheck.cpp` — Offline License Validation
- Ported from `mca_core/license.py` to C++ (same HMAC secret, same key format)
- `FMCALicenseResult` struct: bValid, bPerpetual, ExpiryDate, DaysRemaining, Error
- `FMCALicenseStatus` struct: bLicensed, bTrial, DaysRemaining, bNeedsKey, Message
- `ValidateKey()`: base32 decode → HMAC-SHA256 verify → expiry check
- `CheckLicense()`: stored key → trial period → needs_key fallthrough
- `StoreKey()`: validates then persists to UE config
- HMAC-SHA256 via OpenSSL (bundled with UE), added `AddEngineThirdPartyPrivateStaticDependencies`
- Base32 decode implemented inline (RFC 4648)
- Trial period: 14 days from first launch, stored in `GEditorPerProjectIni`
- Date epoch: 2025-01-01 UTC (unix 1735689600), matching Python implementation

### `MCAEditorModule.cpp` — License Gate in SpawnMCAEditorTab
- `SpawnMCAEditorTab()` now calls `FMCALicenseCheck::CheckLicense()` before creating editor
- If `bNeedsKey`: shows `BuildLicensePanel()` (key input + Activate button) instead of editor
- If licensed/trial active: shows full `SMCAEditorPanel` as before
- `BuildLicensePanel()`: centered UI with title, message, key input, status label, activate button
- On successful activation: replaces license panel with `SMCAEditorPanel` in-place
- On failure: shows validation error in red status text

### `MCAEditor.Build.cs` — Updated Dependencies
- Added `DesktopPlatform` module
- Added `OpenSSL` via `AddEngineThirdPartyPrivateStaticDependencies`

## Files Modified (Phase 4)
- `Source/MCAEditor/Public/MCALicenseCheck.h` — NEW: license validation header
- `Source/MCAEditor/Private/MCALicenseCheck.cpp` — NEW: full implementation
- `Source/MCAEditor/Private/MCAEditorModule.cpp` — license gate + license panel
- `Source/MCAEditor/Public/MCAEditorModule.h` — BuildLicensePanel declaration
- `Source/MCAEditor/MCAEditor.Build.cs` — OpenSSL + DesktopPlatform deps

## Phase 5 — Test Compile (UE 5.6)

### Compile Fixes for UE 5.6 Compatibility
- `SMultiLineEditableTextBox.h` moved from `Widgets/Text/` to `Widgets/Input/` in 5.6
- `ITextLayoutMarshaller` gained 4 new abstract methods: `RequiresLiveUpdate()`, `MakeDirty()`, `ClearDirty()`, `IsDirty()`
- `FTextLayout::FNewLineData` constructor now requires `TSharedRef<FString>` + runs (was just runs)
- `SelectText()` removed from `SMultiLineEditableTextBox` (only on inner `SMultiLineEditableText`, which is protected)
- OpenSSL `namespace UI` conflict with `typedef UI` in `ossl_typ.h` — replaced with inline SHA-256 implementation
- `FSimpleDelegate::CreateSP` can't take methods returning `FReply` — wrapped in lambda
- Missing linker symbols: added `DeveloperSettings` and `ApplicationCore` to module deps

### Build Result
- **Target**: UE56Test project (UE 5.6, Win64, Development)
- **Status**: All 19 compilation/linking actions succeeded
- Plugin DLL: `UnrealEditor-MCAEditor.dll` built successfully

## Next Steps
1. Plugin icon / branding resources
2. Test runtime behavior in UE editor
