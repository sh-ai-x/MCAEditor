def get_selected_actors():
    """Get the currently selected actors in the editor."""
    import unreal

    selected = unreal.EditorLevelLibrary.get_selected_level_actors()

    actors = []
    for actor in selected:
        loc = actor.get_actor_location()
        rot = actor.get_actor_rotation()
        scale = actor.get_actor_scale3d()

        actors.append({
            "name": actor.get_actor_label(),
            "class": actor.get_class().get_name(),
            "location": [loc.x, loc.y, loc.z],
            "rotation": [rot.pitch, rot.yaw, rot.roll],
            "scale": [scale.x, scale.y, scale.z],
        })

    return {
        "success": True,
        "count": len(actors),
        "actors": actors,
    }
