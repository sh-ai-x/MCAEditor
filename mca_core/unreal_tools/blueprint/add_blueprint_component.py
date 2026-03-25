def add_blueprint_component(asset_path: str, component_class: str, component_name: str = "", parent_component: str = ""):
    """Add a component to a Blueprint's component hierarchy.

    Adds a new component to the Blueprint's SimpleConstructionScript.
    The operation is wrapped in an editor transaction for Ctrl+Z undo support.

    Note: This uses the SCS API which has limitations. For advanced component
    setups, use ``execute_python`` directly.

    :param asset_path: Full content path to the Blueprint (e.g. "/Game/BP_MyActor").
    :param component_class: UE component class name (e.g. "StaticMeshComponent", "PointLightComponent").
    :param component_name: Optional name for the component. Auto-generated if empty.
    :param parent_component: Optional name of an existing component to attach to.
    """
    import unreal

    # Load the Blueprint asset.
    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {
            "success": False,
            "message": "Blueprint not found at '{}'.".format(asset_path),
        }

    # Resolve the component class.
    comp_cls = getattr(unreal, component_class, None)
    if comp_cls is None:
        return {
            "success": False,
            "message": "Component class '{}' not found in the unreal module.".format(
                component_class
            ),
        }

    scs = bp.simple_construction_script
    if scs is None:
        return {
            "success": False,
            "message": "Blueprint '{}' has no SimpleConstructionScript (not an Actor BP?).".format(
                asset_path
            ),
        }

    with unreal.ScopedEditorTransaction("add_blueprint_component: {}".format(component_class)):

        # Find the parent SCS node if specified.
        parent_node = None
        if parent_component:
            for node in scs.get_all_nodes():
                if node.component_template and node.component_template.get_name() == parent_component:
                    parent_node = node
                    break
            if parent_node is None:
                return {
                    "success": False,
                    "message": "Parent component '{}' not found.".format(parent_component),
                }

        try:
            # Create a new SCS node for the component.
            new_node = scs.create_node(comp_cls, component_name or "")

            if new_node is None:
                return {
                    "success": False,
                    "message": "Failed to create SCS node for '{}'.".format(component_class),
                }

            # Attach to parent if specified.
            if parent_node is not None:
                parent_node.add_child_node(new_node)

            # Compile to apply changes.
            unreal.KismetEditorUtilities.compile_blueprint(bp)

            # Save the asset.
            unreal.EditorAssetLibrary.save_asset(asset_path)

            # Get the final component name.
            final_name = ""
            if new_node.component_template:
                final_name = new_node.component_template.get_name()

        except Exception as e:
            return {
                "success": False,
                "message": "Failed to add component: {}".format(str(e)),
            }

    return {
        "success": True,
        "asset_path": asset_path,
        "component_name": final_name,
        "component_class": component_class,
        "parent": parent_component or "root",
    }
