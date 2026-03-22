// MCA Editor Commands — UI command definitions.
//
// Declares the command set for the toolbar button. Only one command
// is needed — OpenMCAEditor. All editor actions live in PySide6.

#pragma once

#include "CoreMinimal.h"
#include "Framework/Commands/Commands.h"
#include "MCAEditorStyle.h"

/**
 * UI command set for MCA Editor actions.
 *
 * Only registers OpenMCAEditor — all other editor functionality
 * (execute, save, find, etc.) is handled by the PySide6 Qt editor.
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

	/** Open the MCA Editor window. */
	TSharedPtr<FUICommandInfo> OpenMCAEditor;
};
