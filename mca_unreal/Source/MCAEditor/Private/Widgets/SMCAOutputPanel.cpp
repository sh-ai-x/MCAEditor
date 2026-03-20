// MCA Output Panel — Execution output display implementation.
//
// Shows Python execution output with color-coded severity using
// individual STextBlock widgets per line. Equivalent to
// mca_qt/widgets/output_window.py.

#include "Widgets/SMCAOutputPanel.h"
#include "MCAEditorStyle.h"

#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Text/STextBlock.h"
#include "HAL/PlatformApplicationMisc.h"
#include "Misc/DateTime.h"

#define LOCTEXT_NAMESPACE "SMCAOutputPanel"


void SMCAOutputPanel::Construct(const FArguments& InArgs)
{
	bShowTimestamps = false;

	ChildSlot
	[
		SNew(SVerticalBox)

		// --- Toolbar (Clear, Copy) ------------------------------------------
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

		// --- Output Lines Container -----------------------------------------
		+ SVerticalBox::Slot()
		.FillHeight(1.0f)
		[
			SAssignNew(ScrollBox, SScrollBox)
			+ SScrollBox::Slot()
			[
				SAssignNew(OutputLinesContainer, SVerticalBox)
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

	// Determine the color based on severity.
	FSlateColor TextColor;
	if (Severity == TEXT("Error"))
	{
		TextColor = FSlateColor(FMCAEditorStyle::ErrorColor);
	}
	else if (Severity == TEXT("Warning"))
	{
		TextColor = FSlateColor(FMCAEditorStyle::WarningColor);
	}
	else if (Severity == TEXT("Result"))
	{
		TextColor = FSlateColor(FMCAEditorStyle::ResultColor);
	}
	else
	{
		TextColor = FSlateColor(FMCAEditorStyle::TextColor);
	}

	// Add a new STextBlock for this output line.
	if (OutputLinesContainer.IsValid())
	{
		OutputLinesContainer->AddSlot()
		.AutoHeight()
		.Padding(8.0f, 1.0f)
		[
			SNew(STextBlock)
			.Text(FText::FromString(DisplayText))
			.ColorAndOpacity(TextColor)
			.Font(FCoreStyle::GetDefaultFontStyle("Mono", 11))
		];
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
	if (OutputLinesContainer.IsValid())
	{
		OutputLinesContainer->ClearChildren();
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
