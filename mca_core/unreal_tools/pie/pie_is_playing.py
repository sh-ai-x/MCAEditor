# MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def pie_is_playing():
    """Report whether a Play-In-Editor / Simulate session is currently active.

    Use this to poll after ``pie_play`` (PIE starts a tick later) or after
    ``pie_stop`` before capturing or driving the world.
    """
    import unreal

    level_editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    playing = bool(level_editor.is_in_play_in_editor())

    return {"success": True, "is_playing": playing}
