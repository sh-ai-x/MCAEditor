def compile_blueprint(asset_path: str):
    """Compile a Blueprint and report success plus the compiler's real errors.

    Forces a recompile of the Blueprint (needed after changing variables,
    components, interfaces, the parent class, or graph nodes) and returns the
    ACTUAL compiler messages — not just a pass/fail status enum.

    Prefers the ``MCAEventGraphLibrary.compile_blueprint_with_messages`` C++
    helper, which routes the compile through an ``FCompilerResultsLog`` so the
    real error text comes back (e.g. "A node named 'Box' already exists"). If
    that helper is not present yet (the MCAEditorScripting plugin hasn't been
    rebuilt), it falls back to a plain compile + status enum so the tool still
    works — just without per-message detail.

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

    messages = []
    num_errors = 0
    num_warnings = 0
    detail_source = "compiler"

    # Preferred path: our C++ helper returns the compiler's tokenized messages.
    # First line is "SUMMARY: errors=N warnings=M"; remaining lines are tagged
    # "ERROR:" / "WARNING:" / "NOTE:".
    try:
        raw = list(unreal.MCAEventGraphLibrary.compile_blueprint_with_messages(bp))
        raw = [str(line) for line in raw]

        summary = raw[0] if raw and raw[0].startswith("SUMMARY:") else ""
        if summary:
            try:
                num_errors = int(summary.split("errors=")[1].split()[0])
                num_warnings = int(summary.split("warnings=")[1].split()[0])
            except (IndexError, ValueError):
                pass
            messages = raw[1:]
        else:
            # No summary line — treat every line as a message and infer errors.
            messages = raw
            num_errors = sum(1 for line in messages if line.startswith("ERROR:"))
            num_warnings = sum(1 for line in messages if line.startswith("WARNING:"))

    except AttributeError:
        # Fallback: the C++ helper isn't compiled in yet. Do a plain compile and
        # read the status enum so the tool still reports pass/fail correctly.
        detail_source = "status-only (rebuild MCAEditorScripting for per-message detail)"
        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        try:
            status_str = str(bp.get_editor_property("status"))
        except Exception:
            status_str = "unknown"
        # BS_ERROR / "error" in the enum name means the compile failed.
        if "error" in status_str.lower():
            num_errors = 1
            messages = ["ERROR: Blueprint failed to compile (status={}).".format(status_str)]
        else:
            messages = []

    # Split detail lines by severity for convenient consumption.
    error_messages = [line for line in messages if line.startswith("ERROR:")]
    warning_messages = [line for line in messages if line.startswith("WARNING:")]

    success = num_errors == 0

    # Save only on a clean compile so a broken Blueprint is never persisted.
    if success:
        unreal.EditorAssetLibrary.save_asset(asset_path)

    return {
        "success": success,
        "asset_path": asset_path,
        "errors": num_errors,
        "warnings": num_warnings,
        "messages": messages,
        "error_messages": error_messages,
        "warning_messages": warning_messages,
        "detail_source": detail_source,
        "message": (
            "Compiled clean." if success
            else "Blueprint has {} compile error(s).".format(num_errors)
        ),
    }
