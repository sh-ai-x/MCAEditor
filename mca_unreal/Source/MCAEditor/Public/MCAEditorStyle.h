// MCA Editor Style — Slate styling definitions.
//
// Manages the dark theme styling for the MCA Editor widgets. Color values
// are ported from the Python version's mca_qt/theme.py.

#pragma once

#include "CoreMinimal.h"
#include "Styling/SlateStyle.h"

/**
 * Slate style set for MCA Editor.
 *
 * Provides consistent dark-theme colors, fonts, and widget styles across
 * all MCA Editor Slate widgets. Registered as "MCAEditorStyle" with
 * the Slate style registry.
 */
class FMCAEditorStyle
{
public:

	/** Initialize the style set. Call once during module startup. */
	static void Initialize();

	/** Clean up the style set. Call during module shutdown. */
	static void Shutdown();

	/** Reload textures used by the style set. */
	static void ReloadTextures();

	/** Get the singleton style set instance. */
	static const ISlateStyle& Get();

	/** Get the style set name. */
	static FName GetStyleSetName();

	// --- Color Constants (from mca_qt/theme.py) ---------------------------

	/** Editor background color (#1E1E1E). */
	static const FLinearColor BackgroundColor;

	/** Sidebar / panel background (#252526). */
	static const FLinearColor PanelColor;

	/** Active tab / selection highlight (#2D2D2D). */
	static const FLinearColor ActiveColor;

	/** Text color (#D4D4D4). */
	static const FLinearColor TextColor;

	/** Keyword blue (#569CD6). */
	static const FLinearColor KeywordColor;

	/** String green (#CE9178). */
	static const FLinearColor StringColor;

	/** Comment gray (#6A9955). */
	static const FLinearColor CommentColor;

	/** Number orange (#B5CEA8). */
	static const FLinearColor NumberColor;

	/** Decorator yellow (#DCDCAA). */
	static const FLinearColor DecoratorColor;

	/** Built-in function purple (#C586C0). */
	static const FLinearColor BuiltinColor;

	/** Error red (#F44747). */
	static const FLinearColor ErrorColor;

	/** Warning yellow (#CCA700). */
	static const FLinearColor WarningColor;

	/** Result cyan (#4EC9B0). */
	static const FLinearColor ResultColor;

	/** Line number gray (#858585). */
	static const FLinearColor LineNumberColor;

	/** Current line highlight (#2A2D2E). */
	static const FLinearColor CurrentLineColor;

	/** Orange Slice accent (#E8922A). */
	static const FLinearColor AccentColor;

private:

	/** Create the style set. */
	static TSharedRef<class FSlateStyleSet> Create();

	/** Singleton instance. */
	static TSharedPtr<class FSlateStyleSet> StyleInstance;
};
