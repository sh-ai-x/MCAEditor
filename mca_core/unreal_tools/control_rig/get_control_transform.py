def get_control_transform(asset_path: str, control_name: str):
    """Get the initial/local/global transform of a specific Control Rig control.

    Returns the initial global transform of the named control. Useful for
    reading rig setup values before making modifications.

    :param asset_path: Full content path to the Control Rig (e.g. "/Game/CR_MyRig").
    :param control_name: Name of the control to inspect.
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

        # Find the control key by name.
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

        # Get parent info.
        parent_key = hierarchy.get_parent(target_key)
        parent_name = str(hierarchy.get_name(parent_key)) if parent_key else ""

        result = {
            "success": True,
            "control_name": control_name,
            "parent": parent_name,
        }

        # Get initial global transform.
        try:
            global_tf = hierarchy.get_initial_global_transform(target_key)
            loc = global_tf.translation
            rot = global_tf.rotation.rotator()
            scale = global_tf.scale3d
            result["initial_global"] = {
                "location": [loc.x, loc.y, loc.z],
                "rotation": [rot.pitch, rot.yaw, rot.roll],
                "scale": [scale.x, scale.y, scale.z],
            }
        except Exception:
            pass

        # Get initial local transform.
        try:
            local_tf = hierarchy.get_initial_local_transform(target_key)
            loc = local_tf.translation
            rot = local_tf.rotation.rotator()
            scale = local_tf.scale3d
            result["initial_local"] = {
                "location": [loc.x, loc.y, loc.z],
                "rotation": [rot.pitch, rot.yaw, rot.roll],
                "scale": [scale.x, scale.y, scale.z],
            }
        except Exception:
            pass

        return result

    except Exception as e:
        return {
            "success": False,
            "message": "Failed to get control transform: {}".format(str(e)),
        }
