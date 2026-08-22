def bp_add_variable_set_node(asset_path: str, variable_name: str):
    """Add a Variable SET node to the EventGraph (writes a Blueprint variable).

    The variable reference is set as a self-member, so the SET node writes
    to the Blueprint's own class.

    Requires the PyUnrealBridge plugin.

    :param asset_path: Full content path to the Blueprint.
    :param variable_name: Name of an existing Blueprint variable.
    """
    import unreal

    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {"success": False, "message": "Blueprint not found at '{}'.".format(asset_path)}

    if not hasattr(unreal, "PyUnrealBlueprintLibrary"):
        return {"success": False, "message": "PyUnrealBridge plugin not enabled."}

    node_id = unreal.PyUnrealBlueprintLibrary.add_variable_set_node(bp, variable_name)
    if not node_id:
        return {"success": False, "message": "Failed to add Variable Set for '{}'.".format(variable_name)}

    return {
        "success": True,
        "asset_path": asset_path,
        "variable": variable_name,
        "node_id": node_id,
    }
