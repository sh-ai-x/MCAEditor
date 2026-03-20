// MCA Quick Open — Ctrl+P file picker dialog.
//
// Modal popup with fuzzy file search across the project directory.
// Mirrors quick_open.py in the Maya version.

#pragma once

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/DeclarativeSyntaxSupport.h"
#include "Widgets/Views/SListView.h"

/** Represents a file result in the quick-open list. */
struct FMCAQuickOpenItem
{
	/** Display name (filename). */
	FString DisplayName;

	/** Full file path. */
	FString FullPath;

	/** Relative path from the project root (for display). */
	FString RelativePath;

	/** Fuzzy match score (higher = better match). */
	int32 MatchScore;
};

/** Delegate fired when a file is selected from the quick-open dialog. */
DECLARE_DELEGATE_OneParam(FOnQuickOpenFileSelected, const FString& /* FilePath */);

/**
 * Quick-open file picker popup.
 *
 * Features:
 *   - Fuzzy file search across the project directory
 *   - Search box with live filtering
 *   - File list with relative paths
 *   - Up/down arrow navigation
 *   - Enter to open selected file
 *   - Escape to dismiss
 *   - Ctrl+G variant for Go To Line
 */
class SMCAQuickOpen : public SCompoundWidget
{
public:

	SLATE_BEGIN_ARGS(SMCAQuickOpen) {}
		/** Root directory to search for files. */
		SLATE_ARGUMENT(FString, RootDirectory)

		/** Called when a file is selected. */
		SLATE_EVENT(FOnQuickOpenFileSelected, OnFileSelected)
	SLATE_END_ARGS()

	/** Construct the widget. */
	void Construct(const FArguments& InArgs);

	/** Show the quick-open popup and focus the search box. */
	void Show();

	/** Hide the popup. */
	void Hide();

private:

	// --- Search Logic ------------------------------------------------------

	/** Update the file list based on the current search query. */
	void OnSearchTextChanged(const FText& NewText);

	/** Calculate a fuzzy match score for a filename against a query. */
	int32 FuzzyMatchScore(const FString& Filename, const FString& Query) const;

	/** Scan the root directory for all files (cached). */
	void BuildFileIndex();

	// --- List View Callbacks -----------------------------------------------

	/** Generate a row widget for a file result. */
	TSharedRef<ITableRow> OnGenerateRow(TSharedPtr<FMCAQuickOpenItem> Item, const TSharedRef<STableViewBase>& OwnerTable);

	/** Handle file selection (double-click or Enter). */
	void OnItemSelected(TSharedPtr<FMCAQuickOpenItem> Item, ESelectInfo::Type SelectInfo);

	// --- Key Handling ------------------------------------------------------

	/** Handle key input (arrow keys, Enter, Escape). */
	virtual FReply OnKeyDown(const FGeometry& MyGeometry, const FKeyEvent& InKeyEvent) override;

	// --- Child Widgets -----------------------------------------------------

	/** Search input field. */
	TSharedPtr<class SEditableTextBox> SearchBox;

	/** File results list view. */
	TSharedPtr<SListView<TSharedPtr<FMCAQuickOpenItem>>> ResultsList;

	// --- State -------------------------------------------------------------

	/** Root directory for file search. */
	FString RootDirectory;

	/** All files in the project (cached index). */
	TArray<TSharedPtr<FMCAQuickOpenItem>> AllFiles;

	/** Filtered results based on current query. */
	TArray<TSharedPtr<FMCAQuickOpenItem>> FilteredFiles;

	// --- Delegates ---------------------------------------------------------

	FOnQuickOpenFileSelected OnFileSelectedDelegate;
};
