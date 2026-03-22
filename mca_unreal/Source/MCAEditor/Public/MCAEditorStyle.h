// MCA Editor Style — Slate styling definitions.
//
// Minimal style set for the MCA Editor plugin. Only provides the
// toolbar and tab icons — all editor UI styling lives in PySide6.

#pragma once

#include "CoreMinimal.h"
#include "Styling/SlateStyle.h"

/**
 * Slate style set for MCA Editor.
 *
 * Provides toolbar/tab icons for the plugin. Registered as
 * "MCAEditorStyle" with the Slate style registry.
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

private:

	/** Create the style set. */
	static TSharedRef<class FSlateStyleSet> Create();

	/** Singleton instance. */
	static TSharedPtr<class FSlateStyleSet> StyleInstance;
};
