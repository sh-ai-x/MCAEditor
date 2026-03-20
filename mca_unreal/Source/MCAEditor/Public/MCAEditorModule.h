// MCA Editor Module — Public header.
//
// Declares the editor module that registers the MCA Editor tab, toolbar
// button, and menu entries. This is the entry point for the entire plugin.

#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"

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

	// --- Toolbar / Menu Registration ---------------------------------------

	/** Registers the toolbar extension button. */
	void RegisterToolbarExtension();

	/** Registers the Window menu entry. */
	void RegisterMenuExtension();

	/** Callback when the toolbar button is clicked. */
	void OnToolbarButtonClicked();

	// --- Members -----------------------------------------------------------

	/** Toolbar extender handle for cleanup on shutdown. */
	TSharedPtr<FExtender> ToolbarExtender;

	/** Tab ID constant — matches the spawner registration. */
	static const FName MCAEditorTabName;
};
