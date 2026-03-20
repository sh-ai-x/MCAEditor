// MCA Editor Settings — UDeveloperSettings for Project Settings integration.
//
// Exposes editor configuration in Project Settings > Plugins > MCA Editor.
// Mirrors the ~60 keys in mca_editor/config/settings.py but starts with
// the essential subset for Phase 1.

#pragma once

#include "CoreMinimal.h"
#include "Engine/DeveloperSettings.h"
#include "MCAEditorSettings.generated.h"

/**
 * MCA Editor plugin settings.
 *
 * Registered under Project Settings > Plugins > MCA Editor.
 * Persisted in Saved/Config/ via UE's config system.
 */
UCLASS(config = EditorPerProjectUserSettings, defaultconfig, meta = (DisplayName = "MCA Editor"))
class UMCAEditorSettings : public UDeveloperSettings
{
	GENERATED_BODY()

public:

	UMCAEditorSettings();

	// --- Font Settings ----------------------------------------------------

	/** Font family for the code editor. */
	UPROPERTY(config, EditAnywhere, Category = "Font", meta = (DisplayName = "Font Family"))
	FString FontFamily;

	/** Font size in points. */
	UPROPERTY(config, EditAnywhere, Category = "Font", meta = (DisplayName = "Font Size", ClampMin = 8, ClampMax = 72))
	int32 FontSize;

	// --- Editor Behavior --------------------------------------------------

	/** Number of spaces per tab stop. */
	UPROPERTY(config, EditAnywhere, Category = "Editor", meta = (DisplayName = "Tab Size", ClampMin = 1, ClampMax = 8))
	int32 TabSize;

	/** Use spaces instead of tabs for indentation. */
	UPROPERTY(config, EditAnywhere, Category = "Editor", meta = (DisplayName = "Use Spaces"))
	bool bUseSpaces;

	/** Show line numbers in the gutter. */
	UPROPERTY(config, EditAnywhere, Category = "Editor", meta = (DisplayName = "Show Line Numbers"))
	bool bShowLineNumbers;

	/** Enable word wrap. */
	UPROPERTY(config, EditAnywhere, Category = "Editor", meta = (DisplayName = "Word Wrap"))
	bool bWordWrap;

	/** Auto-save the file before executing code. */
	UPROPERTY(config, EditAnywhere, Category = "Editor", meta = (DisplayName = "Auto-Save on Execute"))
	bool bAutoSaveOnExecute;

	// --- Python Execution -------------------------------------------------

	/** Port for remote Python execution (0 = use in-process). */
	UPROPERTY(config, EditAnywhere, Category = "Python", meta = (DisplayName = "Remote Execution Port", ClampMin = 0, ClampMax = 65535))
	int32 RemoteExecutionPort;

	// --- Accessors --------------------------------------------------------

	/** Get the singleton settings instance. */
	static const UMCAEditorSettings* GetSettings();

	// --- UDeveloperSettings Interface -------------------------------------

	virtual FName GetContainerName() const override { return TEXT("Project"); }
	virtual FName GetCategoryName() const override { return TEXT("Plugins"); }
	virtual FName GetSectionName() const override { return TEXT("MCA Editor"); }
};
