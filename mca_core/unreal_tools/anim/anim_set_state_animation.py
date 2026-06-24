# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def anim_set_state_animation(asset_path: str, state_machine: str, state: str, anim_asset_path: str):
    """Set the animation asset played by a state.

    :param asset_path: Content path to the Animation Blueprint.
    :param state_machine: Name of the state machine.
    :param state: Name of the state.
    :param anim_asset_path: Content path to the AnimSequence/BlendSpace.
    """
    import unreal

    if not hasattr(unreal, "MCAAnimBlueprintLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    abp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if abp is None:
        return {"success": False, "message": "AnimBlueprint not found at '{}'.".format(asset_path)}
    seq = unreal.EditorAssetLibrary.load_asset(anim_asset_path)
    if seq is None:
        return {"success": False, "message": "Animation asset not found at '{}'.".format(anim_asset_path)}

    ok = unreal.MCAAnimBlueprintLibrary.set_state_animation(abp, state_machine, state, seq)
    return {"success": bool(ok), "asset_path": asset_path, "state": state, "anim": anim_asset_path}
