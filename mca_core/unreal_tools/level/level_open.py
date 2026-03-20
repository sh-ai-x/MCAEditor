def level_open(level_path: str):
    """Open an existing level in the Unreal Editor.

    :param level_path: Content path to the level (e.g. "/Game/Maps/MyLevel").
    """
    import unreal

    # Load the level via the editor subsystem.
    success = unreal.EditorLevelLibrary.load_level(level_path)

    return {
        "success": success,
        "level_path": level_path,
    }
