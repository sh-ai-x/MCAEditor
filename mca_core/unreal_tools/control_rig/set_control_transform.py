def set_control_transform(asset_path: str, control_name: str, location: list = None, rotation: list = None, scale: list = None):
    """Set the initial transform of a Control Rig control.

    Modifies the initial global transform of a control. Only provided
    components are changed — omitted values stay at their current setting.
    The operation is wrapped in an editor transaction for Ctrl+Z undo support.

    :param asset_path: Full content path to the Control Rig (e.g. "/Game/CR_MyRig").
    :param control_name: Name of the control to modify.
    :param location: Optional [X, Y, Z] location values.
    :param rotation: Optional [Pitch, Yaw, Roll] rotation values in degrees.
    :param scale: Optional [X, Y, Z] scale values.
    """
    import unreal

    # Verify Control Rig plugin is available.
    try:
        _test = unreal.ControlRigBlueprint
    except AttributeError:
        return {
            "success": False,
            "message": "Control Rig plugin is not enabled or not available.",
        }

    # Load the Control Rig asset.
    rig_bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if rig_bp is None:
        return {
            "success": False,
            "message": "Control Rig not found at '{}'.".format(asset_path),
        }

    if not isinstance(rig_bp, unreal.ControlRigBlueprint):
        return {
            "success": False,
            "message": "'{}' is not a ControlRigBlueprint.".format(asset_path),
        }

    try:
        hierarchy = rig_bp.hierarchy
        if hierarchy is None:
            return {
                "success": False,
                "message": "Hierarchy is not available.",
            }

        # Find the control key.
        all_keys = hierarchy.get_all_keys()
        target_key = None

        for key in all_keys:
            name = str(hierarchy.get_name(key))
            elem_type = str(hierarchy.get_type(key))
            if name == control_name and "Control" in elem_type:
                target_key = key
                break

        if target_key is None:
            return {
                "success": False,
                "message": "Control '{}' not found in the hierarchy.".format(control_name),
            }

        with unreal.ScopedEditorTransaction("set_control_transform: {}".format(control_name)):

            # Get current initial transform.
            current_tf = hierarchy.get_initial_global_transform(target_key)

            # Update location if provided.
            if location is not None and len(location) == 3:
                current_tf.translation = unreal.Vector(
                    location[0], location[1], location[2]
                )

            # Update rotation if provided.
            if rotation is not None and len(rotation) == 3:
                rot = unreal.Rotator(rotation[0], rotation[1], rotation[2])
                current_tf.rotation = rot.quaternion()

            # Update scale if provided.
            if scale is not None and len(scale) == 3:
                current_tf.scale3d = unreal.Vector(scale[0], scale[1], scale[2])

            # Apply the updated transform.
            hierarchy.set_initial_global_transform(target_key, current_tf)

            # Save the asset.
            unreal.EditorAssetLibrary.save_asset(asset_path)

        return {
            "success": True,
            "control_name": control_name,
            "location": location,
            "rotation": rotation,
            "scale": scale,
        }

    except Exception as e:
        return {
            "success": False,
            "message": "Failed to set transform: {}".format(str(e)),
        }
