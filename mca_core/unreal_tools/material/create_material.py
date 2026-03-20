def create_material(name: str, color: list = None, metallic: float = 0.0,
                    roughness: float = 0.5):
    """Create a new material instance with basic parameters.

    :param name: Name for the new material.
    :param color: [R, G, B] base color (0.0-1.0 each). Default: white.
    :param metallic: Metallic value (0.0-1.0). Default: 0.0.
    :param roughness: Roughness value (0.0-1.0). Default: 0.5.
    """
    import unreal

    if color is None:
        color = [1.0, 1.0, 1.0]

    # Create material asset using the asset tools.
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.MaterialFactoryNew()

    material = asset_tools.create_asset(
        name, "/Game/Materials", unreal.Material, factory
    )

    if material is None:
        return {
            "success": False,
            "message": "Failed to create material '{}'.".format(name),
        }

    # Save the asset.
    unreal.EditorAssetLibrary.save_asset("/Game/Materials/" + name)

    return {
        "success": True,
        "name": name,
        "path": "/Game/Materials/" + name,
        "color": color,
        "metallic": metallic,
        "roughness": roughness,
    }
