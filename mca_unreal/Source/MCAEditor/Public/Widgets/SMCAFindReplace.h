// MCA Find/Replace Bar — Search and replace overlay.
//
// Overlay bar activated by Ctrl+F / Ctrl+H with regex, case-sensitive,
// and whole-word toggles. Mirrors find_replace_bar.py.

#pragma once

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/DeclarativeSyntaxSupport.h"

class SMCACodeEditor;

/** Delegate fired when a search match needs to be highlighted in the editor. */
DECLARE_DELEGATE_TwoParams(FOnFindMatch, int32 /* StartOffset */, int32 /* Length */);

/**
 * Find and replace bar overlay widget.
 *
 * Features:
 *   - Search box with match count display
 *   - Regex toggle, case-sensitive toggle, whole-word toggle
 *   - Find next / Find previous navigation
 *   - Replace / Replace All
 *   - Ctrl+F to show find, Ctrl+H to show find+replace
 *   - Escape to dismiss
 */
class SMCAFindReplace : public SCompoundWidget
{
public:

	SLATE_BEGIN_ARGS(SMCAFindReplace) {}
		/** The code editor to search within. */
		SLATE_ARGUMENT(TSharedPtr<SMCACodeEditor>, CodeEditor)
	SLATE_END_ARGS()

	/** Construct the widget. */
	void Construct(const FArguments& InArgs);

	/** Show the find bar (Ctrl+F mode). */
	void ShowFind();

	/** Show the find+replace bar (Ctrl+H mode). */
	void ShowFindReplace();

	/** Hide the bar. */
	void Hide();

	/** Is the bar currently visible? */
	bool IsBarVisible() const;

private:

	// --- Search Actions ----------------------------------------------------

	/** Execute a search with the current query and options. */
	void DoSearch();

	/** Navigate to the next match. */
	FReply OnFindNext();

	/** Navigate to the previous match. */
	FReply OnFindPrev();

	/** Replace the current match. */
	FReply OnReplace();

	/** Replace all matches. */
	FReply OnReplaceAll();

	/** Close button callback. */
	FReply OnCloseClicked();

	// --- State -------------------------------------------------------------

	/** Whether the replace row is visible. */
	bool bShowReplace;

	/** Whether regex mode is active. */
	bool bUseRegex;

	/** Whether case-sensitive mode is active. */
	bool bCaseSensitive;

	/** Whether whole-word mode is active. */
	bool bWholeWord;

	/** Current match index (for "N of M" display). */
	int32 CurrentMatchIndex;

	/** Total match count. */
	int32 TotalMatches;

	/** Character offsets of all found matches. */
	TArray<int32> MatchOffsets;

	/** Length of the search query (for selection). */
	int32 MatchLength;

	// --- Child Widgets -----------------------------------------------------

	/** Search input field. */
	TSharedPtr<class SEditableTextBox> SearchBox;

	/** Replace input field. */
	TSharedPtr<class SEditableTextBox> ReplaceBox;

	/** Match count text ("N of M"). */
	TSharedPtr<STextBlock> MatchCountText;

	/** Replace row (hidden in find-only mode). */
	TSharedPtr<SWidget> ReplaceRow;

	/** Reference to the code editor for performing searches. */
	TSharedPtr<SMCACodeEditor> CodeEditorRef;
};
