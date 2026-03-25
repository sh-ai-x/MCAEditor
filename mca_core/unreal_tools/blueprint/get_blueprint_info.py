def get_blueprint_info(asset_path: str):
    """Get a full overview of a Blueprint asset.

    Returns the Blueprint's type, parent class, generated class, components,
    variables, and user-defined functions — everything needed to understand
    what a Blueprint contains.

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

    # --- Basic info ---
    gen_class = bp.generated_class()
    parent_class = gen_class.get_super_class() if gen_class else None

    info = {
        "success": True,
        "name": bp.get_name(),
        "path": asset_path,
        "blueprint_type": type(bp).__name__,
        "parent_class": parent_class.get_name() if parent_class else "None",
        "generated_class": gen_class.get_name() if gen_class else "None",
    }

    # --- Components (from SimpleConstructionScript) ---
    components = []
    try:
        scs = bp.simple_construction_script
        if scs is not None:
            for node in scs.get_all_nodes():
                comp_template = node.component_template
                if comp_template is not None:
                    components.append({
                        "name": comp_template.get_name(),
                        "class": comp_template.get_class().get_name(),
                    })
    except Exception:
        pass
    info["components"] = components

    # --- Variables (properties on the generated class CDO) ---
    variables = []
    try:
        if gen_class is not None:
            cdo = unreal.get_default_object(gen_class)
            if cdo is not None:
                # Collect user-added properties (skip inherited engine ones).
                parent_props = set(dir(parent_class)) if parent_class else set()
                for prop_name in sorted(dir(cdo)):
                    if prop_name.startswith("_"):
                        continue
                    # Only include properties that are NEW on this class.
                    if prop_name in parent_props:
                        continue
                    try:
                        val = cdo.get_editor_property(prop_name)
                        variables.append({
                            "name": prop_name,
                            "type": type(val).__name__ if val is not None else "unknown",
                        })
                    except Exception:
                        pass
    except Exception:
        pass
    info["variables"] = variables[:50]
    info["total_variables"] = len(variables)

    # --- User-defined functions ---
    functions = []
    try:
        # Blueprint editor library provides function graphs.
        fn_graphs = unreal.BlueprintEditorLibrary.get_function_graphs(bp)
        for graph in fn_graphs:
            functions.append(graph.get_name())
    except Exception:
        pass
    info["functions"] = functions

    return info
