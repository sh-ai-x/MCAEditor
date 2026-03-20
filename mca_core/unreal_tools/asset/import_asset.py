def import_asset(source_path: str, destination_path: str):
    """Import an external file (FBX, OBJ, texture) into the project.

    :param source_path: Absolute filesystem path to the source file.
    :param destination_path: Content path for the imported asset (e.g. "/Game/Meshes/MyCube").
    """
    import unreal

    # Build the import task.
    task = unreal.AssetImportTask()
    task.filename = source_path
    task.destination_path = destination_path
    task.automated = True
    task.replace_existing = True
    task.save = True

    # Run the import.
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

    # Check if the import was successful.
    imported = task.get_editor_property("imported_object_paths")

    return {
        "success": len(imported) > 0 if imported else False,
        "source": source_path,
        "destination": destination_path,
        "imported_paths": [str(p) for p in imported] if imported else [],
    }
