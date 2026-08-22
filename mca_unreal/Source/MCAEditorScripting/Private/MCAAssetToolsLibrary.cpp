// MCA Asset Tools Library — Implementation.
//
// Thin, automation-safe wrappers over ObjectTools. The engine calls default
// to showing modal confirmation dialogs; every call here passes false so
// nothing blocks a headless or MCP-driven session.
//
// Key patterns:
//   - ObjectTools::ConsolidateObjects takes a mutable TArray& and reorders it,
//     so it is handed a local copy rather than the caller's array
//   - Results are reported by count plus explicit out-arrays; callers should
//     verify by re-querying the reference graph, not by trusting the return
//   - Nothing is saved here — the caller saves the dirtied packages

#include "MCAAssetToolsLibrary.h"
#include "MCAEditorScriptingModule.h"

#include "ObjectTools.h"
#include "UObject/Package.h"


// =============================================================================
// Reference Replacement
// =============================================================================

int32 UMCAAssetToolsLibrary::ReplaceReferences(
	UObject* TargetAsset,
	const TArray<UObject*>& SourceAssets,
	TArray<UObject*>& OutFailed,
	TArray<FString>& OutDirtiedPackages)
{
	OutFailed.Reset();
	OutDirtiedPackages.Reset();

	if (!TargetAsset)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("ReplaceReferences: TargetAsset is null"));
		return 0;
	}

	// Filter out nulls and self-references. Consolidating an asset into itself
	// would delete the target, which is never what the caller wants.
	TArray<UObject*> ToConsolidate;
	ToConsolidate.Reserve(SourceAssets.Num());
	for (UObject* Source : SourceAssets)
	{
		if (!Source)
		{
			continue;
		}

		if (Source == TargetAsset)
		{
			UE_LOG(LogMCAScripting, Warning,
				TEXT("ReplaceReferences: skipping '%s' - same object as the target"),
				*Source->GetPathName());
			continue;
		}

		ToConsolidate.Add(Source);
	}

	if (ToConsolidate.Num() == 0)
	{
		UE_LOG(LogMCAScripting, Warning, TEXT("ReplaceReferences: nothing to consolidate"));
		return 0;
	}

	const int32 NumRequested = ToConsolidate.Num();

	// The 2-argument ConsolidateObjects overload hardcodes bWarnAboutRootSet=true.
	// When any source is in the root set it opens a Yes/No dialog which defaults to
	// No, and a No answer aborts the whole operation via an early return - silently,
	// with empty results. Headless callers therefore always get a no-op. Use the long
	// overload so bWarnAboutRootSet can be false, which skips the prompt and clears
	// the root flags instead. Empty "within" sets mean "consolidate everywhere",
	// matching what the short overload passes.
	TSet<UObject*> ConsolidateWithin;
	TSet<UObject*> DoNotConsolidateWithin;

	ObjectTools::FConsolidationResults Results =
		ObjectTools::ConsolidateObjects(
			TargetAsset,
			ToConsolidate,
			ConsolidateWithin,
			DoNotConsolidateWithin,
			/*bShouldDeleteAfterConsolidate=*/true,
			/*bWarnAboutRootSet=*/false);

	for (const TObjectPtr<UObject>& Failed : Results.FailedConsolidationObjs)
	{
		if (Failed)
		{
			OutFailed.AddUnique(Failed.Get());
			UE_LOG(LogMCAScripting, Warning, TEXT("ReplaceReferences: failed to consolidate '%s'"),
				*Failed->GetPathName());
		}
	}

	for (const TObjectPtr<UObject>& Invalid : Results.InvalidConsolidationObjs)
	{
		if (Invalid)
		{
			OutFailed.AddUnique(Invalid.Get());
			UE_LOG(LogMCAScripting, Warning, TEXT("ReplaceReferences: '%s' was invalid for consolidation"),
				*Invalid->GetPathName());
		}
	}

	for (const TObjectPtr<UPackage>& Package : Results.DirtiedPackages)
	{
		if (Package)
		{
			OutDirtiedPackages.AddUnique(Package->GetName());
		}
	}

	// A consolidation that replaced anything always dirties at least the package
	// holding the rewritten reference. Zero dirtied packages with zero reported
	// failures is the signature of an internal early-out rather than success, so
	// report it as a failure instead of a silent no-op - callers of this API have
	// been burned by engine calls that return "success" without doing anything.
	if (Results.DirtiedPackages.Num() == 0 && OutFailed.Num() == 0)
	{
		UE_LOG(LogMCAScripting, Error,
			TEXT("ReplaceReferences: consolidation into '%s' dirtied no packages and reported no ")
			TEXT("failures - it did not take effect. Nothing was changed."),
			*TargetAsset->GetPathName());
		return 0;
	}

	const int32 NumSucceeded = FMath::Max(0, NumRequested - OutFailed.Num());

	UE_LOG(LogMCAScripting, Log,
		TEXT("ReplaceReferences: %d/%d consolidated into '%s' (%d packages dirtied, %d failed)"),
		NumSucceeded, NumRequested, *TargetAsset->GetPathName(),
		OutDirtiedPackages.Num(), OutFailed.Num());

	return NumSucceeded;
}


// =============================================================================
// Deletion
// =============================================================================

int32 UMCAAssetToolsLibrary::ForceDeleteAssets(const TArray<UObject*>& Assets)
{
	TArray<UObject*> ToDelete;
	ToDelete.Reserve(Assets.Num());
	for (UObject* Asset : Assets)
	{
		if (Asset)
		{
			ToDelete.Add(Asset);
		}
	}

	if (ToDelete.Num() == 0)
	{
		UE_LOG(LogMCAScripting, Warning, TEXT("ForceDeleteAssets: nothing to delete"));
		return 0;
	}

	// ShowConfirmation = false: never prompt.
	const int32 NumDeleted = ObjectTools::ForceDeleteObjects(ToDelete, /*ShowConfirmation=*/false);

	UE_LOG(LogMCAScripting, Log, TEXT("ForceDeleteAssets: deleted %d/%d"),
		NumDeleted, ToDelete.Num());

	return NumDeleted;
}
