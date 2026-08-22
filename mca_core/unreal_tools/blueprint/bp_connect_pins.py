def bp_connect_pins(asset_path: str, source_node_id: str, source_pin: str,
                    target_node_id: str, target_pin: str):
    """Wire two pins in a Blueprint's EventGraph.

    Connects an output pin on the source node to an input pin on the
    target node. The schema validates type compatibility — exec-to-exec,
    matching data types, etc. — and rejects incompatible connections.

    Standard pin names:
      - Exec out: "then" (most nodes) or "execute" (function calls)
      - Exec in: "execute"
      - Function call return: "ReturnValue"
      - Function call target: "self"

    Requires the PyUnrealBridge plugin.

    :param asset_path: Full content path to the Blueprint.
    :param source_node_id: Node GUID of the source (upstream) node.
    :param source_pin: Output pin name on the source node.
    :param target_node_id: Node GUID of the target (downstream) node.
    :param target_pin: Input pin name on the target node.
    """
    import unreal

    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {"success": False, "message": "Blueprint not found at '{}'.".format(asset_path)}

    if not hasattr(unreal, "PyUnrealBlueprintLibrary"):
        return {"success": False, "message": "PyUnrealBridge plugin not enabled."}

    ok = unreal.PyUnrealBlueprintLibrary.connect_pins(
        bp, source_node_id, source_pin, target_node_id, target_pin
    )

    return {
        "success": bool(ok),
        "asset_path": asset_path,
        "connection": "{}.{} -> {}.{}".format(
            source_node_id[:8], source_pin, target_node_id[:8], target_pin
        ),
        "message": "Connected." if ok else "Schema rejected the connection — check pin names and types via bp_get_node_pins.",
    }
