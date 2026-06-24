# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def anim_set_transition_bool_condition(asset_path: str, state_machine: str, from_state: str, to_state: str, bool_variable: str, equals_value: bool):
    """Set a bool-variable condition on a transition (e.g. IsSitting == False).

    The variable must already exist on the Animation Blueprint.

    :param asset_path: Content path to the Animation Blueprint.
    :param state_machine: Name of the state machine.
    :param from_state: Source state name.
    :param to_state: Destination state name.
    :param bool_variable: Name of the bool variable on the AnimBP.
    :param equals_value: Value the variable must equal for the transition to fire.
    """
    import unreal

    if not hasattr(unreal, "MCAAnimBlueprintLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    abp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if abp is None:
        return {"success": False, "message": "AnimBlueprint not found at '{}'.".format(asset_path)}

    ok = unreal.MCAAnimBlueprintLibrary.set_transition_bool_condition(
        abp, state_machine, from_state, to_state, bool_variable, equals_value)
    return {"success": bool(ok), "transition": "{} -> {}".format(from_state, to_state),
            "condition": "{} == {}".format(bool_variable, equals_value)}
