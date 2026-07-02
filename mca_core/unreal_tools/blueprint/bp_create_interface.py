# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def bp_create_interface(package_path: str, asset_name: str):
    """Create a Blueprint Interface asset (BPTYPE_Interface).

    Interfaces are the decoupled contract between Blueprints (e.g. a waypoint
    interaction contract) — there is no stock Python path to create one.
    Idempotent: an existing interface at the path returns success.

    :param package_path: Content folder (e.g. "/Game/BotTown/Interaction").
    :param asset_name: Asset name (e.g. "BPI_WaypointInteraction").
    """
    import unreal

    if not hasattr(unreal, "MCAEventGraphLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    if not hasattr(unreal.MCAEventGraphLibrary, "create_blueprint_interface"):
        return {"success": False, "message": "MCAEditorScripting plugin too old — rebuild for create_blueprint_interface."}

    path = unreal.MCAEventGraphLibrary.create_blueprint_interface(package_path, asset_name)
    return {"success": bool(path), "path": str(path)}
