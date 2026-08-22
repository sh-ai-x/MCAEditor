def bp_list_event_graph_nodes(asset_path: str):
    """List nodes in a Blueprint's EventGraph (UbergraphPages[0]).

    Returns each node's stable ID (GUID string), class name, and display
    title. Node IDs are required by the wire/edit tools.

    Requires the PyUnrealBridge plugin — UE 5.6 marks EdGraph.Nodes as
    protected, so node enumeration is impossible from Python alone.

    :param asset_path: Full content path to the Blueprint.
    """
    import unreal

    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {"success": False, "message": "Blueprint not found at '{}'.".format(asset_path)}

    if not hasattr(unreal, "PyUnrealBlueprintLibrary"):
        return {"success": False, "message": "PyUnrealBridge plugin not enabled — install/enable it to use this tool."}

    rows = unreal.PyUnrealBlueprintLibrary.list_event_graph_nodes(bp)

    nodes = []
    for row in rows:
        # Format from C++: NodeId:ClassName:Title — first colon is delimiter,
        # but title may contain colons, so split only on the first two.
        parts = row.split(":", 2)
        if len(parts) == 3:
            nodes.append({"id": parts[0], "class": parts[1], "title": parts[2]})

    return {
        "success": True,
        "asset_path": asset_path,
        "total_count": len(nodes),
        "nodes": nodes,
    }
