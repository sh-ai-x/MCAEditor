// MCA Editor Module — Public header.
//
// Declares the minimal editor module that launches the PySide6 MCA Editor
// as a free-floating Qt window owned by UE's main window. All editor UI
// lives in PySide6/Qt — this C++ module just provides the toolbar button,
// Window menu entry, and a periodic tick to pump Qt events.

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
 * Registers a toolbar button and Window > MCA Editor menu entry.
 * When clicked, executes ue_editor_host.py which creates the PySide6
 * MCA Editor as a free-floating Qt window owned by UE's main window.
 *
 * A periodic tick pumps Qt events so the editor stays responsive
 * while UE owns the main loop.
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

	// --- Toolbar / Menu Registration ---------------------------------------

	/** Registers the toolbar extension button. */
	void RegisterToolbarExtension();

	/** Registers the Window menu entry. */
	void RegisterMenuExtension();

	/** Callback when the toolbar button is clicked. */
	void OnToolbarButtonClicked();

	// --- Python Execution --------------------------------------------------

	/** Execute a Python statement in UE's embedded interpreter. */
	void RunPython(const FString& Code);

	// --- Qt Event Pump Tick ------------------------------------------------

	/** Start the periodic Qt event pump. */
	void StartQtTick();

	/** Stop the periodic Qt event pump. */
	void StopQtTick();

	/** Get the native HWND of UE's main editor window (for Win32 ownership). */
	uint64 GetMainWindowHWND() const;

	/** Delegate handle for the OnPostTick Qt pump callback. */
	FDelegateHandle QtTickHandle;

	/** Whether the Qt tick is currently active. */
	bool bTickActive = false;

	/** Frame counter for throttling Qt event pumps. */
	uint32 TickCounter = 0;
};
