def get_python_output():
    """Get the Python version and environment info from UE's interpreter."""
    import sys
    import unreal

    return {
        "success": True,
        "python_version": sys.version,
        "engine_version": unreal.SystemLibrary.get_engine_version(),
        "platform": sys.platform,
        "executable": sys.executable,
    }
