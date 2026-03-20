// MCA Output Panel — Execution output display.
//
// Read-only text widget that shows Python execution output with
// color-coded severity (info, warning, error, result). Mirrors
// the output_window.py in the Maya version.

#pragma once

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/DeclarativeSyntaxSupport.h"

/**
 * Output panel for displaying Python execution results.
 *
 * Features:
 *   - Color-coded output (info=white, warning=yellow, error=red, result=cyan)
 *   - Timestamps (toggleable)
 *   - Clear / copy buttons
 *   - Ctrl+F search within output
 *   - Right-click context menu
 *   - Auto-scroll to bottom on new output
 */
class SMCAOutputPanel : public SCompoundWidget
{
public:

	SLATE_BEGIN_ARGS(SMCAOutputPanel) {}
	SLATE_END_ARGS()

	/** Construct the widget. */
	void Construct(const FArguments& InArgs);

	// --- Output Methods ----------------------------------------------------

	/**
	 * Append text to the output panel.
	 *
	 * @param Text     The text to append.
	 * @param Severity "Info", "Warning", "Error", or "Result" for color coding.
	 */
	void AppendOutput(const FString& Text, const FString& Severity = TEXT("Info"));

	/** Clear all output text. */
	void ClearOutput();

	/** Get all output text as a single string. */
	FString GetAllText() const;

	/** Toggle timestamp display on/off. */
	void ToggleTimestamps();

private:

	// --- Event Handlers ----------------------------------------------------

	/** Clear button callback. */
	FReply OnClearClicked();

	/** Copy button callback. */
	FReply OnCopyClicked();

	// --- Child Widgets -----------------------------------------------------

	/** Rich text block for colored output display. */
	TSharedPtr<class SRichTextBlock> OutputTextBlock;

	/** Scroll box wrapping the output text. */
	TSharedPtr<class SScrollBox> ScrollBox;

	// --- State -------------------------------------------------------------

	/** Whether to show timestamps before each line. */
	bool bShowTimestamps;

	/** Accumulated output lines for GetAllText(). */
	TArray<FString> OutputLines;
};
