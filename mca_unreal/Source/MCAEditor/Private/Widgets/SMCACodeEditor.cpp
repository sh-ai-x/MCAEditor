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
		, MultiLineQuoteChar(TEXT('"'))
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

	// --- Token Types -------------------------------------------------------

	enum class ETokenType : uint8
	{
		Default,
		Keyword,
		Builtin,
		String,
		Comment,
		Number,
		Decorator,
	};

	/** Small struct representing one token span within a line. */
	struct FToken
	{
		int32 Start;
		int32 End;
		ETokenType Type;
	};

	// --- Character Helpers -------------------------------------------------

	/** Check if a character is a Python identifier start (letter or underscore). */
	static bool IsIdentStart(TCHAR C)
	{
		return FChar::IsAlpha(C) || C == TEXT('_');
	}

	/** Check if a character is a Python identifier continuation. */
	static bool IsIdentChar(TCHAR C)
	{
		return FChar::IsAlpha(C) || FChar::IsDigit(C) || C == TEXT('_');
	}

	/** Check if a position is at a word boundary (start of line or after non-ident). */
	bool IsWordBoundary(const FString& Line, int32 Pos) const
	{
		if (Pos == 0) return true;
		return !IsIdentChar(Line[Pos - 1]);
	}

	/** Check if end of word (end of line or next char is non-ident). */
	bool IsWordEnd(const FString& Line, int32 Pos) const
	{
		if (Pos >= Line.Len()) return true;
		return !IsIdentChar(Line[Pos]);
	}

	/**
	 * Tokenize a single line of Python code into styled runs.
	 *
	 * Walks the string character by character, building a list of tokens
	 * for comments, strings, keywords, builtins, numbers, decorators,
	 * and default text. Each token becomes a separate FSlateTextRun with
	 * the appropriate style applied.
	 */
	void TokenizeLine(const FString& Line, TArray<TSharedRef<IRun>>& OutRuns, FTextLayout& TextLayout)
	{
		// Cache style references — avoids repeated lookups per line.
		const FTextBlockStyle& DefaultStyle = FMCAEditorStyle::Get().GetWidgetStyle<FTextBlockStyle>("MCAEditor.EditorText");
		const FTextBlockStyle& KeywordStyle = FMCAEditorStyle::Get().GetWidgetStyle<FTextBlockStyle>("MCAEditor.Keyword");
		const FTextBlockStyle& StringStyle = FMCAEditorStyle::Get().GetWidgetStyle<FTextBlockStyle>("MCAEditor.String");
		const FTextBlockStyle& CommentStyle = FMCAEditorStyle::Get().GetWidgetStyle<FTextBlockStyle>("MCAEditor.Comment");
		const FTextBlockStyle& NumberStyle = FMCAEditorStyle::Get().GetWidgetStyle<FTextBlockStyle>("MCAEditor.Number");
		const FTextBlockStyle& DecoratorStyle = FMCAEditorStyle::Get().GetWidgetStyle<FTextBlockStyle>("MCAEditor.Decorator");
		const FTextBlockStyle& BuiltinStyle = FMCAEditorStyle::Get().GetWidgetStyle<FTextBlockStyle>("MCAEditor.Builtin");

		if (Line.IsEmpty())
		{
			// Empty line — add a single empty run so the layout has a line entry.
			TSharedRef<FString> LineText = MakeShared<FString>(TEXT(""));
			FTextRange Range(0, 0);
			FRunInfo RunInfo;
			OutRuns.Add(FSlateTextRun::Create(RunInfo, LineText, DefaultStyle, Range));
			return;
		}

		// Build token list by scanning the line.
		TArray<FToken> Tokens;
		TokenizeLineIntoTokens(Line, Tokens);

		// Convert tokens into styled Slate text runs.
		// All runs share a single FString so that the text layout can
		// reference character positions within the original line.
		TSharedRef<FString> LineText = MakeShared<FString>(Line);

		for (const FToken& Token : Tokens)
		{
			FRunInfo RunInfo;
			FTextRange Range(Token.Start, Token.End);

			const FTextBlockStyle* Style = &DefaultStyle;
			switch (Token.Type)
			{
			case ETokenType::Keyword:   Style = &KeywordStyle;   break;
			case ETokenType::Builtin:   Style = &BuiltinStyle;   break;
			case ETokenType::String:    Style = &StringStyle;     break;
			case ETokenType::Comment:   Style = &CommentStyle;    break;
			case ETokenType::Number:    Style = &NumberStyle;     break;
			case ETokenType::Decorator: Style = &DecoratorStyle;  break;
			default: break;
			}

			OutRuns.Add(FSlateTextRun::Create(RunInfo, LineText, *Style, Range));
		}
	}

	/**
	 * Core tokenization logic — scans a line and produces a flat token list.
	 *
	 * Handles multi-line string state (triple quotes spanning lines),
	 * f-string prefixes, decorator lines, comments, numbers, identifiers
	 * (keywords vs builtins vs default), and everything else as default.
	 */
	void TokenizeLineIntoTokens(const FString& Line, TArray<FToken>& OutTokens)
	{
		const int32 Len = Line.Len();
		int32 Pos = 0;

		// --- Handle continuation of a multi-line string from a previous line.
		if (bInMultiLineString)
		{
			int32 ClosePos = FindTripleQuoteEnd(Line, 0);
			if (ClosePos == INDEX_NONE)
			{
				// Entire line is still inside the multi-line string.
				OutTokens.Add({ 0, Len, ETokenType::String });
				return;
			}
			else
			{
				// Multi-line string ends on this line.
				OutTokens.Add({ 0, ClosePos, ETokenType::String });
				bInMultiLineString = false;
				Pos = ClosePos;
			}
		}

		// --- Walk the rest of the line character by character.
		while (Pos < Len)
		{
			TCHAR C = Line[Pos];

			// --- Comment: # to end of line.
			if (C == TEXT('#'))
			{
				OutTokens.Add({ Pos, Len, ETokenType::Comment });
				return; // Nothing after a comment on this line.
			}

			// --- Decorator: @ at start of non-whitespace content.
			if (C == TEXT('@') && IsDecoratorPosition(Line, Pos))
			{
				int32 Start = Pos;
				Pos++; // skip @
				// Consume the decorator name (identifier chars and dots).
				while (Pos < Len && (IsIdentChar(Line[Pos]) || Line[Pos] == TEXT('.')))
				{
					Pos++;
				}
				OutTokens.Add({ Start, Pos, ETokenType::Decorator });
				continue;
			}

			// --- Strings: single/double/triple, with optional f/r/b/u prefix.
			if (IsStringStart(Line, Pos))
			{
				int32 Start = Pos;
				ConsumeString(Line, Pos);
				OutTokens.Add({ Start, Pos, ETokenType::String });
				continue;
			}

			// --- Numbers: digit sequences, including 0x, 0b, 0o, floats.
			if (FChar::IsDigit(C) || (C == TEXT('.') && Pos + 1 < Len && FChar::IsDigit(Line[Pos + 1])))
			{
				// Only treat as a number if at a word boundary (avoids coloring
				// digits inside identifiers like "var2").
				if (IsWordBoundary(Line, Pos))
				{
					int32 Start = Pos;
					ConsumeNumber(Line, Pos);
					OutTokens.Add({ Start, Pos, ETokenType::Number });
					continue;
				}
			}

			// --- Identifiers: keywords, builtins, or default.
			if (IsIdentStart(C))
			{
				int32 Start = Pos;
				while (Pos < Len && IsIdentChar(Line[Pos]))
				{
					Pos++;
				}

				FString Word = Line.Mid(Start, Pos - Start);

				// Check if followed by '(' for builtin detection.
				bool bFollowedByParen = (Pos < Len && Line[Pos] == TEXT('('));

				if (Keywords.Contains(Word))
				{
					OutTokens.Add({ Start, Pos, ETokenType::Keyword });
				}
				else if (Builtins.Contains(Word) && bFollowedByParen)
				{
					OutTokens.Add({ Start, Pos, ETokenType::Builtin });
				}
				else
				{
					OutTokens.Add({ Start, Pos, ETokenType::Default });
				}
				continue;
			}

			// --- Default: any other character (operators, whitespace, etc.).
			{
				int32 Start = Pos;
				// Batch consecutive default characters into one token.
				while (Pos < Len)
				{
					TCHAR Ch = Line[Pos];
					if (Ch == TEXT('#') || Ch == TEXT('@') || IsStringStart(Line, Pos)
						|| IsIdentStart(Ch)
						|| (FChar::IsDigit(Ch) && IsWordBoundary(Line, Pos))
						|| (Ch == TEXT('.') && Pos + 1 < Len && FChar::IsDigit(Line[Pos + 1])))
					{
						break;
					}
					Pos++;
				}
				if (Pos > Start)
				{
					OutTokens.Add({ Start, Pos, ETokenType::Default });
				}
			}
		}
	}

	// --- String Parsing Helpers --------------------------------------------

	/**
	 * Check if position is the start of a string literal.
	 * Handles optional f/r/b/u/rb/br prefixes before quote characters.
	 */
	bool IsStringStart(const FString& Line, int32 Pos) const
	{
		int32 Len = Line.Len();
		int32 P = Pos;

		// Skip optional string prefix characters (f, r, b, u, and combinations).
		while (P < Len)
		{
			TCHAR C = FChar::ToLower(Line[P]);
			if (C == TEXT('f') || C == TEXT('r') || C == TEXT('b') || C == TEXT('u'))
			{
				P++;
				// Maximum 2 prefix chars (e.g. rb, br, fr).
				if (P - Pos > 2) return false;
			}
			else
			{
				break;
			}
		}

		// Must be followed by a quote character.
		if (P < Len && (Line[P] == TEXT('\'') || Line[P] == TEXT('"')))
		{
			// Only valid if the prefix chars are at a word boundary.
			if (P > Pos && !IsWordBoundary(Line, Pos))
			{
				return false;
			}
			return true;
		}

		// No prefix — check if the current char is directly a quote.
		return (Line[Pos] == TEXT('\'') || Line[Pos] == TEXT('"'));
	}

	/**
	 * Consume a string literal starting at Pos, advancing Pos past the
	 * closing quote. Handles triple-quoted strings and sets
	 * bInMultiLineString if the string doesn't close on this line.
	 */
	void ConsumeString(const FString& Line, int32& Pos)
	{
		int32 Len = Line.Len();

		// Skip prefix characters (f, r, b, u).
		while (Pos < Len)
		{
			TCHAR C = FChar::ToLower(Line[Pos]);
			if (C == TEXT('f') || C == TEXT('r') || C == TEXT('b') || C == TEXT('u'))
			{
				Pos++;
			}
			else
			{
				break;
			}
		}

		if (Pos >= Len) return;

		TCHAR QuoteChar = Line[Pos];

		// Check for triple quote.
		if (Pos + 2 < Len && Line[Pos + 1] == QuoteChar && Line[Pos + 2] == QuoteChar)
		{
			// Triple-quoted string.
			Pos += 3; // skip opening """
			MultiLineQuoteChar = QuoteChar;

			// Search for closing triple quote on this line.
			while (Pos < Len)
			{
				if (Line[Pos] == TEXT('\\'))
				{
					Pos += 2; // skip escaped character
					continue;
				}
				if (Pos + 2 < Len && Line[Pos] == QuoteChar && Line[Pos + 1] == QuoteChar && Line[Pos + 2] == QuoteChar)
				{
					Pos += 3; // skip closing """
					return;
				}
				Pos++;
			}

			// Didn't find closing triple quote — string continues on next line.
			bInMultiLineString = true;
			return;
		}

		// Single-quoted string — consume until matching close or end of line.
		Pos++; // skip opening quote
		while (Pos < Len)
		{
			if (Line[Pos] == TEXT('\\'))
			{
				Pos += 2; // skip escaped character
				continue;
			}
			if (Line[Pos] == QuoteChar)
			{
				Pos++; // skip closing quote
				return;
			}
			Pos++;
		}
		// Unterminated single-line string — still consumed to end of line.
	}

	/**
	 * Find the end position of a triple-quoted string that started on a
	 * previous line. Returns the position AFTER the closing triple quote,
	 * or INDEX_NONE if not found on this line.
	 */
	int32 FindTripleQuoteEnd(const FString& Line, int32 StartPos) const
	{
		int32 Len = Line.Len();
		int32 Pos = StartPos;

		while (Pos < Len)
		{
			if (Line[Pos] == TEXT('\\'))
			{
				Pos += 2;
				continue;
			}
			if (Pos + 2 < Len && Line[Pos] == MultiLineQuoteChar
				&& Line[Pos + 1] == MultiLineQuoteChar
				&& Line[Pos + 2] == MultiLineQuoteChar)
			{
				return Pos + 3;
			}
			Pos++;
		}
		return INDEX_NONE;
	}

	// --- Number Parsing Helper ---------------------------------------------

	/**
	 * Consume a numeric literal: integers, floats, hex (0x), binary (0b),
	 * octal (0o), and optional underscores (Python 3 numeric separators).
	 */
	void ConsumeNumber(const FString& Line, int32& Pos) const
	{
		int32 Len = Line.Len();

		// Check for 0x, 0b, 0o prefixes.
		if (Pos + 1 < Len && Line[Pos] == TEXT('0'))
		{
			TCHAR Next = FChar::ToLower(Line[Pos + 1]);
			if (Next == TEXT('x') || Next == TEXT('b') || Next == TEXT('o'))
			{
				Pos += 2;
				while (Pos < Len && (FChar::IsAlnum(Line[Pos]) || Line[Pos] == TEXT('_')))
				{
					Pos++;
				}
				return;
			}
		}

		// Regular number: digits, dots, underscores, and optional exponent.
		while (Pos < Len && (FChar::IsDigit(Line[Pos]) || Line[Pos] == TEXT('.') || Line[Pos] == TEXT('_')))
		{
			Pos++;
		}

		// Exponent part (e.g. 1e10, 3.14E-2).
		if (Pos < Len && (Line[Pos] == TEXT('e') || Line[Pos] == TEXT('E')))
		{
			Pos++;
			if (Pos < Len && (Line[Pos] == TEXT('+') || Line[Pos] == TEXT('-')))
			{
				Pos++;
			}
			while (Pos < Len && (FChar::IsDigit(Line[Pos]) || Line[Pos] == TEXT('_')))
			{
				Pos++;
			}
		}

		// Optional j suffix for complex numbers.
		if (Pos < Len && (Line[Pos] == TEXT('j') || Line[Pos] == TEXT('J')))
		{
			Pos++;
		}
	}

	// --- Decorator Detection -----------------------------------------------

	/**
	 * Check if an '@' at the given position is a decorator (not matmul operator).
	 * A decorator '@' appears at the start of the line (ignoring whitespace).
	 */
	bool IsDecoratorPosition(const FString& Line, int32 Pos) const
	{
		// Everything before the @ should be whitespace for it to be a decorator.
		for (int32 i = 0; i < Pos; ++i)
		{
			if (!FChar::IsWhitespace(Line[i]))
			{
				return false;
			}
		}
		return true;
	}

	/** Python keywords. */
	TSet<FString> Keywords;

	/** Python built-in functions. */
	TSet<FString> Builtins;

	/** Tracks whether we're inside a multi-line string (''' or """). */
	bool bInMultiLineString;

	/** Which quote character the current multi-line string uses (' or "). */
	TCHAR MultiLineQuoteChar;
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

	// Build the widget: line numbers gutter + text editor side by side.
	ChildSlot
	[
		SNew(SHorizontalBox)

		// Line numbers gutter (fixed width, right-aligned).
		+ SHorizontalBox::Slot()
		.AutoWidth()
		[
			SNew(SBox)
			.WidthOverride(50.0f)
			.Padding(FMargin(4.0f, 4.0f, 8.0f, 4.0f))
			[
				SAssignNew(LineNumbersWidget, STextBlock)
				.Text(FText::FromString(TEXT("1")))
				.Justification(ETextJustify::Right)
				.ColorAndOpacity(FMCAEditorStyle::LineNumberColor)
				.Font(FCoreStyle::GetDefaultFontStyle("Mono", 12))
			]
		]

		// Code text editor.
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
			.OnCursorMoved(this, &SMCACodeEditor::HandleCursorMoved)
		]
	];

	// Build initial line numbers.
	UpdateLineNumbers();
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
		UpdateLineNumbers();
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
	if (TextBox.IsValid())
	{
		FTextLocation CursorLoc = TextBox->GetCursorLocation();
		return CursorLoc.GetLineIndex() + 1; // Convert 0-based to 1-based.
	}
	return 1;
}


