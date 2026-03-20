def select_actors(actor_names: list):
    """Set the editor selection to the specified actors by label.

    :param actor_names: List of actor label names to select.
    """
    import unreal

    selected = []
    not_found = []

    # Clear current selection.
    unreal.EditorLevelLibrary.set_selected_level_actors([])

    # Find actors by label and select them.
    all_actors = unreal.EditorLevelLibrary.get_all_level_actors()
    actors_to_select = []

    for name in actor_names:
        found = False
        for actor in all_actors:
            if actor.get_actor_label() == name:
                actors_to_select.append(actor)
                selected.append(name)
                found = True
                break
        if not found:
            not_found.append(name)

    # Set the selection.
    if actors_to_select:
        unreal.EditorLevelLibrary.set_selected_level_actors(actors_to_select)

    return {
        "success": len(not_found) == 0,
        "selected": selected,
        "not_found": not_found,
    }
