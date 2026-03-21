// MCA Editor Module — Public header.
//
// Declares the editor module that registers the MCA Editor tab, toolbar
// button, and menu entries. This is the entry point for the entire plugin.

#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"
#include "Delegates/IDelegateInstance.h"

// Custom log category for the MCA Editor plugin.
// NOTE: LogTemp is suppressed from the file log in UE 5.6 — always use this.
DECLARE_LOG_CATEGORY_EXTERN(LogMCAEditor, Log, All);

class FToolBarBuilder;
class FExtender;

/**
 * Main module for the MCA Editor plugin.
 *
 * Handles tab spawner registration, toolbar/menu integration, and
 * module lifecycle. Mirrors the role of plugin_main.py in the Maya version.
 */
class FMCAEditorModule : public IModuleInterface
{
public:

	// --- IModuleInterface --------------------------------------------------

	/** Called when the module is loaded (PostEngineInit phase). */
	virtual void StartupModule() override;

	/** Called when the module is unloaded. */
	virtual void ShutdownModule() override;

private:

	// --- Tab Management ----------------------------------------------------

	/** Spawns the MCA Editor tab when the user opens it. */
	TSharedRef<class SDockTab> SpawnMCAEditorTab(const class FSpawnTabArgs& Args);

	/** Builds the license key entry UI shown when trial has expired. */
	TSharedRef<SWidget> BuildLicensePanel(TSharedRef<class SDockTab> OwnerTab);

	// --- Toolbar / Menu Registration ---------------------------------------

	/** Registers the toolbar extension button. */
	void RegisterToolbarExtension();

	/** Registers the Window menu entry. */
	void RegisterMenuExtension();

	/** Callback when the toolbar button is clicked. */
	void OnToolbarButtonClicked();

	/** Called when the MCA Editor tab is closed by the user. */
	void OnTabClosed(TSharedRef<SDockTab> ClosedTab);

	// --- Config Helpers ----------------------------------------------------

	/** Read a string from the MCAEditor config section. */
	static FString GetConfigString(const FString& Key, const FString& Default = TEXT(""));

	/** Write a string to the MCAEditor config section and flush. */
	static void SetConfigString(const FString& Key, const FString& Value);

	// --- Members -----------------------------------------------------------

	/** Toolbar extender handle for cleanup on shutdown. */
	TSharedPtr<FExtender> ToolbarExtender;

	/** Delegate handle for the OnPostTick auto-open callback. */
	FDelegateHandle PostTickHandle;

	/** Tab ID constant — matches the spawner registration. */
	static const FName MCAEditorTabName;
};
