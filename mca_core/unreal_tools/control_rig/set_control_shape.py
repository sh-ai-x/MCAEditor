def set_control_shape(asset_path: str, control_name: str, shape_name: str = "", color: list = None):
    """Set the visual shape and color of a Control Rig control.

    Modifies the control's gizmo/shape settings for viewport display.
    The operation is wrapped in an editor transaction for Ctrl+Z undo support.

    :param asset_path: Full content path to the Control Rig (e.g. "/Game/CR_MyRig").
    :param control_name: Name of the control to modify.
    :param shape_name: Optional shape name (e.g. "Default", "Circle_Thin", "Square").
    :param color: Optional [R, G, B] color values (0.0-1.0 range) or [R, G, B, A].
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

        with unreal.ScopedEditorTransaction("set_control_shape: {}".format(control_name)):

            # Get current control settings.
            settings = hierarchy.get_control_settings(target_key)

            # Update shape name if provided.
            if shape_name:
                try:
                    settings.shape_name = shape_name
                except Exception:
                    pass

            # Update color if provided.
            if color is not None and len(color) >= 3:
                r, g, b = color[0], color[1], color[2]
                a = color[3] if len(color) > 3 else 1.0
                try:
                    settings.shape_color = unreal.LinearColor(r, g, b, a)
                except Exception:
                    pass

            # Apply updated settings.
            hierarchy.set_control_settings(target_key, settings)

            # Save the asset.
            unreal.EditorAssetLibrary.save_asset(asset_path)

        return {
            "success": True,
            "control_name": control_name,
            "shape_name": shape_name or "(unchanged)",
            "color": color,
        }

    except Exception as e:
        return {
            "success": False,
            "message": "Failed to set control shape: {}".format(str(e)),
        }
