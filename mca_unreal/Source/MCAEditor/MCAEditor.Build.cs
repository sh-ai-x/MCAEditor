// MCA Editor — Unreal Build Tool module rules.
//
// Defines dependencies, include paths, and compiler settings for the
// MCA Editor plugin. Mirrors the Python/PySide6 Maya version's architecture
// but uses Slate widgets and UE's built-in Python interpreter.

using UnrealBuildTool;

public class MCAEditor : ModuleRules
{
	public MCAEditor(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;

		// --- Public Dependencies -------------------------------------------
		// Core UE modules needed for Slate UI and editor integration.
		PublicDependencyModuleNames.AddRange(
			new string[]
			{
				"Core",
			}
		);

		// --- Private Dependencies ------------------------------------------
		// Modules used internally but not exposed in our public headers.
		PrivateDependencyModuleNames.AddRange(
			new string[]
			{
				"CoreUObject",
				"Engine",
				"Slate",
				"SlateCore",
				"InputCore",
				"UnrealEd",
				"EditorStyle",
				"ToolMenus",
				"Projects",
				"EditorSubsystem",
				"DirectoryWatcher",
				"DesktopPlatform",
				"DeveloperSettings",
				"ApplicationCore",
			}
		);

		// Soft dependency on PythonScriptPlugin — warn if not available but
		// don't prevent compilation. Users must enable it for execution.
		PrivateIncludePathModuleNames.AddRange(
			new string[]
			{
				"PythonScriptPlugin",
			}
		);
	}
}
