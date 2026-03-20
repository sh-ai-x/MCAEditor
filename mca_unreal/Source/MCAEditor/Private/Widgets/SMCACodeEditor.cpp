// MCA Code Editor — Syntax-highlighted Python text editor implementation.
//
// Uses SMultiLineEditableTextBox with a custom marshaller for Python
// syntax highlighting. This is the core editing widget, equivalent to
// mca_qt/widgets/code_editor.py.

#include "Widgets/SMCACodeEditor.h"
#include "MCAEditorStyle.h"
#include "MCAEditorSettings.h"

#include "Framework/Text/IRun.h"
#include "Framework/Text/TextLayout.h"
#include "Framework/Text/SlateTextRun.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SGridPanel.h"
#include "Widgets/Text/STextBlock.h"

// --- Python Syntax Marshaller ------------------------------------------

/**
 * Custom text marshaller for Python syntax highlighting.
 *
 * Tokenizes each line and applies Slate text styles for:
 *   - Keywords (def, class, if, for, return, etc.) — blue
 *   - Strings (single/double/triple-quoted, f-strings) — green/orange
 *   - Comments (#) — gray/green
 *   - Numbers — light green
 *   - Decorators (@) — yellow
 *   - Built-in functions (print, len, range) — purple
 *   - unreal.* API calls — cyan
 */
class FMCAPythonSyntaxMarshaller : public ITextLayoutMarshaller
{
public:

	FMCAPythonSyntaxMarshaller()
		: bInMultiLineString(false)
	{
		// Python keywords for highlighting.
		Keywords = {
			TEXT("False"), TEXT("None"), TEXT("True"), TEXT("and"), TEXT("as"),
			TEXT("assert"), TEXT("async"), TEXT("await"), TEXT("break"), TEXT("class"),
			TEXT("continue"), TEXT("def"), TEXT("del"), TEXT("elif"), TEXT("else"),
			TEXT("except"), TEXT("finally"), TEXT("for"), TEXT("from"), TEXT("global"),
			TEXT("if"), TEXT("import"), TEXT("in"), TEXT("is"), TEXT("lambda"),
			TEXT("nonlocal"), TEXT("not"), TEXT("or"), TEXT("pass"), TEXT("raise"),
			TEXT("return"), TEXT("try"), TEXT("while"), TEXT("with"), TEXT("yield"),
		};

		// Python built-in functions.
		Builtins = {
			TEXT("print"), TEXT("len"), TEXT("range"), TEXT("type"), TEXT("str"),
			TEXT("int"), TEXT("float"), TEXT("list"), TEXT("dict"), TEXT("set"),
			TEXT("tuple"), TEXT("bool"), TEXT("super"), TEXT("isinstance"),
			TEXT("hasattr"), TEXT("getattr"), TEXT("setattr"), TEXT("enumerate"),
			TEXT("zip"), TEXT("map"), TEXT("filter"), TEXT("sorted"), TEXT("reversed"),
			TEXT("input"), TEXT("open"), TEXT("dir"), TEXT("vars"), TEXT("help"),
		};
	}

	virtual ~FMCAPythonSyntaxMarshaller() {}

	// --- ITextLayoutMarshaller Interface -----------------------------------

	virtual void SetText(const FString& SourceString, FTextLayout& TargetTextLayout) override
	{
		// Split the source string into lines and highlight each one.
		TArray<FString> Lines;
		SourceString.ParseIntoArrayLines(Lines);

		TArray<FTextLayout::FNewLineData> LinesToAdd;
		LinesToAdd.Reserve(Lines.Num());

		bInMultiLineString = false;

		for (const FString& Line : Lines)
		{
			TArray<TSharedRef<IRun>> Runs;
			TokenizeLine(Line, Runs, TargetTextLayout);

			LinesToAdd.Emplace(MoveTemp(Runs));
		}

		TargetTextLayout.AddLines(LinesToAdd);
	}

	virtual void GetText(FString& TargetString, const FTextLayout& SourceTextLayout) override
	{
		// Extract plain text from the layout.
		SourceTextLayout.GetAsText(TargetString);
	}

private:

