def get_level_info():
    """Get information about the currently loaded level.

    Returns level name, path, actor count, and world settings.
    """
    import unreal

    # Get the current world.
    world = unreal.EditorLevelLibrary.get_editor_world()

    # Get all actors in the level.
    actors = unreal.EditorLevelLibrary.get_all_level_actors()

    # Get world settings.
    level_name = world.get_name() if world else "Unknown"

    # Count actors by class.
    actor_classes = {}
    for actor in actors:
        class_name = actor.get_class().get_name()
        actor_classes[class_name] = actor_classes.get(class_name, 0) + 1

    return {
        "success": True,
        "level_name": level_name,
        "actor_count": len(actors),
        "actor_classes": actor_classes,
    }
