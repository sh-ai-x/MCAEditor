def viewport_focus(actor_name: str):
    """Focus the editor viewport on a specific actor.

    :param actor_name: The display label of the actor to focus on.
    """
    import unreal

    # Find the actor by label.
    all_actors = unreal.EditorLevelLibrary.get_all_level_actors()
    target = None
    for actor in all_actors:
        if actor.get_actor_label() == actor_name:
            target = actor
            break

    if target is None:
        return {
            "success": False,
            "message": "Actor '{}' not found.".format(actor_name),
        }

    # Select and focus on the actor.
    unreal.EditorLevelLibrary.set_selected_level_actors([target])

    # Use the level editor subsystem to focus the viewport.
    subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if subsystem:
        subsystem.pilot_level_actor(target)

    return {
        "success": True,
        "actor": actor_name,
    }
