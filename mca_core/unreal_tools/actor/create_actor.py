def create_actor(actor_class: str, name: str = None, location: list = None,
                  rotation: list = None, scale: list = None):
    """Create an actor in the current Unreal level.

    Actor classes available: StaticMeshActor, PointLight, SpotLight,
    DirectionalLight, CameraActor, PlayerStart, etc.

    :param actor_class: The UClass name to spawn (e.g. "StaticMeshActor").
    :param name: Optional display label for the actor.
    :param location: [x, y, z] world location (default: origin).
    :param rotation: [pitch, yaw, roll] rotation in degrees (default: zero).
    :param scale: [x, y, z] scale (default: [1, 1, 1]).
    """
    import unreal

    if location is None:
        location = [0.0, 0.0, 0.0]
    if rotation is None:
        rotation = [0.0, 0.0, 0.0]
    if scale is None:
        scale = [1.0, 1.0, 1.0]

    # Build location and rotation from the provided arrays.
    actor_loc = unreal.Vector(location[0], location[1], location[2])
    actor_rot = unreal.Rotator(rotation[0], rotation[1], rotation[2])

    # Spawn the actor using the editor level library.
    spawned = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.EditorAssetLibrary.load_asset("/Script/Engine." + actor_class),
        actor_loc,
        actor_rot
    )

    # Set the display label if provided.
    if name and spawned:
        spawned.set_actor_label(name)

    # Set scale if non-default.
    if spawned and scale != [1.0, 1.0, 1.0]:
        spawned.set_actor_scale3d(unreal.Vector(scale[0], scale[1], scale[2]))

    return {
        "success": spawned is not None,
        "name": spawned.get_actor_label() if spawned else None,
        "class": actor_class,
        "location": location,
        "rotation": rotation,
        "scale": scale,
    }
