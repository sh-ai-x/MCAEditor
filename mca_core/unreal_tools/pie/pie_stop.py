# MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def pie_stop():
    """End the current Play-In-Editor / Simulate session.

    Safe to call when nothing is playing — it reports ``was_playing: False``.
    PIE tears down on the next editor tick after the request.
    """
    import unreal

    level_editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)

    was_playing = level_editor.is_in_play_in_editor()
    if was_playing:
        level_editor.editor_request_end_play()

    return {"success": True, "was_playing": bool(was_playing), "requested": bool(was_playing)}
