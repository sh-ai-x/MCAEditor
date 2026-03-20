def assign_material(actor_name: str, material_path: str, slot: int = 0):
    """Assign a material to an actor's mesh component.

    :param actor_name: The display label of the target actor.
    :param material_path: Content path to the material asset.
    :param slot: Material slot index (default: 0).
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

    # Load the material.
    material = unreal.EditorAssetLibrary.load_asset(material_path)
    if material is None:
        return {
            "success": False,
            "message": "Material '{}' not found.".format(material_path),
        }

    # Find the static mesh component on the actor.
    components = target.get_components_by_class(unreal.StaticMeshComponent)
    if not components:
        components = target.get_components_by_class(unreal.MeshComponent)

    if not components:
        return {
            "success": False,
            "message": "No mesh component found on actor '{}'.".format(actor_name),
        }

    # Set the material on the first mesh component.
    mesh_comp = components[0]
    mesh_comp.set_material(slot, material)

    return {
        "success": True,
        "actor": actor_name,
        "material": material_path,
        "slot": slot,
    }
