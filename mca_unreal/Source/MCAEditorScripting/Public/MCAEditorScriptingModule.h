// MCA Editor Scripting Module — Public header.
//
// Minimal editor module that registers the MCAEditorScripting
// BlueprintFunctionLibrary classes. The actual APIs live in the
// library headers — this module just ensures they get loaded.

#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"

// Custom log category for scripting operations.
DECLARE_LOG_CATEGORY_EXTERN(LogMCAScripting, Log, All);

/**
 * Editor-only module that exposes Animation Blueprint and Blueprint graph
 * editing APIs to Python via UFUNCTION(BlueprintCallable).
 *
 * Loaded automatically by the MCAEditor plugin. No manual setup needed.
 */
class FMCAEditorScriptingModule : public IModuleInterface
{
public:

	/** Called when the module is loaded. */
	virtual void StartupModule() override;

	/** Called when the module is unloaded. */
	virtual void ShutdownModule() override;
};
