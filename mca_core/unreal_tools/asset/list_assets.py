def list_assets(path: str = "/Game/", type_filter: str = None):
    """List assets in the Content Browser by path and optional type filter.

    :param path: Content path to search (e.g. "/Game/Textures").
    :param type_filter: Optional UClass name filter (e.g. "StaticMesh", "Texture2D").
    """
    import unreal

    # Get the asset registry.
    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()

    # Build the filter.
    ar_filter = unreal.ARFilter()
    ar_filter.package_paths = [path]
    ar_filter.recursive_paths = True

    if type_filter:
        ar_filter.class_names = [type_filter]

    # Query assets.
    assets = asset_registry.get_assets(ar_filter)

    result_list = []
    for asset_data in assets:
        result_list.append({
            "name": str(asset_data.asset_name),
            "class": str(asset_data.asset_class_path.asset_name),
            "path": str(asset_data.package_name),
        })

    return {
        "success": True,
        "count": len(result_list),
        "assets": result_list,
    }
