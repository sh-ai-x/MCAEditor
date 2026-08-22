def bp_set_pin_default_object(asset_path: str, node_id: str, pin_name: str, object_path: str):
    """Set a pin's default to an asset/object reference.

    Use this for asset inputs: Level Sequence, Sound, Material, Texture,
    Static Mesh, Skeletal Mesh, Anim Sequence, Data Table, etc. The
    referenced asset is loaded from object_path and bound to the pin.

    For non-object pin types (strings/numbers/bools), use
    bp_set_pin_default_value.

    Requires the PyUnrealBridge plugin.

    :param asset_path: Full content path to the Blueprint.
    :param node_id: Node GUID containing the pin.
    :param pin_name: Pin name (see bp_get_node_pins).
    :param object_path: Content path to the asset to bind (e.g.
        "/Game/Wayward/Levels/Adventures/Sequences/FamilarsOpen").
    """
    import unreal

    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {"success": False, "message": "Blueprint not found at '{}'.".format(asset_path)}

    if not hasattr(unreal, "PyUnrealBlueprintLibrary"):
        return {"success": False, "message": "PyUnrealBridge plugin not enabled."}

    target = unreal.EditorAssetLibrary.load_asset(object_path)
    if target is None:
        return {"success": False, "message": "Asset not found at '{}'.".format(object_path)}

    ok = unreal.PyUnrealBlueprintLibrary.set_pin_default_object(bp, node_id, pin_name, target)

    return {
        "success": bool(ok),
        "asset_path": asset_path,
        "pin": "{}.{}".format(node_id[:8], pin_name),
        "object": object_path,
        "message": "Set." if ok else "Schema rejected the object — wrong type? Check the pin's expected class via bp_get_node_pins.",
    }
