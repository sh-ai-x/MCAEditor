def get_asset_info(asset_path: str):
    """Get metadata and info about an asset by content path.

    :param asset_path: Content path to the asset (e.g. "/Game/Meshes/MyCube").
    """
    import unreal

    # Load the asset data.
    asset_data = unreal.EditorAssetLibrary.find_asset_data(asset_path)

    if not asset_data.is_valid():
        return {
            "success": False,
            "message": "Asset '{}' not found.".format(asset_path),
        }

    return {
        "success": True,
        "name": str(asset_data.asset_name),
        "class": str(asset_data.asset_class_path.asset_name),
        "path": str(asset_data.package_name),
        "is_valid": asset_data.is_valid(),
    }
