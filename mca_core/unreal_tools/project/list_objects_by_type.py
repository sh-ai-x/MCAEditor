def list_objects_by_type(type_name: str):
    """List all actors of a specific type in the current level.

    :param type_name: UClass name to filter by (e.g. "StaticMeshActor", "PointLight").
    """
    import unreal

    # Get all actors in the level.
    all_actors = unreal.EditorLevelLibrary.get_all_level_actors()

    matching = []
    for actor in all_actors:
        class_name = actor.get_class().get_name()
        if class_name == type_name:
            loc = actor.get_actor_location()
            matching.append({
                "name": actor.get_actor_label(),
                "class": class_name,
                "location": [loc.x, loc.y, loc.z],
            })

    return {
        "success": True,
        "type": type_name,
        "count": len(matching),
        "actors": matching,
    }
