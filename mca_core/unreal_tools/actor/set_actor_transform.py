def set_actor_transform(actor_name: str, location: list = None,
                        rotation: list = None, scale: list = None):
    """Set the transform (location, rotation, scale) of an actor.

    :param actor_name: The display label of the actor.
    :param location: [x, y, z] world location (None = don't change).
    :param rotation: [pitch, yaw, roll] in degrees (None = don't change).
    :param scale: [x, y, z] scale (None = don't change).
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

    # Apply location if provided.
    if location is not None:
        target.set_actor_location(
            unreal.Vector(location[0], location[1], location[2]),
            False, False
        )

    # Apply rotation if provided.
    if rotation is not None:
        target.set_actor_rotation(
            unreal.Rotator(rotation[0], rotation[1], rotation[2]),
            False
        )

    # Apply scale if provided.
    if scale is not None:
        target.set_actor_scale3d(
            unreal.Vector(scale[0], scale[1], scale[2])
        )

    # Read back the final transform.
    loc = target.get_actor_location()
    rot = target.get_actor_rotation()
    sc = target.get_actor_scale3d()

    return {
        "success": True,
        "name": actor_name,
        "location": [loc.x, loc.y, loc.z],
        "rotation": [rot.pitch, rot.yaw, rot.roll],
        "scale": [sc.x, sc.y, sc.z],
    }