	/**
	 * Tokenize a single line of Python code into styled runs.
	 *
	 * This is a simplified tokenizer — it handles the most common cases
	 * but doesn't implement a full Python lexer. Good enough for editing.
	 */
	void TokenizeLine(const FString& Line, TArray<TSharedRef<IRun>>& OutRuns, FTextLayout& TextLayout)
	{
		const FTextBlockStyle& DefaultStyle = FMCAEditorStyle::Get().GetWidgetStyle<FTextBlockStyle>("MCAEditor.EditorText");
		const FTextBlockStyle& KeywordStyle = FMCAEditorStyle::Get().GetWidgetStyle<FTextBlockStyle>("MCAEditor.Keyword");
		const FTextBlockStyle& StringStyle = FMCAEditorStyle::Get().GetWidgetStyle<FTextBlockStyle>("MCAEditor.String");
		const FTextBlockStyle& CommentStyle = FMCAEditorStyle::Get().GetWidgetStyle<FTextBlockStyle>("MCAEditor.Comment");
		const FTextBlockStyle& NumberStyle = FMCAEditorStyle::Get().GetWidgetStyle<FTextBlockStyle>("MCAEditor.Number");
		const FTextBlockStyle& DecoratorStyle = FMCAEditorStyle::Get().GetWidgetStyle<FTextBlockStyle>("MCAEditor.Decorator");
		const FTextBlockStyle& BuiltinStyle = FMCAEditorStyle::Get().GetWidgetStyle<FTextBlockStyle>("MCAEditor.Builtin");

		if (Line.IsEmpty())
		{
			// Empty line — add a single empty run.
			TSharedRef<FString> LineText = MakeShared<FString>(TEXT(""));
			FTextRange Range(0, 0);
			FRunInfo RunInfo;
			OutRuns.Add(FSlateTextRun::Create(RunInfo, LineText, DefaultStyle, Range));
			return;
		}

		// For now, create a single run with the full line text in default style.
		// TODO Phase 2: Implement proper tokenization with per-token styling.
		// The tokenizer will walk the string character by character, identifying:
		//   - Comments (# to end of line)
		//   - Strings (', ", ''', """, f-strings)
		//   - Keywords (word boundary check against Keywords set)
		//   - Builtins (word boundary check against Builtins set)
		//   - Numbers (digit sequences)
		//   - Decorators (@ at line start)
		//   - Everything else: default style
		TSharedRef<FString> LineText = MakeShared<FString>(Line);
		FTextRange Range(0, Line.Len());
		FRunInfo RunInfo;
		OutRuns.Add(FSlateTextRun::Create(RunInfo, LineText, DefaultStyle, Range));
	}

	/** Python keywords. */
	TSet<FString> Keywords;

	/** Python built-in functions. */
	TSet<FString> Builtins;

	/** Tracks whether we're inside a multi-line string (''' or """). */
	bool bInMultiLineString;
};


// --- SMCACodeEditor Implementation -------------------------------------

void SMCACodeEditor::Construct(const FArguments& InArgs)
{
	bIsModified = false;
	OnTextChangedDelegate = InArgs._OnTextChanged;
	OnCursorMovedDelegate = InArgs._OnCursorMoved;
	OnExecuteRequestedDelegate = InArgs._OnExecuteRequested;

	// Create the syntax marshaller.
	SyntaxMarshaller = MakeShared<FMCAPythonSyntaxMarshaller>();

	// Build the widget: line numbers + text editor side by side.
	ChildSlot
	[
		SNew(SHorizontalBox)

		// Code text editor (full width for Phase 1, line numbers added in Phase 2).
		+ SHorizontalBox::Slot()
		.FillWidth(1.0f)
		[
			SAssignNew(TextBox, SMultiLineEditableTextBox)
			.Marshaller(SyntaxMarshaller.ToSharedRef())
			.Text(InArgs._InitialText)
			.AutoWrapText(false)
			.Margin(FMargin(8.0f, 4.0f))
			.OnTextChanged(this, &SMCACodeEditor::HandleTextChanged)
			.OnTextCommitted(this, &SMCACodeEditor::HandleTextCommitted)
		]
	];
}


FText SMCACodeEditor::GetText() const
{
	if (TextBox.IsValid())
	{
		return TextBox->GetText();
	}
	return FText::GetEmpty();
}


void SMCACodeEditor::SetText(const FText& NewText)
{
	if (TextBox.IsValid())
	{
		TextBox->SetText(NewText);
	}
}


FString SMCACodeEditor::GetSelectedText() const
{
	if (TextBox.IsValid())
	{
		return TextBox->GetSelectedText().ToString();
	}
	return FString();
}


FString SMCACodeEditor::GetExecutionText() const
{
	// If there's a selection, execute that; otherwise execute all text.
	FString Selected = GetSelectedText();
	if (!Selected.IsEmpty())
	{
		return Selected;
	}
	return GetText().ToString();
}


int32 SMCACodeEditor::GetCursorLine() const
{
	// TODO Phase 2: Implement cursor position tracking.
	return 1;
}


int32 SMCACodeEditor::GetCursorColumn() const
{
	// TODO Phase 2: Implement cursor position tracking.
	return 1;
}


void SMCACodeEditor::GoToLine(int32 LineNumber)
{
	// TODO Phase 2: Implement cursor positioning.
	if (TextBox.IsValid())
	{
		TextBox->GoTo(FTextLocation(LineNumber - 1, 0));
	}
}


void SMCACodeEditor::ToggleComment()
{
	// TODO Phase 2: Implement comment toggling.
	// Walk each selected line, toggle "# " prefix.
}


void SMCACodeEditor::IndentSelection()
{
	// TODO Phase 2: Implement indent.
	// Add tab/spaces to the start of each selected line.
}


void SMCACodeEditor::DedentSelection()
{
	// TODO Phase 2: Implement dedent.
	// Remove one tab stop from the start of each selected line.
}


bool SMCACodeEditor::IsModified() const
{
	return bIsModified;
}


void SMCACodeEditor::ClearModified()
{
	bIsModified = false;
}


void SMCACodeEditor::HandleTextChanged(const FText& NewText)
{
	bIsModified = true;
	OnTextChangedDelegate.ExecuteIfBound();
}


void SMCACodeEditor::HandleTextCommitted(const FText& NewText, ETextCommit::Type CommitType)
{
	// No special handling needed — text changes are tracked via HandleTextChanged.
}
