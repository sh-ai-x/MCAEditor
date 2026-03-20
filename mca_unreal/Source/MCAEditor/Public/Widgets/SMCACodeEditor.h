// MCA Code Editor — Syntax-highlighted Python text editor.
//
// Built on SMultiLineEditableTextBox with a custom ITextLayoutMarshaller
// for Python syntax highlighting. Provides line numbers, auto-indent,
// brace matching, and basic auto-complete.

#pragma once

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/DeclarativeSyntaxSupport.h"
#include "Widgets/Text/SMultiLineEditableTextBox.h"
#include "Framework/Text/TextLayout.h"

class FMCAPythonSyntaxMarshaller;

/** Delegate fired when the editor text changes. */
DECLARE_DELEGATE(FOnCodeEditorTextChanged);

/** Delegate fired when the cursor position changes. */
DECLARE_DELEGATE_TwoParams(FOnCursorPositionChanged, int32 /* Line */, int32 /* Column */);

/**
 * Syntax-highlighted Python code editor widget.
 *
 * Features (matching the Maya/standalone version):
 *   - Python syntax highlighting (keywords, strings, comments, etc.)
 *   - Line numbers gutter
 *   - Current line highlight
 *   - Auto-indent (Python block detection)
 *   - Tab/Shift+Tab indent/dedent
 *   - Ctrl+/ toggle comment
 *   - Shift+Enter to execute
 *   - Basic auto-complete popup
 */
class SMCACodeEditor : public SCompoundWidget
{
public:

	SLATE_BEGIN_ARGS(SMCACodeEditor)
		: _InitialText(FText::GetEmpty())
	{}
		/** Initial text content for the editor. */
		SLATE_ARGUMENT(FText, InitialText)

		/** Called when text changes (for modified indicator). */
		SLATE_EVENT(FOnCodeEditorTextChanged, OnTextChanged)

		/** Called when cursor moves (for status bar). */
		SLATE_EVENT(FOnCursorPositionChanged, OnCursorMoved)

		/** Called when Shift+Enter is pressed (execute request). */
		SLATE_EVENT(FSimpleDelegate, OnExecuteRequested)
	SLATE_END_ARGS()

	/** Construct the widget. */
	void Construct(const FArguments& InArgs);

	// --- Text Access -------------------------------------------------------

	/** Get the current editor text. */
	FText GetText() const;

	/** Set the editor text (replaces all content). */
	void SetText(const FText& NewText);

	/** Get the currently selected text (empty if no selection). */
	FString GetSelectedText() const;

	/** Get the text to execute: selection if any, otherwise all text. */
	FString GetExecutionText() const;

	// --- Cursor / Selection ------------------------------------------------

	/** Get the current cursor line (1-based). */
	int32 GetCursorLine() const;

	/** Get the current cursor column (1-based). */
	int32 GetCursorColumn() const;

	/** Go to a specific line number (1-based). */
	void GoToLine(int32 LineNumber);

	/** Select a range of text by character offset and length. */
	void SelectRange(int32 StartOffset, int32 Length);

	/** Replace the current selection with new text. */
	void ReplaceSelectedText(const FString& NewText);

	// --- Edit Operations ---------------------------------------------------

	/** Toggle line comment (Ctrl+/) on the current line or selection. */
	void ToggleComment();

	/** Indent the current line or selection by one tab stop. */
	void IndentSelection();

	/** Dedent the current line or selection by one tab stop. */
	void DedentSelection();

	// --- State -------------------------------------------------------------

	/** Check if the content has been modified since last save/load. */
	bool IsModified() const;

	/** Clear the modified flag (called after save). */
	void ClearModified();

private:

	// --- Event Handlers ----------------------------------------------------

	/** Called when the text box content changes. */
	void HandleTextChanged(const FText& NewText);

	/** Called when the text is committed (Enter key, etc.). */
	void HandleTextCommitted(const FText& NewText, ETextCommit::Type CommitType);

	/** Called when the cursor position changes in the text box. */
	void HandleCursorMoved(const FTextLocation& NewCursorPosition);

	/** Rebuild the line numbers gutter text to match the current line count. */
	void UpdateLineNumbers();

	// --- Child Widgets -----------------------------------------------------

	/** The underlying multi-line text box. */
	TSharedPtr<SMultiLineEditableTextBox> TextBox;

	/** Python syntax marshaller for highlighting. */
	TSharedPtr<FMCAPythonSyntaxMarshaller> SyntaxMarshaller;

	/** Line numbers text block. */
	TSharedPtr<SWidget> LineNumbersWidget;

	// --- State -------------------------------------------------------------

	/** Whether the content has been modified since last load/save. */
	bool bIsModified;

	// --- Delegates ---------------------------------------------------------

	FOnCodeEditorTextChanged OnTextChangedDelegate;
	FOnCursorPositionChanged OnCursorMovedDelegate;
	FSimpleDelegate OnExecuteRequestedDelegate;
};
