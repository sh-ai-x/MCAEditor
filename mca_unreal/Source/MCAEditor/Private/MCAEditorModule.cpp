// MCA Editor Module — Minimal plugin that launches the PySide6 editor.
//
// Registers a toolbar button and Window menu entry. When clicked,
// executes ue_editor_host.py which creates the MCA Editor as a
// free-floating Qt window owned by UE's main window.
//
// A periodic tick pumps Qt events so the editor stays responsive
// while UE owns the main loop.

#include "MCAEditorModule.h"
#include "MCAEditorCommands.h"
#include "MCAEditorStyle.h"

#include "Framework/Application/SlateApplication.h"
#include "Framework/Docking/TabManager.h"
#include "LevelEditor.h"
#include "ToolMenus.h"
#include "IPythonScriptPlugin.h"

// Define our custom log category.
DEFINE_LOG_CATEGORY(LogMCAEditor);

#define LOCTEXT_NAMESPACE "FMCAEditorModule"


void FMCAEditorModule::StartupModule()
{
	UE_LOG(LogMCAEditor, Log, TEXT("MCAEditor: StartupModule()"));

	// Initialize the Slate style set (icons only — no Slate widgets).
	FMCAEditorStyle::Initialize();
	FMCAEditorStyle::ReloadTextures();

	// Register the UI command set (just OpenMCAEditor).
	FMCAEditorCommands::Register();

	// Register toolbar and menu extensions once ToolMenus is ready.
	UToolMenus::RegisterStartupCallback(
		FSimpleMulticastDelegate::FDelegate::CreateRaw(this, &FMCAEditorModule::RegisterToolbarExtension)
	);
	RegisterMenuExtension();

	UE_LOG(LogMCAEditor, Log, TEXT("MCAEditor: StartupModule() done"));
}


void FMCAEditorModule::ShutdownModule()
{
	UE_LOG(LogMCAEditor, Log, TEXT("MCAEditor: ShutdownModule()"));

	// Stop the Qt tick.
	StopQtTick();

	// Close the Python editor window.
	RunPython(TEXT("import ue_editor_host; ue_editor_host.close()"));

	// Clean up.
	UToolMenus::UnRegisterStartupCallback(this);
	UToolMenus::UnregisterOwner(this);
	FMCAEditorCommands::Unregister();
	FMCAEditorStyle::Shutdown();
}


// --- Toolbar / Menu Registration -------------------------------------------

void FMCAEditorModule::RegisterToolbarExtension()
{
	UToolMenu* ToolbarMenu = UToolMenus::Get()->ExtendMenu(
		"LevelEditor.LevelEditorToolBar.PlayToolBar");
	if (ToolbarMenu)
	{
		FToolMenuSection& Section = ToolbarMenu->FindOrAddSection("MCAEditor");
		Section.AddEntry(FToolMenuEntry::InitToolBarButton(
			"OpenMCAEditor",
			FUIAction(FExecuteAction::CreateRaw(this, &FMCAEditorModule::OnToolbarButtonClicked)),
			LOCTEXT("ToolbarButton", "MCA Editor"),
			LOCTEXT("ToolbarTooltip", "Open the MCA Python Code Editor"),
			FSlateIcon(FMCAEditorStyle::GetStyleSetName(), "MCAEditor.ToolbarIcon")
		));

		UE_LOG(LogMCAEditor, Log, TEXT("MCAEditor: Toolbar button registered"));
	}
}


void FMCAEditorModule::RegisterMenuExtension()
{
	UToolMenu* WindowMenu = UToolMenus::Get()->ExtendMenu(
		"LevelEditor.MainMenu.Window");
	if (WindowMenu)
	{
		FToolMenuSection& Section = WindowMenu->FindOrAddSection("MCAEditor");
		Section.AddMenuEntry(
			"OpenMCAEditor",
			LOCTEXT("MenuEntry", "MCA Editor"),
			LOCTEXT("MenuTooltip", "Open the MCA Python Code Editor"),
			FSlateIcon(),
			FUIAction(FExecuteAction::CreateRaw(this, &FMCAEditorModule::OnToolbarButtonClicked))
		);
	}
}


void FMCAEditorModule::OnToolbarButtonClicked()
{
	UE_LOG(LogMCAEditor, Log, TEXT("MCAEditor: Toolbar button clicked — launching editor"));

	// Launch the PySide6 editor via the Python host script.
	RunPython(TEXT("import ue_editor_host; ue_editor_host.launch()"));

	// Start the Qt event pump tick if not already running.
	StartQtTick();
}


// --- Python Execution Helper -----------------------------------------------

void FMCAEditorModule::RunPython(const FString& Code)
{
	IPythonScriptPlugin* Python = IPythonScriptPlugin::Get();
	if (Python && Python->IsPythonAvailable())
	{
		FPythonCommandEx PythonCommand;
		PythonCommand.Command = Code;
		PythonCommand.ExecutionMode = EPythonCommandExecutionMode::ExecuteStatement;
		PythonCommand.FileExecutionScope = EPythonFileExecutionScope::Public;

		bool bSuccess = Python->ExecPythonCommandEx(PythonCommand);
		if (!bSuccess)
		{
			UE_LOG(LogMCAEditor, Error, TEXT("MCAEditor: Python exec failed: %s"),
				*PythonCommand.CommandResult);
		}

		// Log any Python output.
		for (const FPythonLogOutputEntry& Entry : PythonCommand.LogOutput)
		{
			switch (Entry.Type)
			{
			case EPythonLogOutputType::Error:
				UE_LOG(LogMCAEditor, Error, TEXT("Python: %s"), *Entry.Output);
				break;
			case EPythonLogOutputType::Warning:
				UE_LOG(LogMCAEditor, Warning, TEXT("Python: %s"), *Entry.Output);
				break;
			default:
				UE_LOG(LogMCAEditor, Log, TEXT("Python: %s"), *Entry.Output);
				break;
			}
		}
	}
	else
	{
		UE_LOG(LogMCAEditor, Error, TEXT("MCAEditor: Python not available — cannot launch editor"));
	}
}


// --- Qt Event Pump Tick ----------------------------------------------------

void FMCAEditorModule::StartQtTick()
{
	if (bTickActive)
	{
		return;
	}

	if (FSlateApplication::IsInitialized())
	{
		QtTickHandle = FSlateApplication::Get().OnPostTick().AddLambda(
			[this](float DeltaTime)
			{
				TickCounter++;
				// Pump Qt events every other frame (~30fps at 60fps UE).
				if (TickCounter % 2 == 0)
				{
					RunPython(TEXT("import ue_editor_host; ue_editor_host.tick()"));
				}
			}
		);
		bTickActive = true;
		UE_LOG(LogMCAEditor, Log, TEXT("MCAEditor: Qt tick started"));
	}
}


void FMCAEditorModule::StopQtTick()
{
	if (bTickActive && FSlateApplication::IsInitialized())
	{
		FSlateApplication::Get().OnPostTick().Remove(QtTickHandle);
		bTickActive = false;
		UE_LOG(LogMCAEditor, Log, TEXT("MCAEditor: Qt tick stopped"));
	}
}


#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FMCAEditorModule, MCAEditor)
