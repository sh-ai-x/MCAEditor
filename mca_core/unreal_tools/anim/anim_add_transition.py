# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def anim_add_transition(asset_path: str, state_machine: str, from_state: str, to_state: str, crossfade: float = 0.2):
    """Add a transition between two states.

    :param asset_path: Content path to the Animation Blueprint.
    :param state_machine: Name of the state machine.
    :param from_state: Source state name.
    :param to_state: Destination state name.
    :param crossfade: Blend duration in seconds.
    """
    import unreal

    if not hasattr(unreal, "MCAAnimBlueprintLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    abp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if abp is None:
        return {"success": False, "message": "AnimBlueprint not found at '{}'.".format(asset_path)}

    ok = unreal.MCAAnimBlueprintLibrary.add_transition(abp, state_machine, from_state, to_state, crossfade)
    return {"success": bool(ok), "transition": "{} -> {}".format(from_state, to_state)}
