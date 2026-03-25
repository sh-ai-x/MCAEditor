def set_blueprint_variable(asset_path: str, variable_name: str, variable_type: str = "", default_value: str = "", category: str = ""):
    """Add or modify a variable on a Blueprint.

    If the variable already exists, updates its default value. If it does
    not exist, attempts to add it. The operation is wrapped in an editor
    transaction for Ctrl+Z undo support.

    Note: Variable creation via Python has API limitations. For complex types
    or if creation fails, use ``execute_python`` with BlueprintEditorLibrary
    directly.

    :param asset_path: Full content path to the Blueprint (e.g. "/Game/BP_MyActor").
    :param variable_name: Name of the variable to add or modify.
    :param variable_type: UE property type for new variables (e.g. "float", "int", "bool", "string", "Vector", "Rotator"). Ignored for existing variables.
    :param default_value: Default value as a string (e.g. "3.14", "true", "(X=1,Y=2,Z=3)").
    :param category: Optional category for the variable in the Blueprint editor.
    """
    import unreal

    # Load the Blueprint asset.
    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {
            "success": False,
            "message": "Blueprint not found at '{}'.".format(asset_path),
        }

    gen_class = bp.generated_class()
    if gen_class is None:
        return {
            "success": False,
            "message": "Blueprint '{}' has no generated class.".format(asset_path),
        }

    with unreal.ScopedEditorTransaction("set_blueprint_variable: {}".format(variable_name)):

        # Check if the variable already exists on the CDO.
        cdo = unreal.get_default_object(gen_class)
        variable_exists = False
        if cdo is not None:
            try:
                cdo.get_editor_property(variable_name)
                variable_exists = True
            except Exception:
                pass

        if not variable_exists:
            # Try to add the variable using BlueprintEditorLibrary.
            try:
                # Map common type names to UE property type strings.
                type_map = {
                    "bool": "BoolProperty",
                    "int": "IntProperty",
                    "float": "FloatProperty",
                    "double": "DoubleProperty",
                    "string": "StrProperty",
                    "name": "NameProperty",
                    "text": "TextProperty",
                    "vector": "StructProperty",
                    "rotator": "StructProperty",
                    "transform": "StructProperty",
                }

                mapped_type = type_map.get(variable_type.lower(), variable_type)

                # Attempt to add via BlueprintEditorLibrary if available.
                result = unreal.BlueprintEditorLibrary.add_variable(
                    bp, variable_name, mapped_type
                )
                if not result:
                    return {
                        "success": False,
                        "message": "Failed to add variable '{}' (type '{}'). Try using execute_python for complex types.".format(
                            variable_name, variable_type
                        ),
                    }

                # Set category if specified.
                if category:
                    try:
                        unreal.BlueprintEditorLibrary.set_variable_category(
                            bp, variable_name, category
                        )
                    except Exception:
                        pass

                # Compile to make the variable accessible on the CDO.
                unreal.KismetEditorUtilities.compile_blueprint(bp)

                # Refresh CDO reference.
                gen_class = bp.generated_class()
                cdo = unreal.get_default_object(gen_class)

            except AttributeError:
                return {
                    "success": False,
                    "message": "BlueprintEditorLibrary.add_variable not available. Use execute_python to add variables manually.",
                }
            except Exception as e:
                return {
                    "success": False,
                    "message": "Failed to add variable: {}".format(str(e)),
                }

        # Set the default value if provided.
        if default_value and cdo is not None:
            try:
                # Try to parse the value based on the current property type.
                current_val = cdo.get_editor_property(variable_name)
                val_type = type(current_val).__name__

                # Convert string to appropriate Python type.
                if val_type == "bool":
                    parsed = default_value.lower() in ("true", "1", "yes")
                elif val_type in ("int", "int32"):
                    parsed = int(default_value)
                elif val_type in ("float", "double"):
                    parsed = float(default_value)
                elif val_type == "str":
                    parsed = default_value
                else:
                    # For complex types, try direct assignment as string.
                    parsed = default_value

                cdo.set_editor_property(variable_name, parsed)
            except Exception as e:
                return {
                    "success": True,
                    "message": "Variable exists but failed to set default: {}".format(
                        str(e)
                    ),
                    "variable_name": variable_name,
                    "created": not variable_exists,
                }

        # Save the asset.
        unreal.EditorAssetLibrary.save_asset(asset_path)

    return {
        "success": True,
        "asset_path": asset_path,
        "variable_name": variable_name,
        "created": not variable_exists,
    }
