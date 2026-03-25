def get_class_hierarchy(class_name: str):
    """Get the full inheritance chain of a UE class.

    Walks the MRO (method resolution order) from the given class up to the
    base UE types, showing the complete parent chain. Useful for understanding
    what a class inherits and what APIs are available at each level.

    :param class_name: Name of the Unreal class (e.g. "Character", "SkeletalMeshComponent").
    """
    import unreal

    # Look up the class in the unreal module.
    cls = getattr(unreal, class_name, None)
    if cls is None:
        return {
            "success": False,
            "message": "Class '{}' not found in the unreal module.".format(class_name),
        }

    # --- Walk the MRO for the full chain ---
    hierarchy = []
    for parent in cls.__mro__:
        name = parent.__name__
        # Skip Python builtins.
        if name in ("object", "type"):
            continue

        doc = (getattr(parent, "__doc__", "") or "").split("\n")[0].strip()
        hierarchy.append({
            "class": name,
            "module": getattr(parent, "__module__", ""),
            "doc": doc[:200],
        })

    return {
        "success": True,
        "class_name": class_name,
        "hierarchy": hierarchy,
    }
