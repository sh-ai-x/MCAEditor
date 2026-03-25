// MCA Editor Scripting — Unreal Build Tool module rules.
//
// Editor-only module that exposes Animation Blueprint and Blueprint graph
// manipulation APIs to Python. Ships with the MCA Editor plugin so it
// works in any project — no per-project C++ needed.
//
// These UFUNCTION(BlueprintCallable) functions are auto-exposed to UE's
// Python interpreter, making them available to both direct Python scripts
// and MCA Editor's MCP tools.

using UnrealBuildTool;

public class MCAEditorScripting : ModuleRules
{
	public MCAEditorScripting(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;

		// --- Public Dependencies -------------------------------------------
		PublicDependencyModuleNames.AddRange(
			new string[]
			{
				"Core",
				"CoreUObject",
				"Engine",
			}
		);

		// --- Private Dependencies ------------------------------------------
		// AnimGraph + BlueprintGraph for graph node creation.
		// UnrealEd + Kismet for FBlueprintEditorUtils and transactions.
		PrivateDependencyModuleNames.AddRange(
			new string[]
			{
				"Slate",
				"SlateCore",
				"UnrealEd",
				"BlueprintGraph",
				"AnimGraph",
				"AnimGraphRuntime",
				"Kismet",
				"KismetCompiler",
				"ToolMenus",
				"AssetTools",
			}
		);
	}
}
