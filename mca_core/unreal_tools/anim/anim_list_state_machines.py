# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def anim_list_state_machines(asset_path: str):
    """List the state machines in an Animation Blueprint.

    :param asset_path: Content path to the Animation Blueprint.
    """
    import unreal

    if not hasattr(unreal, "MCAAnimBlueprintLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    abp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if abp is None:
        return {"success": False, "message": "AnimBlueprint not found at '{}'.".format(asset_path)}

    names = unreal.MCAAnimBlueprintLibrary.list_state_machines(abp)
    return {"success": True, "asset_path": asset_path,
            "state_machines": [str(n) for n in names]}
