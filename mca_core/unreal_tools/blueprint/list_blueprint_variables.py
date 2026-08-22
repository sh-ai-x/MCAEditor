def list_blueprint_variables(asset_path: str):
    """List all variables defined on a Blueprint with types, defaults, and categories.

    Returns user-defined variables (properties added in the Blueprint editor),
    excluding inherited engine properties.

    :param asset_path: Full content path to the Blueprint (e.g. "/Game/BP_MyActor").
    """
    import re
    import unreal

    # In UE 5.6 ``BlueprintGeneratedClass.get_super_class()`` was removed
    # from the Python API. The parent class is still exposed via the
    # AssetRegistry ``ParentClass`` tag, which we parse and load.

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

    # Resolve the parent class via AssetRegistry tag.
    parent_class = None
    try:
        ar = unreal.AssetRegistryHelpers.get_asset_registry()
        ads = ar.get_assets_by_package_name(bp.get_outermost().get_name())
        if ads:
            raw = ads[0].get_tag_value("ParentClass")
            if raw:
                m = re.search(r"'([^']+)'", str(raw))
                if m:
                    parent_class = unreal.load_class(None, m.group(1))
    except Exception:
        parent_class = None

    cdo = unreal.get_default_object(gen_class)
    if cdo is None:
        return {
            "success": False,
            "message": "Could not get CDO for '{}'.".format(asset_path),
        }

    # Build the set of inherited property names so we can exclude them.
    parent_props = set()
    if parent_class is not None:
        try:
            parent_cdo = unreal.get_default_object(parent_class)
            if parent_cdo is not None:
                parent_props = set(dir(parent_cdo))
        except Exception:
            pass

    variables = []
    for prop_name in sorted(dir(cdo)):
        if prop_name.startswith("_"):
            continue
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
        "parent_class_resolved": parent_class.get_name() if parent_class else None,
    }
