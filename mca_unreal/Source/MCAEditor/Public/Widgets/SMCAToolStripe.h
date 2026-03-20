// MCA Tool Stripe — Side button bar.
//
// Vertical button bar on the right side of the editor panel for toggling
// panels like terminal and AI chat. Mirrors tool_stripe.py.

#pragma once

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/DeclarativeSyntaxSupport.h"

/** Delegate fired when a stripe button is toggled. */
DECLARE_DELEGATE_OneParam(FOnStripeButtonToggled, const FName& /* ButtonID */);

/**
 * Vertical button bar for panel toggles.
 *
 * Sits on the right edge of the editor panel. Each button toggles
 * a bottom panel (terminal, AI chat, etc.) similar to VS Code's
 * activity bar.
 */
class SMCAToolStripe : public SCompoundWidget
{
public:

	SLATE_BEGIN_ARGS(SMCAToolStripe) {}
		/** Called when any stripe button is toggled. */
		SLATE_EVENT(FOnStripeButtonToggled, OnButtonToggled)
	SLATE_END_ARGS()

	/** Construct the widget. */
	void Construct(const FArguments& InArgs);

	/**
	 * Add a button to the stripe.
	 *
	 * @param ButtonID  Unique identifier for the button.
	 * @param Label     Display text (short, like "Terminal" or "AI").
	 * @param ToolTip   Tooltip text.
	 */
	void AddButton(const FName& ButtonID, const FString& Label, const FString& ToolTip);

	/** Remove a button by ID. */
	void RemoveButton(const FName& ButtonID);

	/** Set the active (pressed) button. Pass NAME_None to deactivate all. */
	void SetActiveButton(const FName& ButtonID);

private:

	/** Handle a stripe button click. */
	FReply OnButtonClicked(FName ButtonID);

	// --- State -------------------------------------------------------------

	/** Container for the button widgets. */
	TSharedPtr<SVerticalBox> ButtonContainer;

	/** Currently active button ID. */
	FName ActiveButtonID;

	/** Registered button IDs for tracking. */
	TArray<FName> ButtonIDs;

	// --- Delegates ---------------------------------------------------------

	FOnStripeButtonToggled OnButtonToggledDelegate;
};
