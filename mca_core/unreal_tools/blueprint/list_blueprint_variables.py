def list_blueprint_variables(asset_path: str):
    """List all variables defined on a Blueprint with types, defaults, and categories.

    Returns user-defined variables (properties added in the Blueprint editor),
    excluding inherited engine properties.

    :param asset_path: Full content path to the Blueprint (e.g. "/Game/BP_MyActor").
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

    parent_class = gen_class.get_super_class()
    cdo = unreal.get_default_object(gen_class)
    if cdo is None:
        return {
            "success": False,
            "message": "Could not get CDO for '{}'.".format(asset_path),
        }

    # Properties on the parent class (to exclude inherited ones).
    parent_props = set()
    if parent_class:
        parent_cdo = unreal.get_default_object(parent_class)
        if parent_cdo:
            parent_props = set(dir(parent_cdo))

    variables = []
    for prop_name in sorted(dir(cdo)):
        if prop_name.startswith("_"):
            continue
        # Only user-added variables.
        if prop_name in parent_props:
            continue
        try:
            val = cdo.get_editor_property(prop_name)
            variables.append({
                "name": prop_name,
                "type": type(val).__name__ if val is not None else "unknown",
                "default": str(val)[:200] if val is not None else "None",
            })
        except Exception:
            pass

    return {
        "success": True,
        "asset_path": asset_path,
        "total_count": len(variables),
        "variables": variables[:100],
    }
