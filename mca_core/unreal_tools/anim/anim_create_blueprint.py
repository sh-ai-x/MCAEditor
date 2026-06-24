# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def anim_create_blueprint(package_path: str, asset_name: str, skeleton_path: str):
    """Create a new Animation Blueprint targeting a skeleton.

    :param package_path: Content folder for the new asset (e.g. "/Game/Anims").
    :param asset_name: Name for the new AnimBP (e.g. "ABP_MyChar").
    :param skeleton_path: Content path to the target Skeleton asset.
    """
    import unreal

    if not hasattr(unreal, "MCAAnimBlueprintLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    skel = unreal.EditorAssetLibrary.load_asset(skeleton_path)
    if skel is None:
        return {"success": False, "message": "Skeleton not found at '{}'.".format(skeleton_path)}

    abp = unreal.MCAAnimBlueprintLibrary.create_anim_blueprint(package_path, asset_name, skel)
    return {"success": bool(abp), "asset_path": "{}/{}".format(package_path, asset_name)}
