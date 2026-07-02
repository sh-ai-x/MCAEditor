# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def bp_add_self_node(asset_path: str, graph_name: str = ""):
    """Add a "Get a reference to self" node (UK2Node_Self) to a Blueprint graph.

    Needed whenever a graph passes ITSELF as a data value (e.g. a waypoint
    handing the arriving character a reference back to itself).

    :param asset_path: Content path to the Blueprint to modify.
    :param graph_name: Target graph; empty = the main EventGraph.
    """
    import unreal

    if not hasattr(unreal, "MCAEventGraphLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    if not hasattr(unreal.MCAEventGraphLibrary, "add_self_node"):
        return {"success": False, "message": "MCAEditorScripting plugin too old — rebuild for add_self_node."}
    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {"success": False, "message": "Blueprint not found at '{}'.".format(asset_path)}

    node_id = unreal.MCAEventGraphLibrary.add_self_node(bp, graph_name)
    return {"success": bool(node_id), "node_id": str(node_id)}
