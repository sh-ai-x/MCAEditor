# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def anim_compile(asset_path: str):
    """Compile an Animation Blueprint and report success.

    :param asset_path: Content path to the Animation Blueprint.
    """
    import unreal

    if not hasattr(unreal, "MCAAnimBlueprintLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    abp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if abp is None:
        return {"success": False, "message": "AnimBlueprint not found at '{}'.".format(asset_path)}

    ok = unreal.MCAAnimBlueprintLibrary.compile_anim_blueprint(abp)
    return {"success": bool(ok), "asset_path": asset_path}
