def set_viewport_camera(location: list = None, rotation: list = None):
    """Set the editor viewport camera position and rotation.

    :param location: [x, y, z] world location.
    :param rotation: [pitch, yaw, roll] in degrees.
    """
    import unreal

    if location is None:
        location = [0.0, 0.0, 200.0]
    if rotation is None:
        rotation = [-30.0, 0.0, 0.0]

    # Get the level editor subsystem to manipulate the viewport.
    subsystem = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)

    # Set viewport camera via the active viewport.
    loc = unreal.Vector(location[0], location[1], location[2])
    rot = unreal.Rotator(rotation[0], rotation[1], rotation[2])

    if subsystem:
        subsystem.set_level_viewport_camera_info(loc, rot)

    return {
        "success": True,
        "location": location,
        "rotation": rotation,
    }
