// MCA Editor Commands — UI command registration.
//
// Defines command metadata for editor actions. Keyboard shortcuts are
// handled by the embedded Qt editor, so only the tab-open command is
// registered here for the toolbar/menu button.

#include "MCAEditorCommands.h"

#define LOCTEXT_NAMESPACE "FMCAEditorCommands"


FMCAEditorCommands::FMCAEditorCommands()
	: TCommands<FMCAEditorCommands>(
		TEXT("MCAEditor"),                                     // Context name
		LOCTEXT("ContextDescription", "MCA Code Editor"),      // Context description
		NAME_None,                                             // Parent context
		FMCAEditorStyle::GetStyleSetName()                     // Style set name
	)
{
}


void FMCAEditorCommands::RegisterCommands()
{
	// Open the MCA Editor tab (toolbar/menu button, no keyboard shortcut).
	UI_COMMAND(OpenMCAEditor, "Open MCA Editor", "Open the MCA Python Code Editor",
		EUserInterfaceActionType::Button, FInputChord());
}


#undef LOCTEXT_NAMESPACE
