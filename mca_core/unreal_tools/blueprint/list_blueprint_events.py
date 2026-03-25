def list_blueprint_events(asset_path: str):
    """Enumerate existing event nodes in a Blueprint's event graph.

    Lists events like BeginPlay, Tick, custom event dispatchers, input
    actions, and other event nodes. This helps understand what events a
    Blueprint already handles so code can call them correctly.

    :param asset_path: Full content path to the Blueprint (e.g. "/Game/BP_MyActor").
    """
    import unreal

    # Load the Blueprint asset.
    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {
            "success": False,
            "message": "Blueprint not found at '{}'.".format(asset_path),
        }

    events = []

    try:
        # Get the event graphs (UberGraphPages contains the main event graph).
        uber_graphs = bp.get_editor_property("ubergraph_pages")
        if uber_graphs:
            for graph in uber_graphs:
                graph_name = graph.get_name()

                # Walk graph nodes to find event nodes.
                for node in graph.get_editor_property("nodes"):
                    node_class = node.get_class().get_name()
                    node_title = ""

                    # Try to get the node's display name.
                    try:
                        node_title = node.get_editor_property("node_comment")
                    except Exception:
                        pass

                    if not node_title:
                        node_title = node.get_name()

                    # Filter for event-type nodes.
                    is_event = False

                    # K2Node_Event is the base class for all event nodes.
                    if "Event" in node_class or "event" in node_class.lower():
                        is_event = True
                    # Input action nodes.
                    elif "InputAction" in node_class:
                        is_event = True
                    # Custom events and dispatchers.
                    elif "CustomEvent" in node_class or "Dispatcher" in node_class:
                        is_event = True

                    if is_event:
                        event_info = {
                            "node_class": node_class,
                            "name": node_title,
                            "graph": graph_name,
                        }

                        # Try to get the event's function name.
                        try:
                            event_ref = node.get_editor_property("event_reference")
                            if event_ref:
                                event_info["function"] = str(event_ref)
                        except Exception:
                            pass

                        # Try to get custom event name.
                        try:
                            custom_name = node.get_editor_property(
                                "custom_function_name"
                            )
                            if custom_name:
                                event_info["custom_name"] = str(custom_name)
                        except Exception:
                            pass

                        events.append(event_info)

    except Exception as e:
        return {
            "success": False,
            "message": "Failed to enumerate events: {}".format(str(e)),
        }

    return {
        "success": True,
        "asset_path": asset_path,
        "total_count": len(events),
        "events": events,
    }
