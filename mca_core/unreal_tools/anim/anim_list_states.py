# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def anim_list_states(asset_path: str, state_machine: str):
    """List the states in a state machine.

    :param asset_path: Content path to the Animation Blueprint.
    :param state_machine: Name of the state machine to inspect.
    """
    import unreal

    if not hasattr(unreal, "MCAAnimBlueprintLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    abp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if abp is None:
        return {"success": False, "message": "AnimBlueprint not found at '{}'.".format(asset_path)}

    names = unreal.MCAAnimBlueprintLibrary.list_states(abp, state_machine)
    return {"success": True, "asset_path": asset_path, "state_machine": state_machine,
            "states": [str(n) for n in names]}
