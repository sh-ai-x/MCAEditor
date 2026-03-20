// MCA Editor — Unreal Build Tool module rules.
//
// Defines dependencies, include paths, and compiler settings for the
// MCA Editor plugin. Embeds the PySide6/Qt MCA Editor inside a Slate
// tab via Win32 native window hosting (same codebase as Maya version).

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
				"UnrealEd",
				"EditorStyle",
				"ToolMenus",
				"Projects",
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
