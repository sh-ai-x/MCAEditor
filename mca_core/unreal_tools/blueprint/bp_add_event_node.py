def bp_add_event_node(asset_path: str, event_name: str):
    """Add an event node to a Blueprint's EventGraph.

    Creates a UK2Node_Event for a named event. If the event matches an
    existing UFUNCTION on the Blueprint's class (or an interface it
    implements), the node is set up as an override. Otherwise it becomes
    a Custom Event.

    Idempotent — if an event with this name already exists, returns the
    existing node's ID instead of creating a duplicate.

    Common event names: BeginPlay, Tick, EndPlay, ReceiveBeginPlay,
    Interact, LocalInteract (interface methods are accepted as-is).

    Requires the PyUnrealBridge plugin.

    :param asset_path: Full content path to the Blueprint.
    :param event_name: UE event/function name to bind (e.g. "LocalInteract").
    """
    import unreal

    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {"success": False, "message": "Blueprint not found at '{}'.".format(asset_path)}

    if not hasattr(unreal, "PyUnrealBlueprintLibrary"):
        return {"success": False, "message": "PyUnrealBridge plugin not enabled."}

    node_id = unreal.PyUnrealBlueprintLibrary.add_event_node(bp, event_name)

    if not node_id:
        return {
            "success": False,
            "message": "Failed to add event '{}'. Check that the EventGraph exists.".format(event_name),
        }

    return {
        "success": True,
        "asset_path": asset_path,
        "event_name": event_name,
        "node_id": node_id,
    }
