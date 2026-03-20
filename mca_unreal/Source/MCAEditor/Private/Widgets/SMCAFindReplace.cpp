// MCA Find/Replace Bar — Search and replace overlay implementation.
//
// Overlay bar for Ctrl+F / Ctrl+H operations with regex support.
// Equivalent to mca_qt/widgets/find_replace_bar.py.

#include "Widgets/SMCAFindReplace.h"
#include "Widgets/SMCACodeEditor.h"
#include "MCAEditorStyle.h"

#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SCheckBox.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/Layout/SBox.h"

#define LOCTEXT_NAMESPACE "SMCAFindReplace"


void SMCAFindReplace::Construct(const FArguments& InArgs)
{
	CodeEditorRef = InArgs._CodeEditor;
	bShowReplace = false;
	bUseRegex = false;
	bCaseSensitive = false;
	bWholeWord = false;
	CurrentMatchIndex = 0;
	TotalMatches = 0;

	// Start hidden.
	SetVisibility(EVisibility::Collapsed);

	ChildSlot
	[
		SNew(SVerticalBox)

		// --- Find Row ------------------------------------------------------
		+ SVerticalBox::Slot()
		.AutoHeight()
		.Padding(4.0f, 2.0f)
		[
			SNew(SHorizontalBox)

			// Search input.
			+ SHorizontalBox::Slot()
			.FillWidth(1.0f)
			.Padding(2.0f, 0.0f)
			[
				SAssignNew(SearchBox, SEditableTextBox)
				.HintText(LOCTEXT("SearchHint", "Find..."))
				.OnTextChanged_Lambda([this](const FText& NewText) { DoSearch(); })
			]

			// Match count display.
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(4.0f, 0.0f)
			.VAlign(VAlign_Center)
			[
				SAssignNew(MatchCountText, STextBlock)
				.Text(LOCTEXT("NoMatches", "0 matches"))
				.ColorAndOpacity(FMCAEditorStyle::LineNumberColor)
			]

			// Find Previous button.
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(2.0f, 0.0f)
			[
				SNew(SButton)
				.Text(LOCTEXT("FindPrev", "<"))
				.ToolTipText(LOCTEXT("FindPrevTooltip", "Find Previous"))
				.OnClicked(this, &SMCAFindReplace::OnFindPrev)
			]

			// Find Next button.
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(2.0f, 0.0f)
			[
				SNew(SButton)
				.Text(LOCTEXT("FindNext", ">"))
				.ToolTipText(LOCTEXT("FindNextTooltip", "Find Next"))
				.OnClicked(this, &SMCAFindReplace::OnFindNext)
			]

			// Regex toggle.
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(4.0f, 0.0f)
			[
				SNew(SCheckBox)
				.ToolTipText(LOCTEXT("RegexToggle", "Use Regular Expression"))
				.OnCheckStateChanged_Lambda([this](ECheckBoxState State) { bUseRegex = (State == ECheckBoxState::Checked); DoSearch(); })
				[
					SNew(STextBlock).Text(LOCTEXT("RegexLabel", ".*"))
				]
			]

			// Case-sensitive toggle.
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(2.0f, 0.0f)
			[
				SNew(SCheckBox)
				.ToolTipText(LOCTEXT("CaseToggle", "Match Case"))
				.OnCheckStateChanged_Lambda([this](ECheckBoxState State) { bCaseSensitive = (State == ECheckBoxState::Checked); DoSearch(); })
				[
					SNew(STextBlock).Text(LOCTEXT("CaseLabel", "Aa"))
				]
			]

			// Close button.
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(4.0f, 0.0f)
			[
				SNew(SButton)
				.Text(LOCTEXT("Close", "x"))
				.OnClicked(this, &SMCAFindReplace::OnCloseClicked)
			]
		]

		// --- Replace Row (conditionally visible) ---------------------------
		+ SVerticalBox::Slot()
		.AutoHeight()
		.Padding(4.0f, 2.0f)
		[
			SAssignNew(ReplaceRow, SHorizontalBox)
			.Visibility_Lambda([this]() { return bShowReplace ? EVisibility::Visible : EVisibility::Collapsed; })

			// Replace input.
			+ SHorizontalBox::Slot()
			.FillWidth(1.0f)
			.Padding(2.0f, 0.0f)
			[
				SAssignNew(ReplaceBox, SEditableTextBox)
				.HintText(LOCTEXT("ReplaceHint", "Replace..."))
			]

			// Replace button.
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(2.0f, 0.0f)
			[
				SNew(SButton)
				.Text(LOCTEXT("Replace", "Replace"))
				.OnClicked(this, &SMCAFindReplace::OnReplace)
			]

			// Replace All button.
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(2.0f, 0.0f)
			[
				SNew(SButton)
				.Text(LOCTEXT("ReplaceAll", "Replace All"))
				.OnClicked(this, &SMCAFindReplace::OnReplaceAll)
			]
		]
	];
}


