def get_project_info():
    """Get information about the current Unreal project.

    Returns project name, engine version, loaded plugins, and target platforms.
    """
    import unreal

    # Get the project descriptor.
    project_dir = unreal.Paths.project_dir()
    project_name = unreal.Paths.get_base_filename(unreal.Paths.get_project_file_path())

    # Get engine version.
    engine_version = unreal.SystemLibrary.get_engine_version()

    # Get the platform name.
    platform_name = unreal.SystemLibrary.get_platform_user_name()

    return {
        "success": True,
        "project_name": project_name,
        "project_dir": project_dir,
        "engine_version": engine_version,
        "platform": platform_name,
    }
