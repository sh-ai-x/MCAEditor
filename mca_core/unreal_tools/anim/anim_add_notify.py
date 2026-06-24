# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def anim_add_notify(anim_asset_path: str, notify_name: str, trigger_time: float):
    """Add a named AnimNotify to a sequence at a given time.

    :param anim_asset_path: Content path to the AnimSequence.
    :param notify_name: Name of the notify (e.g. "End_Sit").
    :param trigger_time: Time in seconds along the sequence.
    """
    import unreal

    if not hasattr(unreal, "MCAAnimBlueprintLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    seq = unreal.EditorAssetLibrary.load_asset(anim_asset_path)
    if seq is None:
        return {"success": False, "message": "Animation sequence not found at '{}'.".format(anim_asset_path)}

    ok = unreal.MCAAnimBlueprintLibrary.add_anim_notify(seq, notify_name, trigger_time)
    if ok:
        unreal.EditorAssetLibrary.save_loaded_asset(seq)
    return {"success": bool(ok), "anim": anim_asset_path, "notify": notify_name, "time": trigger_time}
