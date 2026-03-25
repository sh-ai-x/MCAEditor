def list_blueprint_components(asset_path: str):
    """List the component hierarchy of a Blueprint.

    Returns all components from the Blueprint's SimpleConstructionScript,
    including their class, parent component, and key properties.

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

    components = []

    try:
        scs = bp.simple_construction_script
        if scs is None:
            return {
                "success": True,
                "asset_path": asset_path,
                "message": "Blueprint has no SimpleConstructionScript (may not be an Actor BP).",
                "total_count": 0,
                "components": [],
            }

        all_nodes = scs.get_all_nodes()
        for node in all_nodes:
            comp_template = node.component_template
            if comp_template is None:
                continue

            # Get the parent node name if it exists.
            parent_name = ""
            parent_node = node.get_editor_property("parent_component_or_variable_name")
            if parent_node:
                parent_name = str(parent_node)

            # Get transform if it's a SceneComponent.
            transform = None
            try:
                rel_loc = comp_template.get_editor_property("relative_location")
                rel_rot = comp_template.get_editor_property("relative_rotation")
                rel_scale = comp_template.get_editor_property("relative_scale3d")
                transform = {
                    "location": [rel_loc.x, rel_loc.y, rel_loc.z],
                    "rotation": [rel_rot.pitch, rel_rot.yaw, rel_rot.roll],
                    "scale": [rel_scale.x, rel_scale.y, rel_scale.z],
                }
            except Exception:
                pass

            comp_info = {
                "name": comp_template.get_name(),
                "class": comp_template.get_class().get_name(),
                "parent": parent_name,
            }
            if transform:
                comp_info["transform"] = transform

            components.append(comp_info)

    except Exception as e:
        return {
            "success": False,
            "message": "Failed to read components: {}".format(str(e)),
        }

    return {
        "success": True,
        "asset_path": asset_path,
        "total_count": len(components),
        "components": components,
    }
