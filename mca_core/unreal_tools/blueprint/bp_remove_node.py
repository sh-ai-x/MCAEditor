# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def bp_remove_node(asset_path: str, node_id: str):
    """Remove a node from a Blueprint's EventGraph — counterpart to the bp_add_* tools.

    Deletes the node by its GUID (from bp_list_event_graph_nodes / bp_add_*) and
    breaks all of its pin links safely. Needed for refactors that RETIRE logic,
    not just add it (e.g. moving a PlayAnimMontage off a character onto a waypoint).

    :param asset_path: Content path to the Blueprint.
    :param node_id: Node GUID string of the node to delete.
    """
    import unreal

    if not hasattr(unreal, "MCAEventGraphLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    if not hasattr(unreal.MCAEventGraphLibrary, "remove_node"):
        return {"success": False, "message": "MCAEditorScripting plugin too old — rebuild for remove_node."}
    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {"success": False, "message": "Blueprint not found at '{}'.".format(asset_path)}

    ok = unreal.MCAEventGraphLibrary.remove_node(bp, node_id)
    return {"success": bool(ok), "asset_path": asset_path, "node_id": node_id}
