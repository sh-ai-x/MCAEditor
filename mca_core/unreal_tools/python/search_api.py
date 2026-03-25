def search_api(keyword: str, max_results: int = 50):
    """Search the unreal module for classes and functions matching a keyword.

    Performs a case-insensitive substring search across all names in the
    ``unreal`` module. Useful for discovering what APIs are available before
    writing code with ``execute_python``.

    :param keyword: Substring to search for (e.g. "blueprint", "skeleton", "anim").
    :param max_results: Maximum number of results to return (default 50).
    """
    import unreal

    keyword_lower = keyword.lower()
    classes = []
    functions = []
    other = []

    for name in sorted(dir(unreal)):
        # Skip private/dunder names.
        if name.startswith("_"):
            continue

        if keyword_lower not in name.lower():
            continue

        attr = getattr(unreal, name, None)

        # Classify the match.
        if isinstance(attr, type):
            doc = (getattr(attr, "__doc__", "") or "").split("\n")[0].strip()
            classes.append({"name": name, "doc": doc[:200]})
        elif callable(attr):
            doc = (getattr(attr, "__doc__", "") or "").split("\n")[0].strip()
            functions.append({"name": name, "doc": doc[:200]})
        else:
            other.append({"name": name, "type": type(attr).__name__})

    # Combine and cap.
    total_count = len(classes) + len(functions) + len(other)
    classes = classes[:max_results]
    functions = functions[:max_results]
    other = other[:max_results]

    return {
        "success": True,
        "keyword": keyword,
        "total_count": total_count,
        "classes": classes,
        "functions": functions,
        "other": other,
    }
