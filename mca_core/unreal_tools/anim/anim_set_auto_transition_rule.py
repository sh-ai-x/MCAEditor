# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def anim_set_auto_transition_rule(asset_path: str, state_machine: str, from_state: str, to_state: str, trigger_time: float = 0.0):
    """Make a transition fire automatically on remaining animation time.

    :param asset_path: Content path to the Animation Blueprint.
    :param state_machine: Name of the state machine.
    :param from_state: Source state name.
    :param to_state: Destination state name.
    :param trigger_time: Seconds remaining at which to trigger.
    """
    import unreal

    if not hasattr(unreal, "MCAAnimBlueprintLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    abp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if abp is None:
        return {"success": False, "message": "AnimBlueprint not found at '{}'.".format(asset_path)}

    ok = unreal.MCAAnimBlueprintLibrary.set_auto_transition_rule(abp, state_machine, from_state, to_state, trigger_time)
    return {"success": bool(ok), "transition": "{} -> {}".format(from_state, to_state), "trigger_time": trigger_time}
