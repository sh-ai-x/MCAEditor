def create_blueprint(asset_name: str, package_path: str = "/Game/", parent_class: str = "Actor"):
    """Create a new Blueprint asset with the specified parent class.

    Creates the Blueprint via the Asset Tools factory, saves it, and returns
    the new asset's path. The operation is wrapped in an editor transaction
    for Ctrl+Z undo support.

    :param asset_name: Name for the new Blueprint (e.g. "BP_MyCharacter").
    :param package_path: Content directory for the asset (default "/Game/").
    :param parent_class: Parent class name (e.g. "Actor", "Character", "Pawn").
    """
    import unreal

    # Resolve the parent class from the unreal module.
    parent_cls = getattr(unreal, parent_class, None)
    if parent_cls is None:
        return {
            "success": False,
            "message": "Parent class '{}' not found in the unreal module.".format(
                parent_class
            ),
        }

    # Check if asset already exists.
    full_path = "{}/{}".format(package_path.rstrip("/"), asset_name)
    if unreal.EditorAssetLibrary.does_asset_exist(full_path):
        return {
            "success": False,
            "message": "Asset already exists at '{}'.".format(full_path),
        }

    # Create the Blueprint inside a transaction for undo support.
    with unreal.ScopedEditorTransaction("create_blueprint: {}".format(asset_name)):
        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()

        # BlueprintFactory handles the creation.
        factory = unreal.BlueprintFactory()
        factory.set_editor_property("parent_class", parent_cls)

        new_bp = asset_tools.create_asset(
            asset_name,
            package_path,
            unreal.Blueprint,
            factory,
        )

        if new_bp is None:
            return {
                "success": False,
                "message": "Failed to create Blueprint '{}'.".format(asset_name),
            }

        # Save the new asset.
        unreal.EditorAssetLibrary.save_asset(full_path)

    return {
        "success": True,
        "name": new_bp.get_name(),
        "path": full_path,
        "parent_class": parent_class,
    }
