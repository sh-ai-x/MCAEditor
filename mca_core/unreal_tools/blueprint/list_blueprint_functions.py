def list_blueprint_functions(asset_path: str):
    """List user-defined functions in a Blueprint with their signatures.

    Returns function names, input parameters, and output parameters for
    each user-defined function graph in the Blueprint.

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

    functions = []

    try:
        # Get function graphs from the Blueprint.
        fn_graphs = unreal.BlueprintEditorLibrary.get_function_graphs(bp)
        for graph in fn_graphs:
            fn_name = graph.get_name()

            # Try to get function signature from the generated class.
            fn_info = {"name": fn_name, "inputs": [], "outputs": []}

            # Attempt to inspect the function via the generated class.
            gen_class = bp.generated_class()
            if gen_class is not None:
                func = gen_class.find_function(fn_name)
                if func is not None:
                    # Walk the function's parameters.
                    for param in func.get_params():
                        param_info = {
                            "name": param.get_name(),
                            "type": param.get_class().get_name(),
                        }
                        # Check direction (input vs output).
                        if param.has_any_property_flags(
                            unreal.PropertyFlags.OUT_PARM
                        ):
                            fn_info["outputs"].append(param_info)
                        else:
                            fn_info["inputs"].append(param_info)

            functions.append(fn_info)
    except Exception as e:
        # BlueprintEditorLibrary may not be available in all UE versions.
        # Fall back to a simpler approach.
        try:
            gen_class = bp.generated_class()
            if gen_class is not None:
                # List callable methods that aren't on the parent.
                parent_class = gen_class.get_super_class()
                parent_methods = set(dir(parent_class)) if parent_class else set()
                for name in sorted(dir(gen_class)):
                    if name.startswith("_"):
                        continue
                    if name in parent_methods:
                        continue
                    attr = getattr(gen_class, name, None)
                    if callable(attr):
                        functions.append({"name": name, "inputs": [], "outputs": []})
        except Exception:
            return {
                "success": False,
                "message": "Failed to list functions: {}".format(str(e)),
            }

    return {
        "success": True,
        "asset_path": asset_path,
        "total_count": len(functions),
        "functions": functions,
    }
