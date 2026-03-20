// MCA Editor Module — Plugin entry point and tab registration.
//
// Registers the MCA Editor nomad tab spawner, toolbar button, and
// Window menu entry. This is the C++ equivalent of plugin_main.py
// in the Maya version.

#include "MCAEditorModule.h"
#include "MCAEditorCommands.h"
#include "MCAEditorStyle.h"
#include "Widgets/SMCAEditorPanel.h"

#include "Framework/Docking/TabManager.h"
#include "Framework/MultiBox/MultiBoxBuilder.h"
#include "LevelEditor.h"
#include "ToolMenus.h"
#include "Widgets/Docking/SDockTab.h"

#define LOCTEXT_NAMESPACE "FMCAEditorModule"

// Tab name constant — used for spawner registration and invocation.
const FName FMCAEditorModule::MCAEditorTabName(TEXT("MCAEditor"));


void FMCAEditorModule::StartupModule()
{
	// Initialize the Slate style set (dark theme colors, fonts).
	FMCAEditorStyle::Initialize();
	FMCAEditorStyle::ReloadTextures();

	// Register the UI command set (Execute, Save, Open, etc.).
	FMCAEditorCommands::Register();

	// --- Nomad Tab Spawner ------------------------------------------------
	// Register a global (nomad) tab that can be docked anywhere in the
	// UE editor layout, just like Output Log or Content Browser.
	FGlobalTabmanager::Get()->RegisterNomadTabSpawner(
		MCAEditorTabName,
		FOnSpawnTab::CreateRaw(this, &FMCAEditorModule::SpawnMCAEditorTab)
	)
	.SetDisplayName(LOCTEXT("TabTitle", "MCA Editor"))
	.SetMenuType(ETabSpawnerMenuType::Enabled)
	.SetTooltipText(LOCTEXT("TabTooltip", "Open the MCA Python Code Editor"))
	.SetIcon(FSlateIcon(FMCAEditorStyle::GetStyleSetName(), "MCAEditor.TabIcon"));

	// Register toolbar and menu extensions once ToolMenus is ready.
	UToolMenus::RegisterStartupCallback(
		FSimpleMulticastDelegate::FDelegate::CreateRaw(this, &FMCAEditorModule::RegisterToolbarExtension)
	);
	RegisterMenuExtension();
}


void FMCAEditorModule::ShutdownModule()
{
	// Clean up in reverse order of registration.
	UToolMenus::UnRegisterStartupCallback(this);
	UToolMenus::UnregisterOwner(this);

	FMCAEditorCommands::Unregister();
	FMCAEditorStyle::Shutdown();

	FGlobalTabmanager::Get()->UnregisterNomadTabSpawner(MCAEditorTabName);
}


TSharedRef<SDockTab> FMCAEditorModule::SpawnMCAEditorTab(const FSpawnTabArgs& Args)
{
	// TODO: Activation check — validate license before creating editor panel.
	// Mirror the pattern from mca_core/license.py (HMAC-SHA256 offline validation).
	// Until implemented, the plugin is unprotected.
	// See: mca_core/license.py for the key format and validation logic.

	return SNew(SDockTab)
		.TabRole(NomadTab)
		[
			SNew(SMCAEditorPanel)
		];
}


void FMCAEditorModule::RegisterToolbarExtension()
{
	// Add a toolbar button to the main editor toolbar under the "Misc" section.
	UToolMenu* ToolbarMenu = UToolMenus::Get()->ExtendMenu("LevelEditor.LevelEditorToolBar.PlayToolBar");
	if (ToolbarMenu)
	{
		FToolMenuSection& Section = ToolbarMenu->FindOrAddSection("MCAEditor");
		Section.AddEntry(FToolMenuEntry::InitToolBarButton(
			"OpenMCAEditor",
			FUIAction(FExecuteAction::CreateRaw(this, &FMCAEditorModule::OnToolbarButtonClicked)),
			LOCTEXT("ToolbarButton", "MCA Editor"),
			LOCTEXT("ToolbarButtonTooltip", "Open the MCA Python Code Editor"),
			FSlateIcon(FMCAEditorStyle::GetStyleSetName(), "MCAEditor.ToolbarIcon")
		));
	}
}


void FMCAEditorModule::RegisterMenuExtension()
{
	// Add "MCA Editor" entry under the Window menu.
	UToolMenu* WindowMenu = UToolMenus::Get()->ExtendMenu("LevelEditor.MainMenu.Window");
	if (WindowMenu)
	{
		FToolMenuSection& Section = WindowMenu->FindOrAddSection("MCAEditor");
		Section.AddMenuEntry(
			"OpenMCAEditor",
			LOCTEXT("MenuEntry", "MCA Editor"),
			LOCTEXT("MenuEntryTooltip", "Open the MCA Python Code Editor"),
			FSlateIcon(),
			FUIAction(FExecuteAction::CreateRaw(this, &FMCAEditorModule::OnToolbarButtonClicked))
		);
	}
}


void FMCAEditorModule::OnToolbarButtonClicked()
{
	// Invoke the tab — if it already exists, focus it; otherwise spawn it.
	FGlobalTabmanager::Get()->TryInvokeTab(MCAEditorTabName);
}


#undef LOCTEXT_NAMESPACE

// Register the module with UE's module system.
IMPLEMENT_MODULE(FMCAEditorModule, MCAEditor)
