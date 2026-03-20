// MCA Native Host — PySide6/Qt embedding implementation.
//
// Hosts the full MCA Editor (PySide6) inside a UE docked tab by
// reparenting the Qt widget as a Win32 child window and keeping it
// positioned to match the Slate geometry on every tick.
//
// When the user docks/undocks a tab, UE destroys the floating window,
// which also destroys our child HWND. The Python-side _mca_reparent()
// detects this via IsWindow() and recreates the native handle using
// destroy()+create() while preserving all widget state.

#include "Widgets/SMCANativeHost.h"
#include "MCAEditorModule.h"
#include "MCAEditorStyle.h"
#include "IPythonScriptPlugin.h"

#include "Interfaces/IPluginManager.h"
#include "Misc/Paths.h"
#include "Framework/Application/SlateApplication.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/Layout/SBox.h"

// Win32 API for coordinate conversion (ClientToScreen).
#include "Windows/AllowWindowsPlatformTypes.h"
#include <Windows.h>
#include "Windows/HideWindowsPlatformTypes.h"

#define LOCTEXT_NAMESPACE "SMCANativeHost"


void SMCANativeHost::Construct(const FArguments& InArgs)
{
	ParentWindowHandle = nullptr;
	bEditorLaunched = false;
	bLaunchAttempted = false;
	bQtWidgetHidden = false;
	LastX = LastY = LastWidth = LastHeight = 0;
	PumpThrottle = 0;

	// Start with a fallback message that gets hidden once Qt loads.
	ChildSlot
	[
		SNew(SBox)
		.HAlign(HAlign_Center)
		.VAlign(VAlign_Center)
		[
			SAssignNew(FallbackText, STextBlock)
			.Text(LOCTEXT("Loading", "Loading MCA Editor..."))
			.ColorAndOpacity(FMCAEditorStyle::TextColor)
			.Font(FCoreStyle::GetDefaultFontStyle("Regular", 14))
		]
	];
}


SMCANativeHost::~SMCANativeHost()
{
	CleanupPythonEditor();
}


void* SMCANativeHost::FindContainingWindowHandle()
{
	// Find the native window that contains THIS widget.
	// When the tab is docked, this is the main editor window.
	// When undocked (floating), this is the floating tab window.
	// Using FindWidgetWindow instead of GetActiveTopLevelWindow
	// so we always get the correct window regardless of focus.
	TSharedPtr<SWindow> ContainingWindow = FSlateApplication::Get().FindWidgetWindow(AsShared());
	if (ContainingWindow.IsValid())
	{
		TSharedPtr<FGenericWindow> NativeWindow = ContainingWindow->GetNativeWindow();
		if (NativeWindow.IsValid())
		{
			return NativeWindow->GetOSWindowHandle();
		}
	}
	return nullptr;
}


void SMCANativeHost::LaunchPythonEditor()
{
	bLaunchAttempted = true;

	// --- Verify Python is available ---
	if (!FModuleManager::Get().IsModuleLoaded("PythonScriptPlugin"))
	{
		ShowFallbackMessage(TEXT("Python Script Plugin is not enabled.\nEnable it in Edit > Plugins > Python."));
		return;
	}

	IPythonScriptPlugin* PythonPlugin = IPythonScriptPlugin::Get();
	if (!PythonPlugin)
	{
		ShowFallbackMessage(TEXT("Could not get Python Script Plugin instance."));
		return;
	}

	// --- Pass the UE window HWND to Python ---
	FPythonCommandEx SetHwndCmd;
	SetHwndCmd.Command = FString::Printf(
		TEXT("_mca_ue_parent_hwnd = %lld"),
		(int64)(intptr_t)ParentWindowHandle
	);
	SetHwndCmd.ExecutionMode = EPythonCommandExecutionMode::ExecuteStatement;
	SetHwndCmd.FileExecutionScope = EPythonFileExecutionScope::Public;
	PythonPlugin->ExecPythonCommandEx(SetHwndCmd);

	// --- Execute the editor setup script ---
	FString PluginDir = IPluginManager::Get().FindPlugin("MCAEditor")->GetBaseDir();
	FString SetupScript = FPaths::Combine(PluginDir, TEXT("Content"), TEXT("Python"), TEXT("ue_editor_host.py"));

	if (!FPaths::FileExists(SetupScript))
	{
		ShowFallbackMessage(FString::Printf(TEXT("Setup script not found:\n%s"), *SetupScript));
		return;
	}

	UE_LOG(LogMCAEditor, Log, TEXT("MCAEditor: Launching Qt editor from %s"), *SetupScript);

	// Execute as a file — variables persist in the public scope.
	FPythonCommandEx SetupCmd;
	SetupCmd.Command = SetupScript;
	SetupCmd.ExecutionMode = EPythonCommandExecutionMode::ExecuteFile;
	SetupCmd.FileExecutionScope = EPythonFileExecutionScope::Public;

	bool bSuccess = PythonPlugin->ExecPythonCommandEx(SetupCmd);

	if (!bSuccess)
	{
		// Collect any error output from the setup script.
		FString ErrorMsg = TEXT("Failed to launch MCA Editor.\n\n");
		if (!SetupCmd.CommandResult.IsEmpty())
		{
			ErrorMsg += SetupCmd.CommandResult;
		}
		for (const FPythonLogOutputEntry& Entry : SetupCmd.LogOutput)
		{
			if (Entry.Type == EPythonLogOutputType::Error)
			{
				ErrorMsg += Entry.Output + TEXT("\n");
			}
		}
		ShowFallbackMessage(ErrorMsg);
		return;
	}

	// --- Success — hide the fallback text ---
	bEditorLaunched = true;
	if (FallbackText.IsValid())
	{
		FallbackText->SetVisibility(EVisibility::Collapsed);
	}

	UE_LOG(LogMCAEditor, Log, TEXT("MCAEditor: Qt editor launched successfully"));
}


