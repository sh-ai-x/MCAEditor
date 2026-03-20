// MCA Quick Open — Ctrl+P file picker implementation.
//
// Modal popup with fuzzy file search. Equivalent to
// mca_qt/widgets/quick_open.py.

#include "Widgets/SMCAQuickOpen.h"
#include "MCAEditorStyle.h"

#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/Layout/SBox.h"
#include "HAL/FileManager.h"

#define LOCTEXT_NAMESPACE "SMCAQuickOpen"


void SMCAQuickOpen::Construct(const FArguments& InArgs)
{
	RootDirectory = InArgs._RootDirectory;
	OnFileSelectedDelegate = InArgs._OnFileSelected;

	// Start hidden.
	SetVisibility(EVisibility::Collapsed);

	ChildSlot
	[
		SNew(SBox)
		.WidthOverride(500.0f)
		.MaxDesiredHeight(400.0f)
		[
			SNew(SVerticalBox)

			// Search input.
			+ SVerticalBox::Slot()
			.AutoHeight()
			.Padding(4.0f)
			[
				SAssignNew(SearchBox, SEditableTextBox)
				.HintText(LOCTEXT("SearchHint", "Type to search files..."))
				.OnTextChanged(this, &SMCAQuickOpen::OnSearchTextChanged)
			]

			// Results list.
			+ SVerticalBox::Slot()
			.FillHeight(1.0f)
			[
				SAssignNew(ResultsList, SListView<TSharedPtr<FMCAQuickOpenItem>>)
				.ListItemsSource(&FilteredFiles)
				.OnGenerateRow(this, &SMCAQuickOpen::OnGenerateRow)
				.OnSelectionChanged(this, &SMCAQuickOpen::OnItemSelected)
			]
		]
	];
}


void SMCAQuickOpen::Show()
{
	// Build the file index if needed.
	if (AllFiles.Num() == 0)
	{
		BuildFileIndex();
	}

	// Show with an empty query (shows all files).
	FilteredFiles = AllFiles;
	if (ResultsList.IsValid())
	{
		ResultsList->RequestListRefresh();
	}

	SetVisibility(EVisibility::Visible);

	// Focus and clear the search box.
	if (SearchBox.IsValid())
	{
		SearchBox->SetText(FText::GetEmpty());
		FSlateApplication::Get().SetKeyboardFocus(SearchBox);
	}
}


void SMCAQuickOpen::Hide()
{
	SetVisibility(EVisibility::Collapsed);
}


void SMCAQuickOpen::BuildFileIndex()
{
	AllFiles.Empty();

	if (RootDirectory.IsEmpty())
	{
		return;
	}

	// Recursively find all files.
	TArray<FString> FoundFiles;
	IFileManager::Get().FindFilesRecursive(FoundFiles, *RootDirectory, TEXT("*.*"), true, false);

	for (const FString& FilePath : FoundFiles)
	{
		// Skip hidden files and directories.
		if (FilePath.Contains(TEXT("/.")) || FilePath.Contains(TEXT("\\.")))
		{
			continue;
		}
		if (FilePath.Contains(TEXT("__pycache__")))
		{
			continue;
		}

		TSharedPtr<FMCAQuickOpenItem> Item = MakeShared<FMCAQuickOpenItem>();
		Item->DisplayName = FPaths::GetCleanFilename(FilePath);
		Item->FullPath = FilePath;

		// Compute relative path for display.
		Item->RelativePath = FilePath;
		FPaths::MakePathRelativeTo(Item->RelativePath, *RootDirectory);

		Item->MatchScore = 0;

		AllFiles.Add(Item);
	}
}


void SMCAQuickOpen::OnSearchTextChanged(const FText& NewText)
{
	FString Query = NewText.ToString();

	if (Query.IsEmpty())
	{
		// Show all files when query is empty.
		FilteredFiles = AllFiles;
	}
	else
	{
		// Filter and score files by fuzzy match.
		FilteredFiles.Empty();

		for (const TSharedPtr<FMCAQuickOpenItem>& Item : AllFiles)
		{
			int32 Score = FuzzyMatchScore(Item->DisplayName, Query);
			if (Score > 0)
			{
				Item->MatchScore = Score;
				FilteredFiles.Add(Item);
			}
		}

		// Sort by score (highest first).
		FilteredFiles.Sort([](const TSharedPtr<FMCAQuickOpenItem>& A, const TSharedPtr<FMCAQuickOpenItem>& B)
		{
			return A->MatchScore > B->MatchScore;
		});
	}

	if (ResultsList.IsValid())
	{
		ResultsList->RequestListRefresh();
	}
}