int32 SMCACodeEditor::GetCursorColumn() const
{
	if (TextBox.IsValid())
	{
		FTextLocation CursorLoc = TextBox->GetCursorLocation();
		return CursorLoc.GetOffset() + 1; // Convert 0-based to 1-based.
	}
	return 1;
}


void SMCACodeEditor::GoToLine(int32 LineNumber)
{
	if (TextBox.IsValid())
	{
		TextBox->GoTo(FTextLocation(LineNumber - 1, 0));
	}
}


void SMCACodeEditor::ToggleComment()
{
	if (!TextBox.IsValid())
	{
		return;
	}

	// Get the full text and figure out which lines are affected.
	FString FullText = TextBox->GetText().ToString();
	TArray<FString> Lines;
	FullText.ParseIntoArrayLines(Lines);

	// Determine the affected line range from the cursor position.
	// If there's a selection, it spans multiple lines; otherwise just the cursor line.
	int32 StartLine = GetCursorLine() - 1; // 0-based
	int32 EndLine = StartLine;

	// Clamp to valid range.
	StartLine = FMath::Clamp(StartLine, 0, Lines.Num() - 1);
	EndLine = FMath::Clamp(EndLine, 0, Lines.Num() - 1);

	// Check if ALL affected lines are already commented — if so, uncomment.
	bool bAllCommented = true;
	for (int32 i = StartLine; i <= EndLine; ++i)
	{
		FString Trimmed = Lines[i].TrimStart();
		if (!Trimmed.IsEmpty() && !Trimmed.StartsWith(TEXT("#")))
		{
			bAllCommented = false;
			break;
		}
	}

	// Apply the toggle.
	for (int32 i = StartLine; i <= EndLine; ++i)
	{
		if (bAllCommented)
		{
			// Remove the first "# " or "#" from each line.
			int32 HashIdx = Lines[i].Find(TEXT("#"));
			if (HashIdx != INDEX_NONE)
			{
				// Remove "# " (hash + space) if present, otherwise just "#".
				if (HashIdx + 1 < Lines[i].Len() && Lines[i][HashIdx + 1] == TEXT(' '))
				{
					Lines[i].RemoveAt(HashIdx, 2);
				}
				else
				{
					Lines[i].RemoveAt(HashIdx, 1);
				}
			}
		}
		else
		{
			// Add "# " at the start (after any leading whitespace indentation).
			int32 InsertPos = 0;
			while (InsertPos < Lines[i].Len() && FChar::IsWhitespace(Lines[i][InsertPos]))
			{
				InsertPos++;
			}
			Lines[i].InsertAt(InsertPos, TEXT("# "));
		}
	}

	// Rebuild the full text and set it back.
	FString NewText = FString::Join(Lines, TEXT("\n"));
	TextBox->SetText(FText::FromString(NewText));
}


