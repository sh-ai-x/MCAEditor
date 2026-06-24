# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def anim_set_default_state(asset_path: str, state_machine: str, state: str):
    """Set a state machine's entry (default) state.

    :param asset_path: Content path to the Animation Blueprint.
    :param state_machine: Name of the state machine.
    :param state: Name of the state to use as entry.
    """
    import unreal

    if not hasattr(unreal, "MCAAnimBlueprintLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    abp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if abp is None:
        return {"success": False, "message": "AnimBlueprint not found at '{}'.".format(asset_path)}

    ok = unreal.MCAAnimBlueprintLibrary.set_default_state(abp, state_machine, state)
    return {"success": bool(ok), "asset_path": asset_path, "state_machine": state_machine, "state": state}
