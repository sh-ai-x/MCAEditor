def compile_blueprint(asset_path: str):
    """Compile a Blueprint and report success or errors.

    Forces a recompile of the Blueprint, which is needed after modifying
    variables, components, or other structural changes.

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

    # Compile the Blueprint.
    try:
        unreal.KismetEditorUtilities.compile_blueprint(bp)
    except Exception as e:
        return {
            "success": False,
            "message": "Compilation failed: {}".format(str(e)),
        }

    # Check compilation status.
    try:
        status = bp.get_editor_property("status")
        status_str = str(status)
    except Exception:
        status_str = "unknown"

    # Check for compiler errors.
    is_error = "error" in status_str.lower()

    # Save after successful compile.
    if not is_error:
        unreal.EditorAssetLibrary.save_asset(asset_path)

    return {
        "success": not is_error,
        "asset_path": asset_path,
        "status": status_str,
        "message": "Compilation completed." if not is_error else "Blueprint has compilation errors.",
    }
