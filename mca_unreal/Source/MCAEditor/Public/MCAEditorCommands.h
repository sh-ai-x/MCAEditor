// MCA Editor Commands — UI command definitions.
//
// Declares the command set for toolbar buttons and menu entries.
// Keyboard shortcuts are handled by the embedded Qt editor directly.

#pragma once

#include "CoreMinimal.h"
#include "Framework/Commands/Commands.h"
#include "MCAEditorStyle.h"

/**
 * UI command set for MCA Editor actions.
 *
 * Only the tab-open command is registered here. All editor keyboard
 * shortcuts (Ctrl+S, Ctrl+F, etc.) are handled by the embedded
 * PySide6/Qt editor widget internally.
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
};
