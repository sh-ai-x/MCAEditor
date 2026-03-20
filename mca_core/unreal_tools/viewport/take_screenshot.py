def take_screenshot(output_path: str = None):
    """Capture a screenshot of the active editor viewport.

    :param output_path: Filesystem path to save the screenshot. If None, saves
        to the project's Saved/Screenshots directory.
    """
    import unreal
    import os
    import datetime

    if output_path is None:
        # Default to project's Saved/Screenshots directory.
        project_dir = unreal.Paths.project_saved_dir()
        screenshot_dir = os.path.join(project_dir, "Screenshots")
        os.makedirs(screenshot_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(screenshot_dir, "MCA_Screenshot_{}.png".format(timestamp))

    # Take a high-res screenshot of the active viewport.
    unreal.AutomationLibrary.take_high_res_screenshot(
        1920, 1080, output_path
    )

    return {
        "success": True,
        "path": output_path,
    }
