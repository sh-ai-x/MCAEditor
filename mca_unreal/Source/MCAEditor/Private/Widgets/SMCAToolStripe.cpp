// MCA Tool Stripe — Side button bar implementation.
//
// Vertical button bar for toggling bottom panels.
// Equivalent to mca_qt/widgets/tool_stripe.py.

#include "Widgets/SMCAToolStripe.h"
#include "MCAEditorStyle.h"

#include "Widgets/Input/SButton.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/Layout/SBox.h"

#define LOCTEXT_NAMESPACE "SMCAToolStripe"


void SMCAToolStripe::Construct(const FArguments& InArgs)
{
	ActiveButtonID = NAME_None;
	OnButtonToggledDelegate = InArgs._OnButtonToggled;

	ChildSlot
	[
		SNew(SBox)
		.WidthOverride(32.0f)
		[
			SAssignNew(ButtonContainer, SVerticalBox)
		]
	];
}


void SMCAToolStripe::AddButton(const FName& ButtonID, const FString& Label, const FString& ToolTip)
{
	ButtonIDs.Add(ButtonID);

	// Capture button ID for the lambda.
	FName CapturedID = ButtonID;

	ButtonContainer->AddSlot()
	.AutoHeight()
	.Padding(2.0f)
	[
		SNew(SButton)
		.Text(FText::FromString(Label))
		.ToolTipText(FText::FromString(ToolTip))
		.OnClicked(FOnClicked::CreateSP(this, &SMCAToolStripe::OnButtonClicked, CapturedID))
		.ButtonColorAndOpacity_Lambda([this, CapturedID]()
		{
			return CapturedID == ActiveButtonID
				? FMCAEditorStyle::AccentColor
				: FMCAEditorStyle::PanelColor;
		})
	];
}


void SMCAToolStripe::RemoveButton(const FName& ButtonID)
{
	ButtonIDs.Remove(ButtonID);

	if (ActiveButtonID == ButtonID)
	{
		ActiveButtonID = NAME_None;
	}

	// TODO: Remove the specific button widget from ButtonContainer.
	// For now, a full rebuild would be needed.
}


void SMCAToolStripe::SetActiveButton(const FName& ButtonID)
{
	ActiveButtonID = ButtonID;
}


FReply SMCAToolStripe::OnButtonClicked(FName ButtonID)
{
	// Toggle behavior: clicking the active button deactivates it.
	if (ActiveButtonID == ButtonID)
	{
		ActiveButtonID = NAME_None;
	}
	else
	{
		ActiveButtonID = ButtonID;
	}

	OnButtonToggledDelegate.ExecuteIfBound(ActiveButtonID);
	return FReply::Handled();
}


#undef LOCTEXT_NAMESPACE