void SMCACodeEditor::IndentSelection()
{
	if (!TextBox.IsValid())
	{
		return;
	}

	// Get settings for tab size and spaces vs tabs.
	const UMCAEditorSettings* Settings = UMCAEditorSettings::GetSettings();
	int32 TabSize = Settings ? Settings->TabSize : 4;
	bool bUseSpaces = Settings ? Settings->bUseSpaces : true;

	FString IndentStr;
	if (bUseSpaces)
	{
		for (int32 i = 0; i < TabSize; ++i)
		{
			IndentStr += TEXT(" ");
		}
	}
	else
	{
		IndentStr = TEXT("\t");
	}

	// Get the full text and work on the affected lines.
	FString FullText = TextBox->GetText().ToString();
	TArray<FString> Lines;
	FullText.ParseIntoArrayLines(Lines);

	int32 TargetLine = GetCursorLine() - 1;
	TargetLine = FMath::Clamp(TargetLine, 0, Lines.Num() - 1);

	// Prepend the indent string.
	Lines[TargetLine] = IndentStr + Lines[TargetLine];

	FString NewText = FString::Join(Lines, TEXT("\n"));
	TextBox->SetText(FText::FromString(NewText));
}


void SMCACodeEditor::DedentSelection()
{
	if (!TextBox.IsValid())
	{
		return;
	}

	const UMCAEditorSettings* Settings = UMCAEditorSettings::GetSettings();
	int32 TabSize = Settings ? Settings->TabSize : 4;

	FString FullText = TextBox->GetText().ToString();
	TArray<FString> Lines;
	FullText.ParseIntoArrayLines(Lines);

	int32 TargetLine = GetCursorLine() - 1;
	TargetLine = FMath::Clamp(TargetLine, 0, Lines.Num() - 1);

	FString& Line = Lines[TargetLine];

	// Remove up to TabSize leading spaces, or one leading tab.
	if (Line.Len() > 0 && Line[0] == TEXT('\t'))
	{
		Line.RemoveAt(0, 1);
	}
	else
	{
		int32 SpacesToRemove = 0;
		while (SpacesToRemove < TabSize && SpacesToRemove < Line.Len() && Line[SpacesToRemove] == TEXT(' '))
		{
			SpacesToRemove++;
		}
		if (SpacesToRemove > 0)
		{
			Line.RemoveAt(0, SpacesToRemove);
		}
	}

	FString NewText = FString::Join(Lines, TEXT("\n"));
	TextBox->SetText(FText::FromString(NewText));
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
	UpdateLineNumbers();
	OnTextChangedDelegate.ExecuteIfBound();
}