int32 SMCAQuickOpen::FuzzyMatchScore(const FString& Filename, const FString& Query) const
{
	// Simple fuzzy matching: all query characters must appear in order.
	FString LowerFilename = Filename.ToLower();
	FString LowerQuery = Query.ToLower();

	int32 Score = 0;
	int32 FileIndex = 0;

	for (int32 QueryIndex = 0; QueryIndex < LowerQuery.Len(); ++QueryIndex)
	{
		TCHAR QueryChar = LowerQuery[QueryIndex];
		bool bFound = false;

		while (FileIndex < LowerFilename.Len())
		{
			if (LowerFilename[FileIndex] == QueryChar)
			{
				// Bonus for consecutive matches.
				Score += 10;

				// Bonus for matching at word boundaries (after _, ., uppercase).
				if (FileIndex == 0 || Filename[FileIndex - 1] == '_' || Filename[FileIndex - 1] == '.')
				{
					Score += 5;
				}

				FileIndex++;
				bFound = true;
				break;
			}
			FileIndex++;
		}

		if (!bFound)
		{
			return 0;  // Query character not found — no match.
		}
	}

	// Bonus for shorter filenames (more specific matches).
	Score += FMath::Max(0, 50 - LowerFilename.Len());

	return Score;
}


TSharedRef<ITableRow> SMCAQuickOpen::OnGenerateRow(TSharedPtr<FMCAQuickOpenItem> Item, const TSharedRef<STableViewBase>& OwnerTable)
{
	return SNew(STableRow<TSharedPtr<FMCAQuickOpenItem>>, OwnerTable)
		[
			SNew(SVerticalBox)

			// Filename.
			+ SVerticalBox::Slot()
			.AutoHeight()
			.Padding(4.0f, 2.0f)
			[
				SNew(STextBlock)
				.Text(FText::FromString(Item->DisplayName))
				.ColorAndOpacity(FMCAEditorStyle::TextColor)
			]

			// Relative path (smaller, dimmer).
			+ SVerticalBox::Slot()
			.AutoHeight()
			.Padding(4.0f, 0.0f, 4.0f, 2.0f)
			[
				SNew(STextBlock)
				.Text(FText::FromString(Item->RelativePath))
				.ColorAndOpacity(FMCAEditorStyle::LineNumberColor)
			]
		];
}


void SMCAQuickOpen::OnItemSelected(TSharedPtr<FMCAQuickOpenItem> Item, ESelectInfo::Type SelectInfo)
{
	if (Item.IsValid() && SelectInfo == ESelectInfo::OnMouseClick)
	{
		OnFileSelectedDelegate.ExecuteIfBound(Item->FullPath);
		Hide();
	}
}


FReply SMCAQuickOpen::OnKeyDown(const FGeometry& MyGeometry, const FKeyEvent& InKeyEvent)
{
	// Escape dismisses the dialog.
	if (InKeyEvent.GetKey() == EKeys::Escape)
	{
		Hide();
		return FReply::Handled();
	}

	// Enter opens the selected file.
	if (InKeyEvent.GetKey() == EKeys::Enter)
	{
		TArray<TSharedPtr<FMCAQuickOpenItem>> SelectedItems;
		ResultsList->GetSelectedItems(SelectedItems);

		if (SelectedItems.Num() > 0)
		{
			OnFileSelectedDelegate.ExecuteIfBound(SelectedItems[0]->FullPath);
			Hide();
			return FReply::Handled();
		}
		else if (FilteredFiles.Num() > 0)
		{
			// Select the first result if nothing is explicitly selected.
			OnFileSelectedDelegate.ExecuteIfBound(FilteredFiles[0]->FullPath);
			Hide();
			return FReply::Handled();
		}
	}

	return SCompoundWidget::OnKeyDown(MyGeometry, InKeyEvent);
}


#undef LOCTEXT_NAMESPACE
