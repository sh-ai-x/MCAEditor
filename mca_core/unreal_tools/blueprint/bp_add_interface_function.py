# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def bp_add_interface_function(asset_path: str, function_name: str, pins: list = None):
    """Add a function signature to a Blueprint Interface asset.

    Each pins entry is "Name|TypeSpec|in" or "Name|TypeSpec|out"; TypeSpec is
    bool/int/float/string/name, "object:<Class>", or "enum:<UserEnumPath>".
    Functions with no out-pins are implementable as EVENTS by implementers;
    output-bearing ones become function-graph overrides.

    :param asset_path: Content path to the interface Blueprint.
    :param function_name: Name of the new function.
    :param pins: Pin specs, e.g. ["NewTarget|name|in", "ReturnValue|bool|out"].
    """
    import unreal

    if not hasattr(unreal, "MCAEventGraphLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    if not hasattr(unreal.MCAEventGraphLibrary, "add_interface_function"):
        return {"success": False, "message": "MCAEditorScripting plugin too old — rebuild for add_interface_function."}
    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {"success": False, "message": "Blueprint not found at '{}'.".format(asset_path)}

    ok = unreal.MCAEventGraphLibrary.add_interface_function(bp, function_name, pins or [])
    return {"success": bool(ok), "asset_path": asset_path, "function": function_name, "pins": pins or []}
