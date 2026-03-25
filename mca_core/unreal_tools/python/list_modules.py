def list_modules(keyword: str = "", max_results: int = 100):
    """List importable Python modules available in UE's interpreter.

    Pre-filters internal engine noise (``_ue_internal``, ``_frozen_importlib``,
    encodings sub-modules, etc.) so only usable modules are returned.

    :param keyword: Optional substring filter (case-insensitive). Empty returns all.
    :param max_results: Maximum number of modules to return (default 100).
    """
    import sys
    import pkgutil

    keyword_lower = keyword.lower()

    # --- Prefixes and patterns to exclude (internal / noise) ---
    EXCLUDE_PREFIXES = (
        "_",            # private/internal modules
        "encodings.",   # codec sub-modules
        "importlib.",   # import machinery internals
        "unittest.",    # test framework internals
        "test.",        # CPython test suite
        "idlelib.",     # IDLE editor
        "tkinter.",     # Tk GUI (not usable in UE)
        "turtle",       # turtle graphics
        "distutils.",   # deprecated build tools
    )
    EXCLUDE_EXACT = {
        "antigravity", "this", "__phello__",
    }

    modules = []

    # Collect from sys.modules (already loaded modules).
    seen = set()
    for name in sorted(sys.modules.keys()):
        if name.startswith(tuple(EXCLUDE_PREFIXES)):
            continue
        if name in EXCLUDE_EXACT:
            continue
        if keyword_lower and keyword_lower not in name.lower():
            continue

        seen.add(name)
        mod = sys.modules[name]
        doc = (getattr(mod, "__doc__", "") or "").split("\n")[0].strip()
        modules.append({
            "name": name,
            "loaded": True,
            "doc": doc[:200],
        })

    # Also scan for importable (but not yet loaded) top-level modules.
    try:
        for importer, name, is_pkg in pkgutil.iter_modules():
            if name in seen:
                continue
            if name.startswith(tuple(EXCLUDE_PREFIXES)):
                continue
            if name in EXCLUDE_EXACT:
                continue
            if keyword_lower and keyword_lower not in name.lower():
                continue

            seen.add(name)
            modules.append({
                "name": name,
                "loaded": False,
                "doc": "",
            })
    except Exception:
        # pkgutil can fail in some embedded environments.
        pass

    # Sort alphabetically and cap.
    modules.sort(key=lambda m: m["name"])
    total_count = len(modules)
    modules = modules[:max_results]

    return {
        "success": True,
        "keyword": keyword,
        "total_count": total_count,
        "modules": modules,
    }
