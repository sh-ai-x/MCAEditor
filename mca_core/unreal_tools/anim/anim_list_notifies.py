# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def anim_list_notifies(anim_asset_path: str):
    """List the named notifies on a sequence as "Name@Time" strings.

    :param anim_asset_path: Content path to the AnimSequence.
    """
    import unreal

    if not hasattr(unreal, "MCAAnimBlueprintLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    seq = unreal.EditorAssetLibrary.load_asset(anim_asset_path)
    if seq is None:
        return {"success": False, "message": "Animation sequence not found at '{}'.".format(anim_asset_path)}

    items = unreal.MCAAnimBlueprintLibrary.list_anim_notifies(seq)
    return {"success": True, "anim": anim_asset_path, "notifies": [str(n) for n in items]}
