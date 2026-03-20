def delete_actors(actor_names: list):
    """Delete actors from the current level by their display label.

    :param actor_names: List of actor label names to delete.
    """
    import unreal

    deleted = []
    not_found = []

    # Get all actors and match by label.
    all_actors = unreal.EditorLevelLibrary.get_all_level_actors()

    for name in actor_names:
        found = False
        for actor in all_actors:
            if actor.get_actor_label() == name:
                actor.destroy_actor()
                deleted.append(name)
                found = True
                break
        if not found:
            not_found.append(name)

    return {
        "success": len(not_found) == 0,
        "deleted": deleted,
        "not_found": not_found,
    }
