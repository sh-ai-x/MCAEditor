// MCA Asset Tools Library — Public API header.
//
// Exposes asset reference surgery to Python: replacing every reference to
// one asset with another ("Replace References" in the Content Browser), and
// force deleting assets by nulling whatever still points at them.
//
// These wrap ObjectTools entry points that the Content Browser context menu
// uses but UE's Python API does not reach:
//   - unreal.EditorAssetLibrary.consolidate_assets() returns True without
//     rewriting any references or deleting the source, so it cannot be used
//     to repoint an asset.
//   - unreal.EditorAssetLibrary.delete_asset() refuses any asset that is
//     still referenced, and there is no scripted equivalent of Force Delete.
//
// All functions are static BlueprintCallable, so they appear in Python as:
//   unreal.MCAAssetToolsLibrary.replace_references(...)
//   unreal.MCAAssetToolsLibrary.force_delete_assets(...)

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "MCAAssetToolsLibrary.generated.h"

/**
 * Static library of asset reference-graph editing functions.
 *
 * These operations rewrite references inside already-loaded packages, which
 * is the only way to repoint assets held in editor-only properties that are
 * not exposed to Python (chooser table rows, pose search database entries,
 * and similar instanced-struct arrays).
 *
 * Callers are responsible for saving the dirtied packages afterwards —
 * neither function saves, so a failed run can be discarded by reloading.
 */
UCLASS()
class MCAEDITORSCRIPTING_API UMCAAssetToolsLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:

	// --- Reference Replacement ------------------------------------------------

	/**
	 * Replace all references to SourceAssets with references to TargetAsset,
	 * then delete the sources, leaving object redirectors behind.
	 *
	 * This is the scripted equivalent of the Content Browser's
	 * "Replace References" / Consolidate Assets action.
	 *
	 * References are rewritten BEFORE the sources are deleted, so a source
	 * that cannot be deleted (for example an AnimSequence pinned by a rooted
	 * AnimSequencerController) still gets fully repointed — it is just left
	 * on disk for a later cleanup pass.
	 *
	 * No type checking is performed, matching the underlying engine call.
	 * Replacing an asset with one of a different class is possible and will
	 * corrupt the referencing property, so pass matched pairs.
	 *
	 * @param TargetAsset         Asset that all references will point at afterwards.
	 * @param SourceAssets        Assets whose references get rewritten; each is then deleted.
	 * @param OutFailed           Sources that failed or were invalid for consolidation.
	 * @param OutDirtiedPackages  Package names dirtied by the operation — save these.
	 * @return Number of sources consolidated successfully.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Asset Tools",
		meta = (DisplayName = "Replace References"))
	static int32 ReplaceReferences(
		UObject* TargetAsset,
		const TArray<UObject*>& SourceAssets,
		TArray<UObject*>& OutFailed,
		TArray<FString>& OutDirtiedPackages
	);

	// --- Deletion -------------------------------------------------------------

	/**
	 * Force delete assets, nulling any references that still point at them.
	 *
	 * The scripted equivalent of Content Browser "Delete -> Force Delete".
	 * Unlike EditorAssetLibrary.delete_asset(), this succeeds even when the
	 * assets are still referenced; referencing properties are set to null and
	 * their packages are dirtied.
	 *
	 * Note that force delete can still fail for objects pinned by a rooted
	 * transient object. Compare the return value against the input count and
	 * check the log rather than assuming success.
	 *
	 * @param Assets  Assets to delete.
	 * @return Number of assets actually deleted.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Asset Tools",
		meta = (DisplayName = "Force Delete Assets"))
	static int32 ForceDeleteAssets(const TArray<UObject*>& Assets);
};
