def bp_add_function_call_node(asset_path: str, function_name: str, target_class: str = ""):
    """Add a function-call node (UK2Node_CallFunction) to the EventGraph.

    Looks up the function on target_class (or, if empty, on the Blueprint's
    own class) and creates a call node. The bridge searches common base
    classes — AActor, APawn, UObject, KismetMathLibrary, KismetSystemLibrary
    — as a fallback so simple cases (e.g. "Add" / "PrintString") work
    without an explicit class.

    For static factory functions like CreateLevelSequencePlayer, pass the
    owning class explicitly (e.g. target_class="LevelSequencePlayer").

    Requires the PyUnrealBridge plugin.

    :param asset_path: Full content path to the Blueprint.
    :param function_name: UFUNCTION name to call (e.g. "CreateLevelSequencePlayer", "Play").
    :param target_class: Owning class name (optional). Accepts both prefixed
        ("AActor") and unprefixed ("Actor") forms.
    """
    import unreal

    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {"success": False, "message": "Blueprint not found at '{}'.".format(asset_path)}

    if not hasattr(unreal, "PyUnrealBlueprintLibrary"):
        return {"success": False, "message": "PyUnrealBridge plugin not enabled."}

    node_id = unreal.PyUnrealBlueprintLibrary.add_function_call_node(bp, function_name, target_class)

    if not node_id:
        return {
            "success": False,
            "message": "Function '{}' not found on '{}' (or fallback classes).".format(
                function_name, target_class or "<self>"
            ),
        }

    return {
        "success": True,
        "asset_path": asset_path,
        "function": function_name,
        "target_class": target_class or "<self>",
        "node_id": node_id,
    }