void SMCANativeHost::ReparentQtWidget()
{
	// Tell Python to reparent the Qt widget into the new UE window.
	// If the old HWND was destroyed (dock/undock kills child windows),
	// Python will recreate it via destroy()+create() before reparenting.
	IPythonScriptPlugin* PythonPlugin = IPythonScriptPlugin::Get();
	if (!PythonPlugin)
	{
		return;
	}

	FPythonCommandEx ReparentCmd;
	ReparentCmd.Command = FString::Printf(
		TEXT("_mca_reparent(%lld)"),
		(int64)(intptr_t)ParentWindowHandle
	);
	ReparentCmd.ExecutionMode = EPythonCommandExecutionMode::ExecuteStatement;
	ReparentCmd.FileExecutionScope = EPythonFileExecutionScope::Public;
	PythonPlugin->ExecPythonCommandEx(ReparentCmd);

	UE_LOG(LogMCAEditor, Log, TEXT("MCAEditor: Reparented Qt widget to HWND=0x%llX"),
		(int64)(intptr_t)ParentWindowHandle);
}


void SMCANativeHost::HideQtWidget()
{
	// Hide the Qt widget when the tab is backgrounded or has no visible area.
	// Only call Python when transitioning from visible to hidden.
	if (bQtWidgetHidden)
	{
		return;
	}

	IPythonScriptPlugin* PythonPlugin = IPythonScriptPlugin::Get();
	if (PythonPlugin)
	{
		FPythonCommandEx HideCmd;
		HideCmd.Command = TEXT("_mca_hide_qt()");
		HideCmd.ExecutionMode = EPythonCommandExecutionMode::ExecuteStatement;
		HideCmd.FileExecutionScope = EPythonFileExecutionScope::Public;
		PythonPlugin->ExecPythonCommandEx(HideCmd);
	}

	bQtWidgetHidden = true;
}


void SMCANativeHost::CleanupPythonEditor()
{
	if (!bEditorLaunched)
	{
		return;
	}

	IPythonScriptPlugin* PythonPlugin = IPythonScriptPlugin::Get();
	if (PythonPlugin)
	{
		FPythonCommandEx CleanupCmd;
		CleanupCmd.Command = TEXT("_mca_cleanup_qt()");
		CleanupCmd.ExecutionMode = EPythonCommandExecutionMode::ExecuteStatement;
		CleanupCmd.FileExecutionScope = EPythonFileExecutionScope::Public;
		PythonPlugin->ExecPythonCommandEx(CleanupCmd);
	}

	bEditorLaunched = false;
	UE_LOG(LogMCAEditor, Log, TEXT("MCAEditor: Qt editor cleaned up"));
}


void SMCANativeHost::ShowFallbackMessage(const FString& Message)
{
	UE_LOG(LogMCAEditor, Error, TEXT("MCAEditor: %s"), *Message);

	if (FallbackText.IsValid())
	{
		FallbackText->SetText(FText::FromString(Message));
		FallbackText->SetVisibility(EVisibility::Visible);
	}
}


