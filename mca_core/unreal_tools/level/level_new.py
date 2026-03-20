def level_new(level_name: str = "NewMap"):
    """Create a new empty level in the Unreal Editor.

    :param level_name: Name for the new level (default: "NewMap").
    """
    import unreal

    # Create a new level using the editor level library.
    success = unreal.EditorLevelLibrary.new_level("/Game/" + level_name)

    return {
        "success": success,
        "level_name": level_name,
        "level_path": "/Game/" + level_name,
    }
