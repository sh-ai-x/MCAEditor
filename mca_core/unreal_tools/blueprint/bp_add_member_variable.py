# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def bp_add_member_variable(asset_path: str, variable_name: str, pin_category: str = "bool", instance_editable: bool = True):
    """Add a member variable to a Blueprint (e.g. IsSitting bool on a pawn).

    :param asset_path: Content path to the Blueprint.
    :param variable_name: Name of the new variable.
    :param pin_category: One of bool/int/float/string/name, or "object:<Class>" for object refs (e.g. "object:AnimMontage").
    :param instance_editable: Whether it is editable per-instance.
    """
    import unreal

    if not hasattr(unreal, "MCAEventGraphLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {"success": False, "message": "Blueprint not found at '{}'.".format(asset_path)}

    ok = unreal.MCAEventGraphLibrary.add_member_variable(bp, variable_name, pin_category, instance_editable)
    return {"success": bool(ok), "asset_path": asset_path, "variable": variable_name,
            "type": pin_category, "instance_editable": instance_editable}
