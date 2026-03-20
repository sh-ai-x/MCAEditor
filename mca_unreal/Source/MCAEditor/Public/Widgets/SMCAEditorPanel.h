// MCA Editor Panel — Main container widget.
//
// Top-level Slate widget that arranges the toolbar, sidebar, code editor,
// output panel, and bottom panel (terminal/AI) using nested SSplitters.
// Mirrors the layout in mca_qt/editor_panel.py.

#pragma once

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/DeclarativeSyntaxSupport.h"

class FPythonBridge;
class SMCACodeEditor;
class SMCAOutputPanel;
class SMCASidebar;
class SMCATabBar;
class SMCAFindReplace;
class SMCAToolStripe;

/**
 * Main container widget for MCA Editor.
 *
 * Layout:
 *   +--------------------------------------------------------------+
 *   | [Execute] [Stop] [Language] [Connect]           Toolbar      |
 *   +----------+---------------------------------------------+----+
 *   |          | [tab1.py] [tab2.py] [+]                      |    |
 *   | Sidebar  |----------------------------------------------|Tool|
 *   | (tree)   |              Code Editor                     |Str.|
 *   |          |----------------------------------------------|    |
 *   |          |              Output Panel                    |    |
 *   +----------+---------------------------------------------+----+
 *   |                       Status Bar                             |
 *   +--------------------------------------------------------------+
 */
class SMCAEditorPanel : public SCompoundWidget
{
public:

	SLATE_BEGIN_ARGS(SMCAEditorPanel) {}
	SLATE_END_ARGS()

	/** Construct the widget. */
	void Construct(const FArguments& InArgs);

	/** Panel accepts keyboard focus so shortcuts work when docked. */
	virtual bool SupportsKeyboardFocus() const override { return true; }

	/** Route keyboard input through the command list. */
	virtual FReply OnKeyDown(const FGeometry& MyGeometry, const FKeyEvent& InKeyEvent) override;

private:

	// --- Toolbar Actions ---------------------------------------------------

	/** Execute the current script (or selection). */
	FReply OnExecuteClicked();

	/** Save the current file. */
	FReply OnSaveClicked();

	/** Open a file via system dialog. */
	FReply OnOpenClicked();

	/** Create a new empty file tab. */
	FReply OnNewFileClicked();

	// --- Layout Builders ---------------------------------------------------

	/** Build the toolbar row. */
	TSharedRef<SWidget> BuildToolbar();

	/** Build the status bar row. */
	TSharedRef<SWidget> BuildStatusBar();

	// --- File Operations ---------------------------------------------------

	/** Open a file by path into a new tab. */
	void OpenFile(const FString& FilePath);

	/** Save the currently active file. */
	void SaveCurrentFile();

	/** Called when the sidebar requests a file open. */
	void OnSidebarFileSelected(const FString& FilePath);

	/** Called when a tab is selected. */
	void OnTabSelected(int32 TabIndex);

	/** Called when a tab is closed. */
	void OnTabClosed(int32 TabIndex);

	// --- Status Bar Updates ------------------------------------------------

	/** Called when the code editor cursor position changes. */
	void OnCursorPositionChanged(int32 Line, int32 Column);

	/** Update the status bar text (cursor position, file info). */
	void UpdateStatusBar();

	// --- Child Widgets -----------------------------------------------------

	/** Python execution bridge. */
	TSharedPtr<FPythonBridge> PythonBridge;

	/** Code editor widget. */
	TSharedPtr<SMCACodeEditor> CodeEditor;

	/** Output panel widget. */
	TSharedPtr<SMCAOutputPanel> OutputPanel;

	/** Sidebar file tree widget. */
	TSharedPtr<SMCASidebar> Sidebar;

	/** Tab bar widget. */
	TSharedPtr<SMCATabBar> TabBar;

	/** Find/replace bar (overlay). */
	TSharedPtr<SMCAFindReplace> FindReplaceBar;

	/** Tool stripe (right side buttons). */
	TSharedPtr<SMCAToolStripe> ToolStripe;

	// --- Status Bar --------------------------------------------------------

	/** Status bar text block (cursor pos, encoding, etc.). */
	TSharedPtr<STextBlock> StatusBarText;

	/** Connection status indicator. */
	TSharedPtr<STextBlock> ConnectionStatusText;

	// --- Command Binding ---------------------------------------------------

	/** Command list mapping keyboard shortcuts to actions. */
	TSharedPtr<FUICommandList> CommandList;

	/** Bind all keyboard shortcuts to their handler functions. */
	void BindCommands();

	// --- Shortcut Actions --------------------------------------------------

	/** Toggle the find bar (Ctrl+F). */
	void OnToggleFind();

	/** Toggle the find+replace bar (Ctrl+H). */
	void OnToggleFindReplace();

	/** Open quick-open dialog (Ctrl+P). */
	void OnQuickOpen();

	/** Open go-to-line dialog (Ctrl+G). */
	void OnGoToLine();

	/** Toggle comment on current line (Ctrl+/). */
	void OnToggleComment();

	/** Quick-open panel widget. */
	TSharedPtr<class SMCAQuickOpen> QuickOpenPanel;
};