void SMCACodeEditor::UpdateLineNumbers()
{
	if (!LineNumbersWidget.IsValid() || !TextBox.IsValid())
	{
		return;
	}

	// Count lines in the editor text.
	FString Content = TextBox->GetText().ToString();
	int32 LineCount = 1;
	for (int32 i = 0; i < Content.Len(); ++i)
	{
		if (Content[i] == TEXT('\n'))
		{
			LineCount++;
		}
	}

	// Build the line numbers string (one number per line).
	FString LineNumbers;
	for (int32 i = 1; i <= LineCount; ++i)
	{
		if (i > 1)
		{
			LineNumbers += TEXT("\n");
		}
		LineNumbers += FString::Printf(TEXT("%d"), i);
	}

	// Cast to STextBlock — LineNumbersWidget is stored as TSharedPtr<SWidget>
	// in the header but we assigned an STextBlock above.
	TSharedPtr<STextBlock> LineNumTextBlock = StaticCastSharedPtr<STextBlock>(LineNumbersWidget);
	if (LineNumTextBlock.IsValid())
	{
		LineNumTextBlock->SetText(FText::FromString(LineNumbers));
	}
}


void SMCACodeEditor::HandleTextCommitted(const FText& NewText, ETextCommit::Type CommitType)
{
	// No special handling needed — text changes are tracked via HandleTextChanged.
}


void SMCACodeEditor::HandleCursorMoved(const FTextLocation& NewCursorPosition)
{
	// Fire the cursor position delegate so the status bar can update.
	int32 Line = NewCursorPosition.GetLineIndex() + 1;
	int32 Column = NewCursorPosition.GetOffset() + 1;
	OnCursorMovedDelegate.ExecuteIfBound(Line, Column);
}
