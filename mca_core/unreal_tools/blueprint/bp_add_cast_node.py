def bp_add_cast_node(asset_path: str, target_class_name: str):
    """Add a dynamic cast node (UK2Node_DynamicCast) to the EventGraph.

    The cast node's TargetType is set to the resolved class. The bridge
    searches loaded UClasses by name (with optional A/U prefix fallback),
    and falls back to searching /Game/ for a Blueprint class with that name.

    Requires the PyUnrealBridge plugin.

    :param asset_path: Full content path to the Blueprint.
    :param target_class_name: Class to cast to (e.g. "Pawn", "WCompanionCharacter").
    """
    import unreal

    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {"success": False, "message": "Blueprint not found at '{}'.".format(asset_path)}

    if not hasattr(unreal, "PyUnrealBlueprintLibrary"):
        return {"success": False, "message": "PyUnrealBridge plugin not enabled."}

    node_id = unreal.PyUnrealBlueprintLibrary.add_cast_node(bp, target_class_name)
    if not node_id:
        return {
            "success": False,
            "message": "Class '{}' not found (tried direct, A-prefix, U-prefix, /Game/ BP).".format(target_class_name),
        }

    return {
        "success": True,
        "asset_path": asset_path,
        "target_class": target_class_name,
        "node_id": node_id,
    }
