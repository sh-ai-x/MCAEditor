def set_class_default(asset_path: str, property_name: str, value: str):
    """Set a Class Default Object (CDO) property value on a Blueprint.

    Modifies the default value of an existing property in the Blueprint's
    Class Defaults panel. The operation is wrapped in an editor transaction
    for Ctrl+Z undo support.

    :param asset_path: Full content path to the Blueprint (e.g. "/Game/BP_MyActor").
    :param property_name: Name of the property to set.
    :param value: New value as a string. Automatically converted based on the property's current type (bool, int, float, string).
    """
    import unreal

    # Load the Blueprint asset.
    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {
            "success": False,
            "message": "Blueprint not found at '{}'.".format(asset_path),
        }

    gen_class = bp.generated_class()
    if gen_class is None:
        return {
            "success": False,
            "message": "Blueprint '{}' has no generated class.".format(asset_path),
        }

    cdo = unreal.get_default_object(gen_class)
    if cdo is None:
        return {
            "success": False,
            "message": "Could not get CDO for '{}'.".format(asset_path),
        }

    # Verify the property exists and get its current type.
    try:
        current_val = cdo.get_editor_property(property_name)
    except Exception:
        return {
            "success": False,
            "message": "Property '{}' not found on CDO.".format(property_name),
        }

    with unreal.ScopedEditorTransaction("set_class_default: {}={}".format(property_name, value)):

        # Convert the string value to the appropriate type.
        try:
            val_type = type(current_val).__name__

            if val_type == "bool":
                parsed = value.lower() in ("true", "1", "yes")
            elif val_type in ("int", "int32", "int64"):
                parsed = int(value)
            elif val_type in ("float", "double"):
                parsed = float(value)
            elif val_type == "str":
                parsed = value
            elif val_type == "Name":
                parsed = unreal.Name(value)
            elif val_type == "Text":
                parsed = unreal.Text(value)
            else:
                # For complex types (Vector, Rotator, etc.), try direct string.
                parsed = value

            cdo.set_editor_property(property_name, parsed)
        except Exception as e:
            return {
                "success": False,
                "message": "Failed to set '{}': {}".format(property_name, str(e)),
            }

        # Save the asset.
        unreal.EditorAssetLibrary.save_asset(asset_path)

    return {
        "success": True,
        "asset_path": asset_path,
        "property_name": property_name,
        "value": value,
        "previous_value": str(current_val)[:200],
    }
