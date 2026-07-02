# Auto-generated MCAUnrealMCP tool. Runs inside UE via Remote Execution.

def bp_add_interface_message_node(asset_path: str, interface_class: str, function_name: str, graph_name: str = ""):
    """Add an interface MESSAGE call node (UK2Node_Message) to a Blueprint graph.

    Message nodes call an interface function on ANY object reference and no-op
    when the target doesn't implement the interface — the decoupled dispatch the
    editor creates when you drag off an untyped reference.

    :param asset_path: Content path to the Blueprint to modify.
    :param interface_class: Interface asset path ("/Game/.../BPI_X"), "/Script/..." path, or bare name.
    :param function_name: Interface function to call.
    :param graph_name: Target graph; empty = the main EventGraph.
    """
    import unreal

    if not hasattr(unreal, "MCAEventGraphLibrary"):
        return {"success": False, "message": "MCAEditorScripting plugin not enabled."}
    if not hasattr(unreal.MCAEventGraphLibrary, "add_interface_message_node"):
        return {"success": False, "message": "MCAEditorScripting plugin too old — rebuild for add_interface_message_node."}
    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        return {"success": False, "message": "Blueprint not found at '{}'.".format(asset_path)}

    node_id = unreal.MCAEventGraphLibrary.add_interface_message_node(bp, interface_class, function_name, graph_name)
    return {"success": bool(node_id), "node_id": str(node_id)}
