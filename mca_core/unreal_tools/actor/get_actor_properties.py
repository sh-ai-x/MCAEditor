def get_actor_properties(actor_name: str):
    """Get transform and properties of an actor by label.

    :param actor_name: The display label of the actor.
    """
    import unreal

    # Find the actor by label.
    all_actors = unreal.EditorLevelLibrary.get_all_level_actors()
    target = None
    for actor in all_actors:
        if actor.get_actor_label() == actor_name:
            target = actor
            break

    if target is None:
        return {
            "success": False,
            "message": "Actor '{}' not found.".format(actor_name),
        }

    loc = target.get_actor_location()
    rot = target.get_actor_rotation()
    scale = target.get_actor_scale3d()

    return {
        "success": True,
        "name": target.get_actor_label(),
        "class": target.get_class().get_name(),
        "location": [loc.x, loc.y, loc.z],
        "rotation": [rot.pitch, rot.yaw, rot.roll],
        "scale": [scale.x, scale.y, scale.z],
        "is_hidden": target.is_hidden_ed(),
    }
