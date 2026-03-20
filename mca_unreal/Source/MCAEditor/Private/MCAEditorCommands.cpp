// MCA Editor Commands — UI command registration.
//
// Defines keyboard shortcuts and command metadata for all editor actions.

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
	// Open the MCA Editor tab.
	UI_COMMAND(OpenMCAEditor, "Open MCA Editor", "Open the MCA Python Code Editor",
		EUserInterfaceActionType::Button, FInputChord());

	// Execute the current script or selection.
	UI_COMMAND(ExecuteCode, "Execute", "Execute the current script or selection",
		EUserInterfaceActionType::Button, FInputChord(EKeys::Enter, EModifierKey::Shift));

	// Save the current file.
	UI_COMMAND(SaveFile, "Save", "Save the current file",
		EUserInterfaceActionType::Button, FInputChord(EKeys::S, EModifierKey::Control));

	// Open a file.
	UI_COMMAND(OpenFile, "Open File", "Open a Python file",
		EUserInterfaceActionType::Button, FInputChord(EKeys::O, EModifierKey::Control));

	// Create a new file.
	UI_COMMAND(NewFile, "New File", "Create a new Python file",
		EUserInterfaceActionType::Button, FInputChord(EKeys::N, EModifierKey::Control));

	// Toggle find/replace bar.
	UI_COMMAND(FindReplace, "Find / Replace", "Toggle the find and replace bar",
		EUserInterfaceActionType::Button, FInputChord(EKeys::F, EModifierKey::Control));

	// Quick open file picker.
	UI_COMMAND(QuickOpen, "Quick Open", "Open the quick file picker",
		EUserInterfaceActionType::Button, FInputChord(EKeys::P, EModifierKey::Control));

	// Go to line.
	UI_COMMAND(GoToLine, "Go To Line", "Jump to a specific line number",
		EUserInterfaceActionType::Button, FInputChord(EKeys::G, EModifierKey::Control));

	// Toggle comment on selected lines.
	UI_COMMAND(ToggleComment, "Toggle Comment", "Toggle line comment on selection",
		EUserInterfaceActionType::Button, FInputChord(EKeys::Slash, EModifierKey::Control));
}


#undef LOCTEXT_NAMESPACE
