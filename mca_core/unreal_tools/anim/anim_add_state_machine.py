# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def anim_add_state_machine(asset_path: str, state_machine: str, connect_to_root: bool = True):
    """Add a state machine to an AnimBP's AnimGraph.

    :param asset_path: Content path to the Animation Blueprint.
    :param state_machine: Name for the new state machine.
    :param connect_to_root: Wire its output to the AnimGraph result pose.
    """
    import unreal

    if not hasattr(unreal, "MCAAnimBlueprintLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    abp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if abp is None:
        return {"success": False, "message": "AnimBlueprint not found at '{}'.".format(asset_path)}

    ok = unreal.MCAAnimBlueprintLibrary.add_state_machine(abp, state_machine, connect_to_root)
    return {"success": bool(ok), "asset_path": asset_path, "state_machine": state_machine}
