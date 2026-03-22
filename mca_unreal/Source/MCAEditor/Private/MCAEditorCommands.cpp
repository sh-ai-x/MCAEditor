// MCA Editor Commands — UI command registration.
//
// Only registers the "Open MCA Editor" command. All other editor actions
// (execute, save, find, etc.) live in the PySide6 Qt editor.

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
	// Open the MCA Editor window.
	UI_COMMAND(OpenMCAEditor, "Open MCA Editor", "Open the MCA Python Code Editor",
		EUserInterfaceActionType::Button, FInputChord());
}


#undef LOCTEXT_NAMESPACE
