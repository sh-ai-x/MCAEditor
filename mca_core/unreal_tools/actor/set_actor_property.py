def set_actor_property(actor_name: str, property_name: str, value: str):
    """Set a property on an actor by name.

    Uses UE's property system to set exposed UPROPERTY values.
    The value is passed as a string and UE handles type conversion.

    :param actor_name: The display label of the actor.
    :param property_name: The property name to set.
    :param value: The value as a string representation.
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

    # Try to set the property using set_editor_property.
    try:
        target.set_editor_property(property_name, value)
        return {
            "success": True,
            "actor": actor_name,
            "property": property_name,
            "value": str(value),
        }
    except Exception as e:
        return {
            "success": False,
            "message": "Failed to set property '{}' on '{}': {}".format(
                property_name, actor_name, str(e)
            ),
        }
