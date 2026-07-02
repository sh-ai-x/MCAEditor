# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def bp_break_pin_links(asset_path: str, node_id: str, pin_name: str):
    """Break ALL links on one pin of an EventGraph node — counterpart to bp_connect_pins.

    Disconnects the pin exactly like alt-clicking it in the Blueprint editor
    (both endpoints get notified). Use before splicing a replacement wire when
    rerouting an existing graph.

    :param asset_path: Content path to the Blueprint.
    :param node_id: Node GUID string owning the pin.
    :param pin_name: Pin to disconnect (see bp_get_node_pins).
    """
    import unreal

    if not hasattr(unreal, "MCAEventGraphLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    if not hasattr(unreal.MCAEventGraphLibrary, "break_pin_links"):
        return {"success": False, "message": "MCAEditorScripting plugin too old — rebuild for break_pin_links."}
    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {"success": False, "message": "Blueprint not found at '{}'.".format(asset_path)}

    ok = unreal.MCAEventGraphLibrary.break_pin_links(bp, node_id, pin_name)
    return {"success": bool(ok), "asset_path": asset_path, "node_id": node_id, "pin": pin_name}
