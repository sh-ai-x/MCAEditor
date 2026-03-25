def list_blueprints(path: str = "/Game/", type_filter: str = "", name_filter: str = "", max_results: int = 100):
    """List Blueprint assets under a content path.

    Searches the asset registry for Blueprint assets, with optional
    filtering by parent class and name substring.

    :param path: Content path to search (e.g. "/Game/Blueprints").
    :param type_filter: Optional parent class name filter (e.g. "Character", "Actor").
    :param name_filter: Optional substring filter on asset name (case-insensitive).
    :param max_results: Maximum number of results (default 100).
    """
    import unreal

    # Query the asset registry for Blueprint assets.
    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()

    ar_filter = unreal.ARFilter()
    ar_filter.package_paths = [path]
    ar_filter.recursive_paths = True
    ar_filter.class_names = ["Blueprint"]

    assets = asset_registry.get_assets(ar_filter)

    name_filter_lower = name_filter.lower()
    results = []

    for asset_data in assets:
        asset_name = str(asset_data.asset_name)

        # Apply name filter.
        if name_filter_lower and name_filter_lower not in asset_name.lower():
            continue

        # Optionally filter by parent class.
        if type_filter:
            # Load the asset to check parent class.
            bp = unreal.EditorAssetLibrary.load_asset(str(asset_data.package_name))
            if bp is None:
                continue
            gen_class = bp.generated_class()
            if gen_class is None:
                continue
            # Walk parent chain looking for the type_filter.
            parent = gen_class.get_super_class()
            matched = False
            while parent is not None:
                if parent.get_name() == type_filter:
                    matched = True
                    break
                parent = parent.get_super_class()
            if not matched:
                continue

        results.append({
            "name": asset_name,
            "path": str(asset_data.package_name),
            "class": str(asset_data.asset_class_path.asset_name),
        })

    total_count = len(results)
    results = results[:max_results]

    return {
        "success": True,
        "path": path,
        "total_count": total_count,
        "blueprints": results,
    }