void SMCAFindReplace::ShowFind()
{
	bShowReplace = false;
	SetVisibility(EVisibility::Visible);

	// Focus the search box.
	if (SearchBox.IsValid())
	{
		FSlateApplication::Get().SetKeyboardFocus(SearchBox);
	}
}


void SMCAFindReplace::ShowFindReplace()
{
	bShowReplace = true;
	SetVisibility(EVisibility::Visible);

	if (SearchBox.IsValid())
	{
		FSlateApplication::Get().SetKeyboardFocus(SearchBox);
	}
}


void SMCAFindReplace::Hide()
{
	SetVisibility(EVisibility::Collapsed);
}


bool SMCAFindReplace::IsBarVisible() const
{
	return GetVisibility() == EVisibility::Visible;
}


void SMCAFindReplace::DoSearch()
{
	if (!SearchBox.IsValid() || !CodeEditorRef.IsValid())
	{
		return;
	}

	FString Query = SearchBox->GetText().ToString();
	if (Query.IsEmpty())
	{
		TotalMatches = 0;
		CurrentMatchIndex = 0;
		MatchCountText->SetText(LOCTEXT("NoMatches", "0 matches"));
		return;
	}

	// Get the editor text and count matches.
	FString EditorText = CodeEditorRef->GetText().ToString();

	// Simple substring search (TODO: regex and case-sensitive modes).
	TotalMatches = 0;
	int32 SearchStart = 0;
	while (true)
	{
		int32 FoundIndex = bCaseSensitive
			? EditorText.Find(Query, ESearchCase::CaseSensitive, ESearchDir::FromStart, SearchStart)
			: EditorText.Find(Query, ESearchCase::IgnoreCase, ESearchDir::FromStart, SearchStart);

		if (FoundIndex == INDEX_NONE)
		{
			break;
		}

		TotalMatches++;
		SearchStart = FoundIndex + 1;
	}

	// Update match count display.
	if (TotalMatches > 0)
	{
		CurrentMatchIndex = FMath::Clamp(CurrentMatchIndex, 1, TotalMatches);
		MatchCountText->SetText(FText::Format(
			LOCTEXT("MatchCount", "{0} of {1}"),
			FText::AsNumber(CurrentMatchIndex),
			FText::AsNumber(TotalMatches)
		));
	}
	else
	{
		CurrentMatchIndex = 0;
		MatchCountText->SetText(LOCTEXT("NoResults", "No results"));
	}
}


FReply SMCAFindReplace::OnFindNext()
{
	if (TotalMatches > 0)
	{
		CurrentMatchIndex = (CurrentMatchIndex % TotalMatches) + 1;
		DoSearch();
	}
	return FReply::Handled();
}


FReply SMCAFindReplace::OnFindPrev()
{
	if (TotalMatches > 0)
	{
		CurrentMatchIndex = CurrentMatchIndex > 1 ? CurrentMatchIndex - 1 : TotalMatches;
		DoSearch();
	}
	return FReply::Handled();
}


FReply SMCAFindReplace::OnReplace()
{
	// TODO Phase 3: Implement single match replacement.
	return FReply::Handled();
}


FReply SMCAFindReplace::OnReplaceAll()
{
	// TODO Phase 3: Implement replace all.
	return FReply::Handled();
}


FReply SMCAFindReplace::OnCloseClicked()
{
	Hide();
	return FReply::Handled();
}


#undef LOCTEXT_NAMESPACE
