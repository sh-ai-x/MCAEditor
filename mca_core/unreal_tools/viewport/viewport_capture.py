# MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def viewport_capture(output_path: str = None, width: int = 1280, height: int = 720,
                     fov: float = 90.0, location: list = None, rotation: list = None):
    """Capture the current scene to a PNG and return its path.

    Two capture paths, chosen automatically by whether PIE/Simulate is running:

    * **Editor (not playing) — fully synchronous.** Uses a one-shot
      ``SceneCapture2D`` whose ``capture_scene()`` forces a blocking render, so
      the PNG exists on disk the instant this call returns (``synchronous:
      True``). Good for inspecting the level or editor-world poses in a single
      call.
    * **Playing (PIE/Simulate) — deferred two-call.** The editor world is None
      during play and editor actors cannot be spawned into the game world, so
      this issues an async high-res screenshot of the live game viewport and
      returns ``synchronous: False, pending: True``. The image only flushes once
      the game thread renders the next frame — which it cannot do while this
      call is still executing on that thread. **Read the returned path on your
      NEXT call** (any subsequent MCP round-trip gives the game time to flush).
      The file at ``path`` is deleted before the request so its existence is a
      reliable "done" signal.

    By default the capture uses the current editor viewport camera, so the
    framing matches what you see. Pass explicit location/rotation to frame a
    specific subject (editor path only; the PIE path captures the game
    viewport).

    :param output_path: Filesystem path for the PNG. If None, writes a
        timestamped file under the project's Saved/Screenshots directory.
    :param width: Capture width in pixels.
    :param height: Capture height in pixels.
    :param fov: Horizontal field of view in degrees (editor path only).
    :param location: Optional [x, y, z] world location for the capture camera
        (editor path only). Defaults to the editor viewport camera location.
    :param rotation: Optional [pitch, yaw, roll] degrees for the capture camera
        (editor path only). Defaults to the editor viewport camera rotation.
    """
    import unreal
    import os
    import datetime

    editor_sub = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    level_editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)

    # Resolve the default output path: timestamped file in Saved/Screenshots.
    if output_path is None:
        shot_dir = os.path.join(unreal.Paths.project_saved_dir(), "Screenshots")
        os.makedirs(shot_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(shot_dir, "MCA_Capture_{}.png".format(stamp))

    out_dir = os.path.dirname(output_path)
    out_name = os.path.basename(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # Delete any stale file so existence is an unambiguous "capture done" signal.
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError:
            pass

    # --- PIE / Simulate path: async high-res screenshot of the game viewport ---
    if level_editor.is_in_play_in_editor():
        # Cannot render synchronously here — the game thread is busy with THIS
        # call, so capture_scene/spawn would not tick. Request the async grab;
        # the caller reads the path on the next round-trip.
        unreal.AutomationLibrary.take_high_res_screenshot(int(width), int(height), output_path)
        return {
            "success": True,
            "path": output_path,
            "synchronous": False,
            "pending": True,
            "mode": "pie_highres",
            "note": "PIE capture flushes on the next render tick — read 'path' on your next call.",
        }

    # --- Editor path: fully synchronous one-shot SceneCapture2D ---
    actor_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    world = editor_sub.get_editor_world()
    if world is None:
        return {"success": False, "message": "No editor world available and not in PIE."}

    # Resolve the capture transform: explicit args win, else the live viewport camera.
    cam_loc, cam_rot = editor_sub.get_level_viewport_camera_info()
    if location is not None:
        cam_loc = unreal.Vector(location[0], location[1], location[2])
    if rotation is not None:
        cam_rot = unreal.Rotator(rotation[0], rotation[1], rotation[2])

    # An 8-bit (RTF_RGBA8) target is REQUIRED so export writes a real PNG — a
    # float target (the create_render_target2d default) writes EXR bytes into a
    # .png and yields an unreadable file.
    render_target = unreal.RenderingLibrary.create_render_target2d(
        world, int(width), int(height), unreal.TextureRenderTargetFormat.RTF_RGBA8)

    # Spawn a transient SceneCapture2D at the chosen transform.
    capture_actor = actor_sub.spawn_actor_from_class(unreal.SceneCapture2D, cam_loc, cam_rot)
    try:
        component = capture_actor.capture_component2d
        # Final tonemapped LDR color so the PNG looks like the viewport.
        component.capture_source = unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR
        component.texture_target = render_target
        component.fov_angle = float(fov)
        # One-shot only — do not keep re-rendering every frame.
        component.set_editor_property("capture_every_frame", False)
        component.set_editor_property("capture_on_movement", False)

        # Force a synchronous render of this single capture.
        component.capture_scene()

        # Write the render target to disk (synchronous).
        unreal.RenderingLibrary.export_render_target(world, render_target, out_dir, out_name)
    finally:
        # Always clean up the temporary capture actor.
        actor_sub.destroy_actor(capture_actor)

    exists = os.path.exists(output_path)
    return {
        "success": exists,
        "path": output_path,
        "synchronous": True,
        "mode": "editor_scenecapture",
        "width": int(width),
        "height": int(height),
        "size_bytes": os.path.getsize(output_path) if exists else 0,
    }
