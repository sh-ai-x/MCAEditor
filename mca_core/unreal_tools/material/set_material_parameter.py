def set_material_parameter(material_path: str, param_name: str, value):
    """Set a parameter on a material instance.

    :param material_path: Content path to the material (e.g. "/Game/Materials/MyMat").
    :param param_name: Parameter name to set.
    :param value: Parameter value (scalar, vector, or texture path).
    """
    import unreal

    # Load the material asset.
    material = unreal.EditorAssetLibrary.load_asset(material_path)

    if material is None:
        return {
            "success": False,
            "message": "Material '{}' not found.".format(material_path),
        }

    # Try to set the parameter based on value type.
    try:
        if isinstance(value, (int, float)):
            material.set_editor_property(param_name, float(value))
        elif isinstance(value, list) and len(value) >= 3:
            color = unreal.LinearColor(value[0], value[1], value[2],
                                       value[3] if len(value) > 3 else 1.0)
            material.set_editor_property(param_name, color)
        else:
            material.set_editor_property(param_name, value)

        # Save the modified material.
        unreal.EditorAssetLibrary.save_asset(material_path)

        return {
            "success": True,
            "material": material_path,
            "parameter": param_name,
            "value": str(value),
        }
    except Exception as e:
        return {
            "success": False,
            "message": "Failed to set parameter '{}': {}".format(param_name, str(e)),
        }
