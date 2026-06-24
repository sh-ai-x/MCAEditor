# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def anim_add_state(asset_path: str, state_machine: str, state: str):
    """Add a state to a state machine.

    :param asset_path: Content path to the Animation Blueprint.
    :param state_machine: Name of the target state machine.
    :param state: Name for the new state.
    """
    import unreal

    if not hasattr(unreal, "MCAAnimBlueprintLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    abp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if abp is None:
        return {"success": False, "message": "AnimBlueprint not found at '{}'.".format(asset_path)}

    ok = unreal.MCAAnimBlueprintLibrary.add_state(abp, state_machine, state)
    return {"success": bool(ok), "asset_path": asset_path, "state_machine": state_machine, "state": state}
