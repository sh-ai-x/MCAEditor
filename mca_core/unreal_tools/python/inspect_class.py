def inspect_class(class_name: str):
    """Inspect a UE class — list its properties, methods, and parent chain.

    Returns the class hierarchy, all editable properties with their types,
    and all callable methods with their signatures.

    :param class_name: Name of the Unreal class (e.g. "StaticMeshActor", "Character").
    """
    import unreal

    # Try to find the class in the unreal module.
    cls = getattr(unreal, class_name, None)
    if cls is None:
        return {
            "success": False,
            "message": "Class '{}' not found in the unreal module.".format(class_name),
        }

    # --- Build parent chain ---
    parent_chain = []
    current = cls
    while current is not None:
        parent_chain.append(current.__name__)
        # Walk up MRO; stop at 'object' or 'StructBase'.
        bases = [b for b in current.__bases__ if b.__name__ not in ("object", "type")]
        current = bases[0] if bases else None

    # --- Collect properties (editable UE properties via CDO if available) ---
    properties = []
    try:
        # Generate a CDO or default instance to inspect properties.
        cdo = unreal.get_default_object(cls)
        if cdo is not None:
            for prop_name in dir(cdo):
                # Skip private/dunder attrs.
                if prop_name.startswith("_"):
                    continue
                # Only include properties that have get_editor_property support.
                try:
                    val = cdo.get_editor_property(prop_name)
                    properties.append({
                        "name": prop_name,
                        "type": type(val).__name__ if val is not None else "unknown",
                        "value": str(val)[:200],
                    })
                except Exception:
                    pass
    except Exception:
        pass

    # Cap properties to avoid huge payloads.
    total_properties = len(properties)
    properties = properties[:100]

    # --- Collect methods ---
    methods = []
    for name in sorted(dir(cls)):
        if name.startswith("_"):
            continue
        attr = getattr(cls, name, None)
        if callable(attr):
            # Get docstring for signature hints.
            doc = getattr(attr, "__doc__", "") or ""
            # Truncate long docstrings.
            first_line = doc.split("\n")[0].strip() if doc else ""
            methods.append({
                "name": name,
                "doc": first_line[:200],
            })

    total_methods = len(methods)
    methods = methods[:100]

    return {
        "success": True,
        "class_name": class_name,
        "parent_chain": parent_chain,
        "properties": properties,
        "total_properties": total_properties,
        "methods": methods,
        "total_methods": total_methods,
    }
