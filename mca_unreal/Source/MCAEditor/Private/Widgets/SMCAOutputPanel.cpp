// MCA Output Panel — Execution output display implementation.
//
// Shows Python execution output with color-coded severity.
// Equivalent to mca_qt/widgets/output_window.py.

#include "Widgets/SMCAOutputPanel.h"
#include "MCAEditorStyle.h"

#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/Text/SRichTextBlock.h"
#include "HAL/PlatformApplicationMisc.h"
#include "Misc/DateTime.h"

#define LOCTEXT_NAMESPACE "SMCAOutputPanel"


void SMCAOutputPanel::Construct(const FArguments& InArgs)
{
	bShowTimestamps = false;

	ChildSlot
	[
		SNew(SVerticalBox)

		// --- Toolbar (Clear, Copy, Timestamps toggle) ----------------------
		+ SVerticalBox::Slot()
		.AutoHeight()
		.Padding(4.0f, 2.0f)
		[
			SNew(SHorizontalBox)

			// "Output" label.
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(4.0f, 0.0f)
			[
				SNew(STextBlock)
				.Text(LOCTEXT("OutputLabel", "Output"))
				.ColorAndOpacity(FMCAEditorStyle::TextColor)
			]

			// Spacer.
			+ SHorizontalBox::Slot()
			.FillWidth(1.0f)
			[
				SNullWidget::NullWidget
			]

			// Clear button.
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(2.0f, 0.0f)
			[
				SNew(SButton)
				.Text(LOCTEXT("ClearButton", "Clear"))
				.OnClicked(this, &SMCAOutputPanel::OnClearClicked)
			]

			// Copy button.
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(2.0f, 0.0f)
			[
				SNew(SButton)
				.Text(LOCTEXT("CopyButton", "Copy"))
				.OnClicked(this, &SMCAOutputPanel::OnCopyClicked)
			]
		]

		// --- Output Text Area -----------------------------------------------
		+ SVerticalBox::Slot()
		.FillHeight(1.0f)
		[
			SAssignNew(ScrollBox, SScrollBox)
			+ SScrollBox::Slot()
			[
				SAssignNew(OutputTextBlock, SRichTextBlock)
				.DecoratorStyleSet(&FMCAEditorStyle::Get())
			]
		]
	];
}


void SMCAOutputPanel::AppendOutput(const FString& Text, const FString& Severity)
{
	// Build the display line with optional timestamp.
	FString DisplayText;
	if (bShowTimestamps)
	{
		FString Timestamp = FDateTime::Now().ToString(TEXT("[%H:%M:%S] "));
		DisplayText = Timestamp + Text;
	}
	else
	{
		DisplayText = Text;
	}

	// Store for GetAllText().
	OutputLines.Add(DisplayText);

	// Determine the style name based on severity.
	FString StyleName;
	if (Severity == TEXT("Error"))
	{
		StyleName = TEXT("MCAEditor.OutputError");
	}
	else if (Severity == TEXT("Warning"))
	{
		StyleName = TEXT("MCAEditor.OutputWarning");
	}
	else if (Severity == TEXT("Result"))
	{
		StyleName = TEXT("MCAEditor.OutputResult");
	}
	else
	{
		StyleName = TEXT("MCAEditor.OutputInfo");
	}

	// TODO: Append to the rich text block with the appropriate style.
	// SRichTextBlock uses a markup format — for now, append as plain text.
	// In Phase 2, use proper rich text runs for color coding.
	if (OutputTextBlock.IsValid())
	{
		// Build accumulated text for display.
		FString AllText;
		for (const FString& Line : OutputLines)
		{
			if (!AllText.IsEmpty())
			{
				AllText += TEXT("\n");
			}
			AllText += Line;
		}
		OutputTextBlock->SetText(FText::FromString(AllText));
	}

	// Auto-scroll to bottom.
	if (ScrollBox.IsValid())
	{
		ScrollBox->ScrollToEnd();
	}
}


void SMCAOutputPanel::ClearOutput()
{
	OutputLines.Empty();
	if (OutputTextBlock.IsValid())
	{
		OutputTextBlock->SetText(FText::GetEmpty());
	}
}


FString SMCAOutputPanel::GetAllText() const
{
	return FString::Join(OutputLines, TEXT("\n"));
}


void SMCAOutputPanel::ToggleTimestamps()
{
	bShowTimestamps = !bShowTimestamps;
}


FReply SMCAOutputPanel::OnClearClicked()
{
	ClearOutput();
	return FReply::Handled();
}


FReply SMCAOutputPanel::OnCopyClicked()
{
	FString AllText = GetAllText();
	FPlatformApplicationMisc::ClipboardCopy(*AllText);
	return FReply::Handled();
}


#undef LOCTEXT_NAMESPACE
