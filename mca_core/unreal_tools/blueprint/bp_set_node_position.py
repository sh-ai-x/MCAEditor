def bp_set_node_position(asset_path: str, node_id: str, x: int, y: int):
    """Move a node to (x, y) in graph editor coordinates.

    Useful when building a graph programmatically to keep the layout
    readable for designers opening it later.

    Requires the PyUnrealBridge plugin.

    :param asset_path: Full content path to the Blueprint.
    :param node_id: Node GUID to move.
    :param x: X position (graph units).
    :param y: Y position (graph units).
    """
    import unreal

    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {"success": False, "message": "Blueprint not found at '{}'.".format(asset_path)}

    if not hasattr(unreal, "PyUnrealBlueprintLibrary"):
        return {"success": False, "message": "PyUnrealBridge plugin not enabled."}

    ok = unreal.PyUnrealBlueprintLibrary.set_node_position(bp, node_id, x, y)

    return {
        "success": bool(ok),
        "asset_path": asset_path,
        "node_id": node_id,
        "position": [x, y],
    }
