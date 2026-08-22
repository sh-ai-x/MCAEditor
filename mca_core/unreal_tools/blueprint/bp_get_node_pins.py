def bp_get_node_pins(asset_path: str, node_id: str):
    """List all pins on a node in a Blueprint's EventGraph.

    Returns each visible (non-hidden) pin with its direction (In/Out),
    name, and type. Pin names are the values to pass to the wire/default
    tools.

    Requires the PyUnrealBridge plugin.

    :param asset_path: Full content path to the Blueprint.
    :param node_id: Node GUID returned by bp_add_* or bp_list_event_graph_nodes.
    """
    import unreal

    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {"success": False, "message": "Blueprint not found at '{}'.".format(asset_path)}

    if not hasattr(unreal, "PyUnrealBlueprintLibrary"):
        return {"success": False, "message": "PyUnrealBridge plugin not enabled."}

    rows = unreal.PyUnrealBlueprintLibrary.get_node_pins(bp, node_id)

    pins = []
    for row in rows:
        # Format from C++: Direction:PinName:PinType
        parts = row.split(":", 2)
        if len(parts) == 3:
            pins.append({"direction": parts[0], "name": parts[1], "type": parts[2]})

    return {
        "success": True,
        "asset_path": asset_path,
        "node_id": node_id,
        "total_count": len(pins),
        "pins": pins,
    }
