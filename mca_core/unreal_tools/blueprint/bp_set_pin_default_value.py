def bp_set_pin_default_value(asset_path: str, node_id: str, pin_name: str, value: str):
    """Set a pin's default literal value (string, bool, int, float, name, enum).

    Use this for non-object pin defaults like strings, numbers, booleans,
    and enum literals. For asset/object references, use bp_set_pin_default_object.

    The Blueprint schema validates the value's type compatibility and
    rejects malformed values (returns success=False with the schema error).

    Examples:
      - Bool pin: value="true" or "false"
      - Int pin: value="5"
      - Float pin: value="0.5"
      - String pin: value="hello"
      - Enum pin: value="EMyEnum::Option1"

    Requires the PyUnrealBridge plugin.

    :param asset_path: Full content path to the Blueprint.
    :param node_id: Node GUID containing the pin.
    :param pin_name: Pin name (see bp_get_node_pins).
    :param value: New value as a string.
    """
    import unreal

    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {"success": False, "message": "Blueprint not found at '{}'.".format(asset_path)}

    if not hasattr(unreal, "PyUnrealBlueprintLibrary"):
        return {"success": False, "message": "PyUnrealBridge plugin not enabled."}

    ok = unreal.PyUnrealBlueprintLibrary.set_pin_default_value(bp, node_id, pin_name, value)

    return {
        "success": bool(ok),
        "asset_path": asset_path,
        "pin": "{}.{}".format(node_id[:8], pin_name),
        "value": value,
        "message": "Set." if ok else "Schema rejected the value — check pin type via bp_get_node_pins.",
    }
