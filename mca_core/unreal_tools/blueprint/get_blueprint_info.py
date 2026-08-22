def get_blueprint_info(asset_path: str):
    """Get a full overview of a Blueprint asset.

    Returns the Blueprint's type, parent class, generated class, components,
    variables, and user-defined functions — everything needed to understand
    what a Blueprint contains.

    :param asset_path: Full content path to the Blueprint (e.g. "/Game/BP_MyActor").
    """
    import re
    import unreal

    # --- 5.6 compat helpers --------------------------------------------
    # In UE 5.6 the Python API stopped exposing several properties on
    # ``Blueprint`` / ``BlueprintGeneratedClass`` (``parent_class``,
    # ``simple_construction_script``, ``ubergraph_pages``,
    # ``implemented_interfaces``) and ``get_super_class`` was removed from
    # ``BlueprintGeneratedClass``. We work around it by reading the
    # AssetRegistry tags, which still encode the same info.

    def _tag(asset_data, name):
        # Defensive get_tag_value — returns "" on any error/missing tag.
        try:
            v = asset_data.get_tag_value(name)
            return str(v) if v else ""
        except Exception:
            return ""

    def _parse_class_path(s):
        # AssetRegistry encodes class refs as "Class'/Script/Module.ClassName'"
        # — pull out the "/Script/Module.ClassName" path inside the quotes.
        if not s:
            return ""
        m = re.search(r"'([^']+)'", s)
        return m.group(1) if m else s

    def _load_class(class_path):
        # Resolve a "/Script/Module.ClassName" path to the UClass UObject.
        if not class_path:
            return None
        try:
            return unreal.load_class(None, class_path)
        except Exception:
            return None

    # --- Load the asset ------------------------------------------------
    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {
            "success": False,
            "message": "Blueprint not found at '{}'.".format(asset_path),
        }

    gen_class = bp.generated_class()

    # --- Parent class via AssetRegistry tag ----------------------------
    ar = unreal.AssetRegistryHelpers.get_asset_registry()
    pkg_name = bp.get_outermost().get_name()
    ads = ar.get_assets_by_package_name(pkg_name)
    asset_data = ads[0] if ads else None

    parent_class_path = _parse_class_path(_tag(asset_data, "ParentClass")) if asset_data else ""
    native_parent_path = _parse_class_path(_tag(asset_data, "NativeParentClass")) if asset_data else ""
    parent_class = _load_class(parent_class_path)
    parent_name = parent_class.get_name() if parent_class else (parent_class_path.split(".")[-1] if parent_class_path else "None")

    info = {
        "success": True,
        "name": bp.get_name(),
        "path": asset_path,
        "blueprint_type": type(bp).__name__,
        "parent_class": parent_name,
        "parent_class_path": parent_class_path or "None",
        "native_parent_class_path": native_parent_path or "None",
        "generated_class": gen_class.get_name() if gen_class else "None",
    }

    # --- Implemented interfaces (AssetRegistry tag) --------------------
    interfaces = []
    if asset_data:
        ii_raw = _tag(asset_data, "ImplementedInterfaces")
        if ii_raw:
            # Tag format: ((Interface="Class'/Script/.../IFoo'",Graphs=(...)),...)
            # Pull each interface class path out.
            for m in re.finditer(r"Interface=\"[^\"]*'([^']+)'\"", ii_raw):
                interfaces.append(m.group(1).split(".")[-1])
    info["interfaces"] = interfaces

    # --- Components (from SimpleConstructionScript) --------------------
    # UE 5.6 stripped ``simple_construction_script`` from the Python API.
    # We try the legacy access for older versions; on 5.6 we report that
    # SCS introspection requires a C++ helper.
    components = []
    scs_status = "ok"
    try:
        scs = getattr(bp, "simple_construction_script", None)
        if scs is None:
            try:
                scs = bp.get_editor_property("simple_construction_script")
            except Exception:
                scs = None
        if scs is not None:
            for node in scs.get_all_nodes():
                comp_template = node.component_template
                if comp_template is not None:
                    components.append({
                        "name": comp_template.get_name(),
                        "class": comp_template.get_class().get_name(),
                    })
        else:
            scs_status = "unavailable: SimpleConstructionScript not exposed to Python (UE 5.6+). Requires native helper."
    except Exception as e:
        scs_status = "error: {}".format(e)
    info["components"] = components
    info["components_status"] = scs_status

    # --- Variables (CDO walk, with parent-class subtraction) -----------
    variables = []
    try:
        if gen_class is not None:
            cdo = unreal.get_default_object(gen_class)
            if cdo is not None:
                parent_props = set()
                if parent_class is not None:
                    parent_cdo = unreal.get_default_object(parent_class)
                    if parent_cdo is not None:
                        parent_props = set(dir(parent_cdo))
                for prop_name in sorted(dir(cdo)):
                    if prop_name.startswith("_"):
                        continue
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

    # --- User-defined functions ----------------------------------------
    # ``get_function_graphs`` was removed from BlueprintEditorLibrary in 5.6.
    # We can still discover interface-override graphs from the
    # ImplementedInterfaces tag, plus probe the standard graph names.
    functions = []
    if asset_data:
        ii_raw = _tag(asset_data, "ImplementedInterfaces")
        # Tag encodes graph paths as "EdGraph'/Game/.../BP_X:GraphName'"
        for m in re.finditer(r":([A-Za-z0-9_]+)'", ii_raw):
            name = m.group(1)
            if name not in functions:
                functions.append(name)
    # Also probe a couple of standard graphs that may exist.
    for name in ("UserConstructionScript",):
        try:
            g = unreal.BlueprintEditorLibrary.find_graph(bp, name)
            if g is not None and name not in functions:
                functions.append(name)
        except Exception:
            pass
    info["functions"] = functions

    return info
