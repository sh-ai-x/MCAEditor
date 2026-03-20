def level_save():
    """Save the current level in the Unreal Editor."""
    import unreal

    # Save the current level.
    success = unreal.EditorLevelLibrary.save_current_level()

    return {
        "success": success,
    }
