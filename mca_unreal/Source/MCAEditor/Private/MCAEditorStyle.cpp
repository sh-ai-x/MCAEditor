// MCA Editor Style — Slate style set implementation.
//
// Minimal style set that only provides toolbar and tab icons.
// All editor UI styling lives in PySide6 (mca_qt/theme.py).

#include "MCAEditorStyle.h"

#include "Framework/Application/SlateApplication.h"
#include "Interfaces/IPluginManager.h"
#include "Styling/SlateStyleRegistry.h"
#include "Styling/SlateTypes.h"
#include "Styling/CoreStyle.h"

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

	// --- Icons -------------------------------------------------------------
	Style->Set("MCAEditor.TabIcon", new FSlateImageBrush(
		Style->RootToContentDir(TEXT("Icon16"), TEXT(".png")), FVector2D(16.0f, 16.0f)));
	Style->Set("MCAEditor.ToolbarIcon", new FSlateImageBrush(
		Style->RootToContentDir(TEXT("Icon40"), TEXT(".png")), FVector2D(40.0f, 40.0f)));

	return Style;
}
