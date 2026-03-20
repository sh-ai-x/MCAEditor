// MCA Native Host — Embeds PySide6/Qt inside a Slate tab.
//
// Creates a lightweight Slate widget that hosts the full MCA Editor
// (PySide6/Qt) as an owned top-level window. On every tick it:
//   1. Detects parent window changes (dock/undock) and updates ownership
//   2. Repositions the Qt widget to match the Slate geometry
//   3. Pumps QApplication.processEvents() for Qt event handling
//   4. Hides the Qt widget when the tab is backgrounded
//
// Uses child parenting (SetParent) for pixel-perfect embedding. When UE
// destroys the parent during dock/undock, the Python side detects the dead
// HWND and recreates it via destroy()+create(), preserving all widget state.

#pragma once

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/DeclarativeSyntaxSupport.h"

/**
 * Native window host for embedding the PySide6-based MCA Editor.
 *
 * The C++ side is intentionally thin — all editor logic lives in
 * Python (mca_qt/editor_panel.py), identical to the Maya version.
 * This widget just handles:
 *   - Finding the containing UE window HWND (tracks dock/undock)
 *   - Launching the Python editor on first tick
 *   - Keeping the Qt widget positioned over our Slate area
 *   - Hiding/showing the Qt widget on tab switches
 *   - Pumping Qt events from UE's tick
 *   - Cleanup on destruction
 */
class SMCANativeHost : public SCompoundWidget
{
public:

	SLATE_BEGIN_ARGS(SMCANativeHost) {}
	SLATE_END_ARGS()

	/** Construct the widget. */
	void Construct(const FArguments& InArgs);

	/** Clean up the Python editor. */
	virtual ~SMCANativeHost();

	/** Called every frame — repositions Qt widget and pumps events. */
	virtual void Tick(const FGeometry& AllottedGeometry, const double InCurrentTime, const float InDeltaTime) override;

private:

	/** Find the native window that contains this widget (changes on dock/undock). */
	void* FindContainingWindowHandle();

	/** Execute the Python setup script to create the Qt editor. */
	void LaunchPythonEditor();

	/** Update the Qt widget's owner to the new UE window (called on dock/undock). */
	void ReparentQtWidget();

	/** Hide the Qt widget when the tab is backgrounded. */
	void HideQtWidget();

	/** Tell Python to clean up the Qt editor. */
	void CleanupPythonEditor();

	/** Show a fallback error message if Python setup fails. */
	void ShowFallbackMessage(const FString& Message);

	// --- State -------------------------------------------------------------

	/** Current owner UE window handle (HWND on Windows). Changes on dock/undock. */
	void* ParentWindowHandle;

	/** Whether the Python editor has been launched successfully. */
	bool bEditorLaunched;

	/** Whether launch was attempted (prevents repeated failures). */
	bool bLaunchAttempted;

	/** Whether the Qt widget is currently hidden (backgrounded tab). */
	bool bQtWidgetHidden;

	/** Last known geometry for change detection (absolute screen coords). */
	int32 LastX, LastY, LastWidth, LastHeight;

	/** Frame counter for throttling Qt event pumping. */
	int32 PumpThrottle;

	/** Fallback text block shown when Python/Qt is not available. */
	TSharedPtr<STextBlock> FallbackText;
};
