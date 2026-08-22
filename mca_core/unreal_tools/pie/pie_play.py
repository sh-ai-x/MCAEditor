# MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def pie_play(simulate: bool = False):
    """Start a Play-In-Editor session (or Simulate).

    PIE begins on the next editor tick, so ``is_in_play_in_editor`` will not
    report True until a subsequent call — this returns as soon as the request
    is issued.

    :param simulate: If True, start Simulate (no player possession) instead of
        full Play. Simulate is the right mode for watching AI-driven pawns
        without a player camera taking over the viewport.
    """
    import unreal

    level_editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)

    if level_editor.is_in_play_in_editor():
        return {"success": True, "already_playing": True, "mode": "unchanged"}

    if simulate:
        level_editor.editor_play_simulate()
        mode = "simulate"
    else:
        level_editor.editor_request_begin_play()
        mode = "play"

    return {"success": True, "requested": True, "mode": mode}
