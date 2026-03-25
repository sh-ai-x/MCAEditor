def get_subsystem(subsystem_name: str, subsystem_type: str = "editor"):
    """Inspect an editor/engine/game-instance subsystem's available methods.

    Returns a list of callable methods on the subsystem, helping Claude
    discover what operations a subsystem supports before writing code.

    :param subsystem_name: Name of the subsystem class (e.g. "EditorActorSubsystem").
    :param subsystem_type: One of "editor", "engine", or "game_instance" (default "editor").
    """
    import unreal

    # Look up the subsystem class in the unreal module.
    subsystem_cls = getattr(unreal, subsystem_name, None)
    if subsystem_cls is None:
        return {
            "success": False,
            "message": "Subsystem class '{}' not found in the unreal module.".format(
                subsystem_name
            ),
        }

    # Get the live subsystem instance based on type.
    subsystem = None
    try:
        if subsystem_type == "editor":
            subsystem = unreal.get_editor_subsystem(subsystem_cls)
        elif subsystem_type == "engine":
            subsystem = unreal.get_engine_subsystem(subsystem_cls)
        elif subsystem_type == "game_instance":
            # GameInstance subsystems require a world context — try default.
            subsystem = unreal.get_game_instance_subsystem(subsystem_cls)
        else:
            return {
                "success": False,
                "message": "Invalid subsystem_type '{}'. Must be 'editor', 'engine', or 'game_instance'.".format(
                    subsystem_type
                ),
            }
    except Exception as e:
        return {
            "success": False,
            "message": "Failed to get subsystem '{}' (type={}): {}".format(
                subsystem_name, subsystem_type, str(e)
            ),
        }

    if subsystem is None:
        return {
            "success": False,
            "message": "Subsystem '{}' returned None — it may not be active.".format(
                subsystem_name
            ),
        }

    # --- Collect methods from the live instance ---
    methods = []
    for name in sorted(dir(subsystem)):
        # Skip private/dunder attributes.
        if name.startswith("_"):
            continue
        attr = getattr(subsystem, name, None)
        if not callable(attr):
            continue

        doc = (getattr(attr, "__doc__", "") or "").split("\n")[0].strip()
        methods.append({
            "name": name,
            "doc": doc[:200],
        })

    total_methods = len(methods)
    methods = methods[:100]

    return {
        "success": True,
        "subsystem_name": subsystem_name,
        "subsystem_type": subsystem_type,
        "class": type(subsystem).__name__,
        "methods": methods,
        "total_methods": total_methods,
    }
