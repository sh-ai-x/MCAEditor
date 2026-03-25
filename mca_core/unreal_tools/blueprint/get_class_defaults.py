def get_class_defaults(asset_path: str, property_filter: str = ""):
    """Get Class Default Object (CDO) property values of a Blueprint.

    Returns the default values for all properties on the Blueprint's
    generated class. These are the values set in the Blueprint editor's
    "Class Defaults" panel.

    :param asset_path: Full content path to the Blueprint (e.g. "/Game/BP_MyActor").
    :param property_filter: Optional substring filter on property names (case-insensitive).
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

    filter_lower = property_filter.lower()
    properties = []

    for prop_name in sorted(dir(cdo)):
        if prop_name.startswith("_"):
            continue

        # Apply filter.
        if filter_lower and filter_lower not in prop_name.lower():
            continue

        try:
            val = cdo.get_editor_property(prop_name)
            properties.append({
                "name": prop_name,
                "type": type(val).__name__ if val is not None else "unknown",
                "value": str(val)[:200] if val is not None else "None",
            })
        except Exception:
            pass

    total_count = len(properties)
    properties = properties[:100]

    return {
        "success": True,
        "asset_path": asset_path,
        "generated_class": gen_class.get_name(),
        "total_count": total_count,
        "properties": properties,
    }
