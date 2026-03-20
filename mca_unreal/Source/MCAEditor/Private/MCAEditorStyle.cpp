// MCA Editor Style — Slate style set implementation.
//
// Dark theme colors ported from mca_qt/theme.py. Provides consistent
// styling across all MCA Editor widgets.

#include "MCAEditorStyle.h"

#include "Framework/Application/SlateApplication.h"
#include "Interfaces/IPluginManager.h"
#include "Styling/SlateStyleRegistry.h"
#include "Styling/SlateTypes.h"
#include "Styling/CoreStyle.h"
#include "Styling/SlateStyleMacros.h"

// --- Color Constants (ported from mca_qt/theme.py) ---------------------

const FLinearColor FMCAEditorStyle::BackgroundColor(0.118f, 0.118f, 0.118f, 1.0f);   // #1E1E1E
const FLinearColor FMCAEditorStyle::PanelColor(0.145f, 0.145f, 0.149f, 1.0f);        // #252526
const FLinearColor FMCAEditorStyle::ActiveColor(0.176f, 0.176f, 0.176f, 1.0f);       // #2D2D2D
const FLinearColor FMCAEditorStyle::TextColor(0.831f, 0.831f, 0.831f, 1.0f);         // #D4D4D4
const FLinearColor FMCAEditorStyle::KeywordColor(0.337f, 0.612f, 0.839f, 1.0f);      // #569CD6
const FLinearColor FMCAEditorStyle::StringColor(0.808f, 0.569f, 0.471f, 1.0f);       // #CE9178
const FLinearColor FMCAEditorStyle::CommentColor(0.416f, 0.600f, 0.333f, 1.0f);      // #6A9955
const FLinearColor FMCAEditorStyle::NumberColor(0.710f, 0.808f, 0.659f, 1.0f);       // #B5CEA8
const FLinearColor FMCAEditorStyle::DecoratorColor(0.863f, 0.863f, 0.667f, 1.0f);    // #DCDCAA
const FLinearColor FMCAEditorStyle::BuiltinColor(0.773f, 0.522f, 0.753f, 1.0f);      // #C586C0
const FLinearColor FMCAEditorStyle::ErrorColor(0.957f, 0.278f, 0.278f, 1.0f);        // #F44747
const FLinearColor FMCAEditorStyle::WarningColor(0.800f, 0.655f, 0.000f, 1.0f);      // #CCA700
const FLinearColor FMCAEditorStyle::ResultColor(0.306f, 0.788f, 0.690f, 1.0f);       // #4EC9B0
const FLinearColor FMCAEditorStyle::LineNumberColor(0.522f, 0.522f, 0.522f, 1.0f);   // #858585
const FLinearColor FMCAEditorStyle::CurrentLineColor(0.165f, 0.176f, 0.180f, 1.0f);  // #2A2D2E
const FLinearColor FMCAEditorStyle::AccentColor(0.910f, 0.573f, 0.165f, 1.0f);       // #E8922A

// --- Singleton Management ----------------------------------------------

TSharedPtr<FSlateStyleSet> FMCAEditorStyle::StyleInstance = nullptr;


void FMCAEditorStyle::Initialize()
{
	if (!StyleInstance.IsValid())
	{
		StyleInstance = Create();
		FSlateStyleRegistry::RegisterSlateStyle(*StyleInstance);
	}
}


void FMCAEditorStyle::Shutdown()
{
	FSlateStyleRegistry::UnRegisterSlateStyle(*StyleInstance);
	ensure(StyleInstance.IsUnique());
	StyleInstance.Reset();
}


void FMCAEditorStyle::ReloadTextures()
{
	if (FSlateApplication::IsInitialized())
	{
		FSlateApplication::Get().GetRenderer()->ReloadTextureResources();
	}
}


const ISlateStyle& FMCAEditorStyle::Get()
{
	return *StyleInstance;
}


FName FMCAEditorStyle::GetStyleSetName()
{
	static FName StyleSetName(TEXT("MCAEditorStyle"));
	return StyleSetName;
}


TSharedRef<FSlateStyleSet> FMCAEditorStyle::Create()
{
	TSharedRef<FSlateStyleSet> Style = MakeShareable(new FSlateStyleSet(GetStyleSetName()));

	// Set the content root to our plugin's Resources directory.
	Style->SetContentRoot(IPluginManager::Get().FindPlugin("MCAEditor")->GetBaseDir() / TEXT("Resources"));

	// --- Editor Text Style -------------------------------------------------
	// Default monospace text style for the code editor.
	const FTextBlockStyle EditorTextStyle = FTextBlockStyle()
		.SetFont(FCoreStyle::GetDefaultFontStyle("Mono", 12))
		.SetColorAndOpacity(FSlateColor(TextColor));

	Style->Set("MCAEditor.EditorText", EditorTextStyle);

	// --- Output Text Styles ------------------------------------------------
	// Info output (white/default).
	Style->Set("MCAEditor.OutputInfo", FTextBlockStyle(EditorTextStyle)
		.SetColorAndOpacity(FSlateColor(TextColor)));

	// Warning output (yellow).
	Style->Set("MCAEditor.OutputWarning", FTextBlockStyle(EditorTextStyle)
		.SetColorAndOpacity(FSlateColor(WarningColor)));

	// Error output (red).
	Style->Set("MCAEditor.OutputError", FTextBlockStyle(EditorTextStyle)
		.SetColorAndOpacity(FSlateColor(ErrorColor)));

	// Result output (cyan).
	Style->Set("MCAEditor.OutputResult", FTextBlockStyle(EditorTextStyle)
		.SetColorAndOpacity(FSlateColor(ResultColor)));

	// --- Syntax Highlight Styles -------------------------------------------
	Style->Set("MCAEditor.Keyword", FTextBlockStyle(EditorTextStyle)
		.SetColorAndOpacity(FSlateColor(KeywordColor)));

	Style->Set("MCAEditor.String", FTextBlockStyle(EditorTextStyle)
		.SetColorAndOpacity(FSlateColor(StringColor)));

	Style->Set("MCAEditor.Comment", FTextBlockStyle(EditorTextStyle)
		.SetColorAndOpacity(FSlateColor(CommentColor)));

	Style->Set("MCAEditor.Number", FTextBlockStyle(EditorTextStyle)
		.SetColorAndOpacity(FSlateColor(NumberColor)));

	Style->Set("MCAEditor.Decorator", FTextBlockStyle(EditorTextStyle)
		.SetColorAndOpacity(FSlateColor(DecoratorColor)));

	Style->Set("MCAEditor.Builtin", FTextBlockStyle(EditorTextStyle)
		.SetColorAndOpacity(FSlateColor(BuiltinColor)));

	// --- Line Number Style -------------------------------------------------
	Style->Set("MCAEditor.LineNumber", FTextBlockStyle(EditorTextStyle)
		.SetColorAndOpacity(FSlateColor(LineNumberColor)));

	// --- Icons -------------------------------------------------------------
	Style->Set("MCAEditor.TabIcon", new FSlateImageBrush(
		Style->RootToContentDir(TEXT("Icon16"), TEXT(".png")), FVector2D(16.0f, 16.0f)));
	Style->Set("MCAEditor.ToolbarIcon", new FSlateImageBrush(
		Style->RootToContentDir(TEXT("Icon40"), TEXT(".png")), FVector2D(40.0f, 40.0f)));

	return Style;
}