void SMCANativeHost::Tick(const FGeometry& AllottedGeometry, const double InCurrentTime, const float InDeltaTime)
{
	SCompoundWidget::Tick(AllottedGeometry, InCurrentTime, InDeltaTime);

	// --- Find containing window (tracks dock/undock transitions) ---
	void* CurrentParentHandle = FindContainingWindowHandle();

	// --- Launch the Python editor on first tick with valid geometry ---
	if (!bLaunchAttempted)
	{
		if (CurrentParentHandle)
		{
			ParentWindowHandle = CurrentParentHandle;

			FVector2D Size = AllottedGeometry.GetAbsoluteSize();
			// Wait for the Slate layout to stabilize (meaningful size).
			if (Size.X > 50 && Size.Y > 50)
			{
				LaunchPythonEditor();
			}
		}
		return;
	}

	if (!bEditorLaunched)
	{
		return;
	}

	// --- Hide the Qt widget when tab is backgrounded ---
	// When another tab is selected in the same dock area, Slate still
	// ticks us but with zero/tiny geometry. Hide the Qt child window
	// so it doesn't cover the active tab.
	FVector2D AbsSize = AllottedGeometry.GetAbsoluteSize();
	if (AbsSize.X < 10 || AbsSize.Y < 10)
	{
		HideQtWidget();
		return;
	}

	// --- Detect parent window change (dock/undock) ---
	// When the tab is docked vs floating, it lives in a different
	// native window. The Qt child must be reparented (and possibly
	// have its HWND recreated if the old parent was destroyed).
	if (CurrentParentHandle && CurrentParentHandle != ParentWindowHandle)
	{
		ParentWindowHandle = CurrentParentHandle;
		ReparentQtWidget();

		// Force geometry update on next cycle since coordinates are
		// relative to the new parent window.
		LastX = LastY = LastWidth = LastHeight = 0;
	}

	// --- Throttle: pump Qt events every other frame (~30fps) ---
	// A text editor doesn't need 60fps event processing.
	PumpThrottle++;
	if (PumpThrottle < 2)
	{
		return;
	}
	PumpThrottle = 0;

	// --- Calculate window-relative position for the Qt widget ---
	// The Qt widget is a child window (via SetParent), so coordinates
	// are relative to the parent window's client area.
	FVector2D AbsPos = AllottedGeometry.GetAbsolutePosition();

	// Convert from screen space to parent window client space.
	POINT ClientOrigin = {0, 0};
	ClientToScreen((HWND)ParentWindowHandle, &ClientOrigin);

	int32 RelX = (int32)(AbsPos.X - ClientOrigin.x);
	int32 RelY = (int32)(AbsPos.Y - ClientOrigin.y);
	int32 Width = (int32)AbsSize.X;
	int32 Height = (int32)AbsSize.Y;

	// Mark as visible (will be shown by _mca_tick's ShowWindow call).
	bQtWidgetHidden = false;

	// --- Call Python: update geometry + pump Qt events ---
	IPythonScriptPlugin* PythonPlugin = IPythonScriptPlugin::Get();
	if (!PythonPlugin)
	{
		return;
	}

	// Batch geometry update and event pump into one Python call.
	if (RelX != LastX || RelY != LastY || Width != LastWidth || Height != LastHeight)
	{
		LastX = RelX;
		LastY = RelY;
		LastWidth = Width;
		LastHeight = Height;

		FPythonCommandEx TickCmd;
		TickCmd.Command = FString::Printf(
			TEXT("_mca_tick(%d, %d, %d, %d)"),
			RelX, RelY, Width, Height
		);
		TickCmd.ExecutionMode = EPythonCommandExecutionMode::ExecuteStatement;
		TickCmd.FileExecutionScope = EPythonFileExecutionScope::Public;
		PythonPlugin->ExecPythonCommandEx(TickCmd);
	}
	else
	{
		// No geometry change — just pump Qt events.
		FPythonCommandEx PumpCmd;
		PumpCmd.Command = TEXT("_mca_pump_qt()");
		PumpCmd.ExecutionMode = EPythonCommandExecutionMode::ExecuteStatement;
		PumpCmd.FileExecutionScope = EPythonFileExecutionScope::Public;
		PythonPlugin->ExecPythonCommandEx(PumpCmd);
	}
}


#undef LOCTEXT_NAMESPACE
