def list_blueprint_components(asset_path: str):
    """List the component hierarchy of a Blueprint.

    Returns all SCS components on the Blueprint with their class, parent
    attach name, and (for scene components) relative transform. Uses the
    PyUnrealBridge native helper when available — UE 5.6 stripped SCS
    access from the Python API, so the bridge is required for full results.

    :param asset_path: Full content path to the Blueprint (e.g. "/Game/BP_MyActor").
    """
    import unreal

    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {
            "success": False,
            "message": "Blueprint not found at '{}'.".format(asset_path),
        }

    # Prefer the C++ bridge — it can see SCS components in UE 5.6+.
    components = []
    if hasattr(unreal, "PyUnrealBlueprintLibrary"):
        try:
            raw = unreal.PyUnrealBlueprintLibrary.list_blueprint_components(bp)
            # Bridge returns rows: Name|Class|Parent|Loc|Rot|Scale
            for row in raw:
                parts = row.split("|")
                if len(parts) < 6:
                    continue
                entry = {
                    "name": parts[0],
                    "class": parts[1],
                    "parent": parts[2],
                    "source": "SCS",
                }
                # Parse transform if present (scene components only).
                if parts[3]:
                    lx, ly, lz = (float(x) for x in parts[3].split(","))
                    rp, ry, rr = (float(x) for x in parts[4].split(","))
                    sx, sy, sz = (float(x) for x in parts[5].split(","))
                    entry["transform"] = {
                        "location": [lx, ly, lz],
                        "rotation": [rp, ry, rr],
                        "scale": [sx, sy, sz],
                    }
                components.append(entry)
            return {
                "success": True,
                "asset_path": asset_path,
                "total_count": len(components),
                "components": components,
                "source": "PyUnrealBridge",
            }
        except Exception as e:
            # Fall through to legacy path on bridge error.
            bridge_err = str(e)
    else:
        bridge_err = "PyUnrealBridge plugin not enabled — SCS unreachable in UE 5.6 without it."

    # Legacy fallback (works on UE 5.5 and earlier).
    scs = None
    try:
        scs = getattr(bp, "simple_construction_script", None)
    except Exception:
        scs = None

    if scs is None:
        return {
            "success": False,
            "asset_path": asset_path,
            "total_count": 0,
            "components": [],
            "message": bridge_err,
        }

    for node in scs.get_all_nodes():
        ct = node.component_template
        if ct is None:
            continue
        components.append({
            "name": ct.get_name(),
            "class": ct.get_class().get_name(),
            "parent": str(node.get_editor_property("parent_component_or_variable_name") or ""),
            "source": "SCS-legacy",
        })

    return {
        "success": True,
        "asset_path": asset_path,
        "total_count": len(components),
        "components": components,
        "source": "legacy",
    }
