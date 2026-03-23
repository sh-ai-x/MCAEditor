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
#include "Widgets/SWindow.h"
#include "GenericPlatform/GenericWindow.h"
#include "LevelEditor.h"
#include "ToolMenus.h"
#include "IPythonScriptPlugin.h"
#include "Containers/Ticker.h"

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

	// Schedule an auto-launch check after a short delay. If the editor was
	// open when UE last closed, this re-opens it automatically so the user
	// picks up right where they left off. The delay ensures Slate's main
	// window is fully created (needed for the HWND owner-window setup).
	FTSTicker::GetCoreTicker().AddTicker(
		FTickerDelegate::CreateLambda([this](float DeltaTime) -> bool
		{
			uint64 MainHWND = GetMainWindowHWND();
			if (MainHWND == 0)
			{
				// Slate window not ready yet — keep retrying.
				return true;
			}

			UE_LOG(LogMCAEditor, Log, TEXT("MCAEditor: Checking auto-launch (HWND = 0x%llX)"), MainHWND);

			// Ask Python if the editor should auto-open. The Python side
			// checks QSettings and only launches if was_open == True.
			FString AutoCmd = FString::Printf(
				TEXT("import ue_editor_host; ue_editor_host.auto_launch(ue_hwnd=0x%llX)"),
				MainHWND
			);
			RunPython(AutoCmd);

			// Start the Qt tick if not already running — needed for
			// processEvents() and log tailing if the editor auto-opened.
			StartQtTick();

			return false;  // One-shot — don't repeat.
		}),
		2.0f  // 2 second delay for Slate to finish initialization.
	);
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


uint64 FMCAEditorModule::GetMainWindowHWND() const
{
	if (!FSlateApplication::IsInitialized())
	{
		UE_LOG(LogMCAEditor, Warning, TEXT("MCAEditor: SlateApplication not initialized — cannot get HWND"));
		return 0;
	}

	// Try the active top-level window first — this is the main editor window
	// when the user clicks the toolbar button.
	TSharedPtr<SWindow> MainWindow = FSlateApplication::Get().GetActiveTopLevelWindow();

	// Fallback: iterate all interactive top-level windows and pick the first.
	// The main editor window is always the first one registered.
	if (!MainWindow.IsValid())
	{
		TArray<TSharedRef<SWindow>> TopLevelWindows;
		FSlateApplication::Get().GetAllVisibleWindowsOrdered(TopLevelWindows);
		if (TopLevelWindows.Num() > 0)
		{
			MainWindow = TopLevelWindows[0];
		}
	}

	if (!MainWindow.IsValid())
	{
		UE_LOG(LogMCAEditor, Warning, TEXT("MCAEditor: No top-level window found — cannot get HWND"));
		return 0;
	}

	// GetNativeWindow() returns the platform window handle; GetOSWindowHandle()
	// gives us the raw void* HWND on Windows.
	TSharedPtr<FGenericWindow> NativeWindow = MainWindow->GetNativeWindow();
	if (!NativeWindow.IsValid())
	{
		UE_LOG(LogMCAEditor, Warning, TEXT("MCAEditor: Native window is null — cannot get HWND"));
		return 0;
	}

	void* RawHWND = NativeWindow->GetOSWindowHandle();
	return reinterpret_cast<uint64>(RawHWND);
}


void FMCAEditorModule::OnToolbarButtonClicked()
{
	UE_LOG(LogMCAEditor, Log, TEXT("MCAEditor: Toolbar button clicked — launching editor"));

	// Get UE's main window HWND so the Python editor can set it as the
	// Win32 owner window.  This makes the editor float above UE only —
	// not above every window on the desktop.
	uint64 MainHWND = GetMainWindowHWND();
	UE_LOG(LogMCAEditor, Log, TEXT("MCAEditor: Main window HWND = 0x%llX"), MainHWND);

	// Launch the PySide6 editor, passing UE's HWND for owner-window setup.
	FString LaunchCmd = FString::Printf(
		TEXT("import ue_editor_host; ue_editor_host.launch(ue_hwnd=0x%llX)"),
		MainHWND
	);
	RunPython(LaunchCmd);

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
