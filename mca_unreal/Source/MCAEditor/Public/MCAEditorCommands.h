// MCA Editor Commands — UI command definitions.
//
// Declares the slash command set for toolbar buttons and keyboard shortcuts.
// Each command maps to an action in the editor panel (Execute, Save, Open, etc.).

#pragma once

#include "CoreMinimal.h"
#include "Framework/Commands/Commands.h"
#include "MCAEditorStyle.h"

/**
 * UI command set for MCA Editor actions.
 *
 * Registered with Slate's command system so they can be bound to toolbar
 * buttons, menu items, and keyboard shortcuts simultaneously.
 */
class FMCAEditorCommands : public TCommands<FMCAEditorCommands>
{
public:

	FMCAEditorCommands();

	// --- TCommands Interface -----------------------------------------------

	/** Register all commands. Called once during module startup. */
	virtual void RegisterCommands() override;

public:

	// --- Command Definitions -----------------------------------------------

	/** Open the MCA Editor tab. */
	TSharedPtr<FUICommandInfo> OpenMCAEditor;

	/** Execute the current script (Shift+Enter). */
	TSharedPtr<FUICommandInfo> ExecuteCode;

	/** Save the current file (Ctrl+S). */
	TSharedPtr<FUICommandInfo> SaveFile;

	/** Open a file (Ctrl+O). */
	TSharedPtr<FUICommandInfo> OpenFile;

	/** Create a new file (Ctrl+N). */
	TSharedPtr<FUICommandInfo> NewFile;

	/** Toggle find/replace bar (Ctrl+F). */
	TSharedPtr<FUICommandInfo> FindReplace;

	/** Open quick-open dialog (Ctrl+P). */
	TSharedPtr<FUICommandInfo> QuickOpen;

	/** Go to line (Ctrl+G). */
	TSharedPtr<FUICommandInfo> GoToLine;

	/** Toggle comment on selected lines (Ctrl+/). */
	TSharedPtr<FUICommandInfo> ToggleComment;
};
