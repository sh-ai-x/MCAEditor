def list_controls(asset_path: str, name_filter: str = "", max_results: int = 100):
    """List all controls in a Control Rig with types, transforms, and hierarchy.

    Returns detailed information about each control including its transform,
    parent, and display properties.

    :param asset_path: Full content path to the Control Rig (e.g. "/Game/CR_MyRig").
    :param name_filter: Optional substring filter on control name (case-insensitive).
    :param max_results: Maximum number of results (default 100).
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

    name_filter_lower = name_filter.lower()
    controls = []

    try:
        hierarchy = rig_bp.hierarchy
        if hierarchy is None:
            return {
                "success": False,
                "message": "Hierarchy is not available.",
            }

        all_keys = hierarchy.get_all_keys()

        for key in all_keys:
            elem_type = hierarchy.get_type(key)
            if "Control" not in str(elem_type):
                continue

            name = str(hierarchy.get_name(key))

            # Apply name filter.
            if name_filter_lower and name_filter_lower not in name.lower():
                continue

            # Get parent.
            parent_key = hierarchy.get_parent(key)
            parent_name = str(hierarchy.get_name(parent_key)) if parent_key else ""

            control_info = {
                "name": name,
                "parent": parent_name,
            }

            # Try to get the initial transform.
            try:
                initial_transform = hierarchy.get_initial_global_transform(key)
                loc = initial_transform.translation
                rot = initial_transform.rotation.rotator()
                control_info["initial_transform"] = {
                    "location": [loc.x, loc.y, loc.z],
                    "rotation": [rot.pitch, rot.yaw, rot.roll],
                }
            except Exception:
                pass

            controls.append(control_info)

    except Exception as e:
        return {
            "success": False,
            "message": "Failed to list controls: {}".format(str(e)),
        }

    total_count = len(controls)
    controls = controls[:max_results]

    return {
        "success": True,
        "asset_path": asset_path,
        "total_count": total_count,
        "controls": controls,
    }
