# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def bp_list_named_graphs(asset_path: str):
    """List every graph on a Blueprint as "Name|Kind" (Ubergraph/Function).

    The companion to the graph_name parameter on the bp_* node tools: discover
    which function graphs exist (e.g. interface implementation stubs) before
    editing inside them.

    :param asset_path: Content path to the Blueprint.
    """
    import unreal

    if not hasattr(unreal, "MCAEventGraphLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    if not hasattr(unreal.MCAEventGraphLibrary, "list_named_graphs"):
        return {"success": False, "message": "MCAEditorScripting plugin too old — rebuild for list_named_graphs."}
    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {"success": False, "message": "Blueprint not found at '{}'.".format(asset_path)}

    graphs = unreal.MCAEventGraphLibrary.list_named_graphs(bp)
    return {"success": True, "graphs": [str(g) for g in graphs]}
