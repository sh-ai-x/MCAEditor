# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def anim_list_transitions(asset_path: str, state_machine: str):
    """List transitions in a state machine as "From -> To" strings.

    :param asset_path: Content path to the Animation Blueprint.
    :param state_machine: Name of the state machine to inspect.
    """
    import unreal

    if not hasattr(unreal, "MCAAnimBlueprintLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    abp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if abp is None:
        return {"success": False, "message": "AnimBlueprint not found at '{}'.".format(asset_path)}

    items = unreal.MCAAnimBlueprintLibrary.list_transitions(abp, state_machine)
    return {"success": True, "asset_path": asset_path, "state_machine": state_machine,
            "transitions": [str(t) for t in items]}
