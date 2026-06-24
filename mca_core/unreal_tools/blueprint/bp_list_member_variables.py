# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def bp_list_member_variables(asset_path: str):
    """List a Blueprint's member variables as "Name|Type|InstanceEditable".

    Works where the stock list_blueprint_variables returns nothing in 5.8.

    :param asset_path: Content path to the Blueprint.
    """
    import unreal

    if not hasattr(unreal, "MCAEventGraphLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {"success": False, "message": "Blueprint not found at '{}'.".format(asset_path)}

    items = unreal.MCAEventGraphLibrary.list_member_variables(bp)
    return {"success": True, "asset_path": asset_path, "variables": [str(v) for v in items]}
