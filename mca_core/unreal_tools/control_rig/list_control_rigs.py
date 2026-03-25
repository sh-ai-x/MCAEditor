def list_control_rigs(path: str = "/Game/", name_filter: str = "", max_results: int = 100):
    """List Control Rig assets under a content path.

    Searches the asset registry for Control Rig Blueprint assets.
    Requires the Control Rig plugin to be enabled.

    :param path: Content path to search (e.g. "/Game/Rigs").
    :param name_filter: Optional substring filter on asset name (case-insensitive).
    :param max_results: Maximum number of results (default 100).
    """
    import unreal

    # Verify Control Rig plugin is available by trying to access the class.
    try:
        _test = unreal.ControlRigBlueprint
    except AttributeError:
        return {
            "success": False,
            "message": "Control Rig plugin is not enabled or not available.",
        }

    # Query the asset registry.
    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()

    ar_filter = unreal.ARFilter()
    ar_filter.package_paths = [path]
    ar_filter.recursive_paths = True
    ar_filter.class_names = ["ControlRigBlueprint"]

    assets = asset_registry.get_assets(ar_filter)

    name_filter_lower = name_filter.lower()
    results = []

    for asset_data in assets:
        asset_name = str(asset_data.asset_name)

        # Apply name filter.
        if name_filter_lower and name_filter_lower not in asset_name.lower():
            continue

        results.append({
            "name": asset_name,
            "path": str(asset_data.package_name),
        })

    total_count = len(results)
    results = results[:max_results]

    return {
        "success": True,
        "path": path,
        "total_count": total_count,
        "control_rigs": results,
    }
