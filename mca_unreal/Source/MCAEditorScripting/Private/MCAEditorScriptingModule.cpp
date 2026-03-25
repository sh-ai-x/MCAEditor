// MCA Editor Scripting Module — Startup/shutdown implementation.
//
// Minimal module that just logs its presence. The actual work is done
// by the BlueprintFunctionLibrary classes which are auto-registered
// by UE's reflection system.

#include "MCAEditorScriptingModule.h"

// Define our custom log category.
DEFINE_LOG_CATEGORY(LogMCAScripting);

#define LOCTEXT_NAMESPACE "FMCAEditorScriptingModule"


void FMCAEditorScriptingModule::StartupModule()
{
	UE_LOG(LogMCAScripting, Log, TEXT("MCAEditorScripting: Module loaded — AnimBP and Blueprint graph APIs available"));
}


void FMCAEditorScriptingModule::ShutdownModule()
{
	UE_LOG(LogMCAScripting, Log, TEXT("MCAEditorScripting: Module unloaded"));
}


#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FMCAEditorScriptingModule, MCAEditorScripting)
