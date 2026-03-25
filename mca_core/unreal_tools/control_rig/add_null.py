def add_null(asset_path: str, null_name: str, parent_name: str = "", location: list = None, rotation: list = None):
    """Add a null (space/group) to a Control Rig hierarchy.

    Creates a new null element for organizing the rig hierarchy. Nulls
    are commonly used as offset or space-switch parents for controls.
    The operation is wrapped in an editor transaction for Ctrl+Z undo support.

    :param asset_path: Full content path to the Control Rig (e.g. "/Game/CR_MyRig").
    :param null_name: Name for the new null.
    :param parent_name: Optional name of the parent element to attach to.
    :param location: Optional [X, Y, Z] initial location.
    :param rotation: Optional [Pitch, Yaw, Roll] initial rotation in degrees.
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
        controller = rig_bp.get_controller()

        if hierarchy is None or controller is None:
            return {
                "success": False,
                "message": "Hierarchy or controller is not available.",
            }

        # Find parent key if specified.
        parent_key = None
        if parent_name:
            all_keys = hierarchy.get_all_keys()
            for key in all_keys:
                if str(hierarchy.get_name(key)) == parent_name:
                    parent_key = key
                    break
            if parent_key is None:
                return {
                    "success": False,
                    "message": "Parent element '{}' not found.".format(parent_name),
                }

        with unreal.ScopedEditorTransaction("add_null: {}".format(null_name)):

            # Build initial transform.
            init_transform = unreal.Transform()
            if location is not None and len(location) == 3:
                init_transform.translation = unreal.Vector(
                    location[0], location[1], location[2]
                )
            if rotation is not None and len(rotation) == 3:
                rot = unreal.Rotator(rotation[0], rotation[1], rotation[2])
                init_transform.rotation = rot.quaternion()

            # Add the null via the hierarchy controller.
            new_key = controller.add_null(
                null_name,
                parent_key if parent_key else unreal.RigElementKey(),
                init_transform,
            )

            if not new_key:
                return {
                    "success": False,
                    "message": "Failed to add null '{}'.".format(null_name),
                }

            # Save the asset.
            unreal.EditorAssetLibrary.save_asset(asset_path)

        return {
            "success": True,
            "null_name": null_name,
            "parent": parent_name or "root",
        }

    except Exception as e:
        return {
            "success": False,
            "message": "Failed to add null: {}".format(str(e)),
        }
