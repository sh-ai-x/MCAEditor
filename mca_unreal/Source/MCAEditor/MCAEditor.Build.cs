// MCA Editor — Unreal Build Tool module rules.
//
// Minimal dependencies for the PySide6 launcher plugin. The C++ side
// only provides a toolbar button, menu entry, and Qt event pump tick.
// All editor UI lives in PySide6/Qt, launched via IPythonScriptPlugin.

using UnrealBuildTool;

public class MCAEditor : ModuleRules
{
	public MCAEditor(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;

		// --- Public Dependencies -------------------------------------------
		PublicDependencyModuleNames.AddRange(
			new string[]
			{
				"Core",
			}
		);

		// --- Private Dependencies ------------------------------------------
		// Minimal set needed for toolbar registration and Python execution.
		PrivateDependencyModuleNames.AddRange(
			new string[]
			{
				"CoreUObject",
				"Engine",
				"Slate",
				"SlateCore",
				"InputCore",
				"UnrealEd",
				"ToolMenus",
				"Projects",
				"PythonScriptPlugin",
			}
		);
	}
}
