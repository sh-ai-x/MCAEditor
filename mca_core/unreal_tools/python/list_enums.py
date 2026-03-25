def list_enums(keyword: str = "", max_results: int = 100):
    """List UE enums available in the Python API.

    Optionally filters by keyword. For each enum, lists all valid values.
    This is essential for discovering valid parameter values when using
    other tools or writing code via ``execute_python``.

    :param keyword: Optional substring filter (case-insensitive). Empty returns all.
    :param max_results: Maximum number of enums to return (default 100).
    """
    import unreal

    keyword_lower = keyword.lower()
    enums = []

    for name in sorted(dir(unreal)):
        # Skip private/dunder names.
        if name.startswith("_"):
            continue

        attr = getattr(unreal, name, None)

        # UE enums in Python are subclasses of unreal.EnumBase.
        if not isinstance(attr, type):
            continue

        # Check if this is an enum type.
        try:
            if not issubclass(attr, unreal.EnumBase):
                continue
        except TypeError:
            continue

        # Apply keyword filter.
        if keyword_lower and keyword_lower not in name.lower():
            continue

        # Collect enum values.
        values = []
        for val_name in sorted(dir(attr)):
            if val_name.startswith("_"):
                continue
            val = getattr(attr, val_name, None)
            if isinstance(val, attr):
                values.append(val_name)

        enums.append({
            "name": name,
            "values": values,
        })

        if len(enums) >= max_results:
            break

    return {
        "success": True,
        "keyword": keyword,
        "count": len(enums),
        "enums": enums,
    }
