def list_blueprint_events(asset_path: str):
    """Enumerate existing event nodes in a Blueprint's event graph.

    Lists events like BeginPlay, Tick, custom event dispatchers, input
    actions, and other event nodes. This helps understand what events a
    Blueprint already handles so code can call them correctly.

    :param asset_path: Full content path to the Blueprint (e.g. "/Game/BP_MyActor").
    """
    import re
    import unreal

    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {
            "success": False,
            "message": "Blueprint not found at '{}'.".format(asset_path),
        }

    # UE 5.6 removed ``ubergraph_pages`` from the Python property set on
    # ``UBlueprint``, and ``EdGraph.nodes`` is now marked protected, so
    # node-level enumeration via Python is no longer possible. We fall
    # back to:
    #   1. The legacy ``ubergraph_pages`` path for older versions.
    #   2. The AssetRegistry ``ImplementedInterfaces`` tag, which encodes
    #      every interface-method graph the Blueprint overrides.
    #   3. Probing common graph names via ``find_graph``.

    events = []
    status_notes = []

    # --- Path 1: legacy ubergraph walk (5.5 and earlier) ---------------
    legacy_ok = False
    try:
        uber_graphs = bp.get_editor_property("ubergraph_pages")
        if uber_graphs:
            for graph in uber_graphs:
                graph_name = graph.get_name()
                try:
                    nodes = graph.get_editor_property("nodes")
                except Exception:
                    continue
                for node in nodes:
                    node_class = node.get_class().get_name()
                    is_event = (
                        "Event" in node_class
                        or "InputAction" in node_class
                        or "CustomEvent" in node_class
                        or "Dispatcher" in node_class
                    )
                    if not is_event:
                        continue
                    node_title = ""
                    try:
                        node_title = node.get_editor_property("node_comment")
                    except Exception:
                        pass
                    if not node_title:
                        node_title = node.get_name()
                    entry = {
                        "node_class": node_class,
                        "name": node_title,
                        "graph": graph_name,
                        "source": "ubergraph",
                    }
                    try:
                        er = node.get_editor_property("event_reference")
                        if er:
                            entry["function"] = str(er)
                    except Exception:
                        pass
                    try:
                        cn = node.get_editor_property("custom_function_name")
                        if cn:
                            entry["custom_name"] = str(cn)
                    except Exception:
                        pass
                    events.append(entry)
            legacy_ok = True
    except Exception as e:
        status_notes.append("ubergraph_pages unavailable ({}).".format(e))

    # --- Path 2: interface-override graphs via AssetRegistry tag --------
    if not legacy_ok:
        status_notes.append(
            "UE 5.6 protects EdGraph.nodes — event-node introspection "
            "requires a C++ helper. Listing overridden interface graphs "
            "and standard graph names instead."
        )
    try:
        ar = unreal.AssetRegistryHelpers.get_asset_registry()
        ads = ar.get_assets_by_package_name(bp.get_outermost().get_name())
        if ads:
            ii_raw = ads[0].get_tag_value("ImplementedInterfaces")
            if ii_raw:
                ii_raw = str(ii_raw)
                # Each interface entry has Graphs=("EdGraph'/.../BP:GraphName'",...)
                # Pull out the trailing ":GraphName" tokens.
                for m in re.finditer(r":([A-Za-z0-9_]+)'", ii_raw):
                    name = m.group(1)
                    if any(e.get("name") == name for e in events):
                        continue
                    events.append({
                        "name": name,
                        "graph": name,
                        "source": "interface-override",
                    })
    except Exception as e:
        status_notes.append("AssetRegistry interface walk failed: {}".format(e))

    # --- Path 3: probe a small set of well-known graph names ------------
    # ``find_graph`` is one of the few introspection APIs that still
    # works on 5.6, but it's name-based — we can only confirm existence,
    # not list nodes inside.
    probe_names = [
        "EventGraph", "UserConstructionScript", "ReceiveBeginPlay",
        "ReceiveTick", "ReceiveEndPlay", "ReceiveActorBeginOverlap",
        "ReceiveActorEndOverlap", "ReceiveHit",
    ]
    for name in probe_names:
        try:
            g = unreal.BlueprintEditorLibrary.find_graph(bp, name)
            if g is not None and not any(e.get("name") == name for e in events):
                events.append({
                    "name": name,
                    "graph": name,
                    "source": "find_graph",
                })
        except Exception:
            pass

    return {
        "success": True,
        "asset_path": asset_path,
        "total_count": len(events),
        "events": events,
        "status": " ".join(status_notes) if status_notes else "ok",
    }
