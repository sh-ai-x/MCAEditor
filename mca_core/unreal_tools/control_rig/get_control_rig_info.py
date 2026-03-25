def get_control_rig_info(asset_path: str):
    """Get an overview of a Control Rig asset.

    Returns the rig's controls, bones, nulls, and hierarchy metadata.
    Requires the Control Rig plugin to be enabled.

    :param asset_path: Full content path to the Control Rig (e.g. "/Game/CR_MyRig").
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

    # Verify it's actually a Control Rig Blueprint.
    if not isinstance(rig_bp, unreal.ControlRigBlueprint):
        return {
            "success": False,
            "message": "'{}' is not a ControlRigBlueprint.".format(asset_path),
        }

    info = {
        "success": True,
        "name": rig_bp.get_name(),
        "path": asset_path,
        "controls": [],
        "bones": [],
        "nulls": [],
    }

    try:
        hierarchy = rig_bp.hierarchy
        if hierarchy is None:
            info["message"] = "Hierarchy is not available."
            return info

        # Walk all elements in the hierarchy.
        all_keys = hierarchy.get_all_keys()

        for key in all_keys:
            elem_type = hierarchy.get_type(key)
            name = hierarchy.get_name(key)

            # Get parent.
            parent_key = hierarchy.get_parent(key)
            parent_name = hierarchy.get_name(parent_key) if parent_key else ""

            elem_info = {
                "name": str(name),
                "parent": str(parent_name),
            }

            # Classify by element type.
            type_str = str(elem_type)

            if "Control" in type_str:
                info["controls"].append(elem_info)
            elif "Bone" in type_str:
                info["bones"].append(elem_info)
            elif "Null" in type_str:
                info["nulls"].append(elem_info)

    except Exception as e:
        info["message"] = "Partial read — error accessing hierarchy: {}".format(str(e))

    info["total_controls"] = len(info["controls"])
    info["total_bones"] = len(info["bones"])
    info["total_nulls"] = len(info["nulls"])

    # Cap lists.
    info["controls"] = info["controls"][:100]
    info["bones"] = info["bones"][:100]
    info["nulls"] = info["nulls"][:100]

    return info
