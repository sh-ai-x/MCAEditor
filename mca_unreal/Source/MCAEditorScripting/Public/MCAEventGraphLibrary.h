// MCA Event Graph Library — Public API header.
//
// Exposes Blueprint EventGraph node creation and pin wiring to Python.
// These functions let you programmatically add event nodes, function calls,
// casts, variable get/set nodes, and wire them together — operations that
// are normally only possible through the visual Blueprint editor.
//
// Node IDs are returned as FString (the node's FGuid serialized) so
// Python callers can reference nodes when connecting pins.
//
// All functions are static BlueprintCallable, so they appear in Python as:
//   unreal.MCAEventGraphLibrary.add_event_node(...)
//   unreal.MCAEventGraphLibrary.connect_pins(...)

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "MCAEventGraphLibrary.generated.h"

class UBlueprint;

/**
 * Static library of Blueprint EventGraph editing functions.
 *
 * Enables programmatic construction of Blueprint event graphs —
 * adding event nodes, function calls, casts, variable accessors,
 * and wiring them together via pin connections.
 *
 * All write operations are wrapped in FScopedTransaction for Ctrl+Z
 * undo support.  Node IDs are FGuid strings for cross-call reference.
 */
UCLASS()
class MCAEDITORSCRIPTING_API UMCAEventGraphLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:

	// --- Node Creation --------------------------------------------------------

	/**
	 * Add an event node to the Blueprint's EventGraph.
	 *
	 * Creates a UK2Node_Event for built-in events like
	 * "BlueprintInitializeAnimation" or "ReceiveBeginPlay".
	 *
	 * @param Blueprint   The Blueprint to modify.
	 * @param EventName   Name of the event (e.g. "BlueprintInitializeAnimation").
	 * @return Node ID string (FGuid), or empty on failure.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Event Graph",
		meta = (DisplayName = "Add Event Node"))
	static FString AddEventNode(
		UBlueprint* Blueprint,
		const FString& EventName
	);

	/**
	 * Add a function call node to the EventGraph.
	 *
	 * Creates a UK2Node_CallFunction.  If TargetClass is specified, the
	 * function is looked up on that class; otherwise on the Blueprint's
	 * generated class and its parents.
	 *
	 * @param Blueprint     The Blueprint to modify.
	 * @param FunctionName  Name of the function to call (e.g. "GetVelocity").
	 * @param TargetClass   Optional class name to search (e.g. "CharacterMovementComponent").
	 * @return Node ID string, or empty on failure.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Event Graph",
		meta = (DisplayName = "Add Function Call Node"))
	static FString AddFunctionCallNode(
		UBlueprint* Blueprint,
		const FString& FunctionName,
		const FString& TargetClass = ""
	);

	/**
	 * Add a Cast node to the EventGraph.
	 *
	 * Creates a UK2Node_DynamicCast that casts to the given class.
	 *
	 * @param Blueprint        The Blueprint to modify.
	 * @param TargetClassName  Class to cast to (e.g. "BP_MyCharacter" or "/Game/BP_MyCharacter.BP_MyCharacter_C").
	 * @return Node ID string, or empty on failure.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Event Graph",
		meta = (DisplayName = "Add Cast Node"))
	static FString AddCastNode(
		UBlueprint* Blueprint,
		const FString& TargetClassName
	);

	/**
	 * Add a variable GET node to the EventGraph.
	 *
	 * @param Blueprint  The Blueprint to modify.
	 * @param VarName    Name of the Blueprint variable.
	 * @return Node ID string, or empty on failure.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Event Graph",
		meta = (DisplayName = "Add Variable Get Node"))
	static FString AddVariableGetNode(
		UBlueprint* Blueprint,
		const FString& VarName
	);

	/**
	 * Add a variable SET node to the EventGraph.
	 *
	 * @param Blueprint  The Blueprint to modify.
	 * @param VarName    Name of the Blueprint variable.
	 * @return Node ID string, or empty on failure.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Event Graph",
		meta = (DisplayName = "Add Variable Set Node"))
	static FString AddVariableSetNode(
		UBlueprint* Blueprint,
		const FString& VarName
	);

	// --- Variable Management --------------------------------------------------

	/**
	 * Add a member variable to a Blueprint.
	 *
	 * Creates a new Blueprint member variable of the given primitive type and,
	 * optionally, marks it Instance Editable (the per-instance "eye" toggle).
	 *
	 * This exists because constructing an FEdGraphPinType from UE's Python
	 * bindings is broken in 5.8 — the pin-type build must happen in C++.
	 *
	 * @param Blueprint         The Blueprint to modify (e.g. a pawn like BP_Notera).
	 * @param VariableName      Name for the new variable (e.g. "IsSitting").
	 * @param PinCategory       Primitive type: "bool", "int", "float", "string", or "name".
	 * @param bInstanceEditable If true, the variable is editable per-instance in the details panel.
	 * @return True if the variable was created.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Event Graph",
		meta = (DisplayName = "Add Member Variable"))
	static bool AddMemberVariable(
		UBlueprint* Blueprint,
		const FString& VariableName,
		const FString& PinCategory,
		bool bInstanceEditable = true
	);

	/**
	 * List a Blueprint's member variables (the read-back for AddMemberVariable).
	 *
	 * Each entry is formatted "Name|Type|InstanceEditable" — e.g.
	 * "IsSitting|bool|true". This works around the 5.8 issue where the stock
	 * list_blueprint_variables path returns nothing for graph Blueprints; it
	 * reads the Blueprint's NewVariables descriptions directly in C++.
	 *
	 * @param Blueprint  The Blueprint to inspect.
	 * @param OutVars    Output array of "Name|Type|InstanceEditable" strings.
	 * @return True if the Blueprint was valid and inspected.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Event Graph",
		meta = (DisplayName = "List Member Variables"))
	static bool ListMemberVariables(
		UBlueprint* Blueprint,
		TArray<FString>& OutVars
	);

	/**
	 * Make a Blueprint implement an interface.
	 *
	 * This is the one Blueprint-authoring operation with no stock Python path —
	 * a Blueprint's ImplementedInterfaces array is protected and the descriptor
	 * struct is not exposed to Python. Resolves the interface class by full path
	 * ("/Script/Module.UMyInterface"), by name ("MyInterface"), or by U-prefixed
	 * name ("UMyInterface"), then adds it via
	 * FBlueprintEditorUtils::ImplementNewInterface and marks the Blueprint
	 * structurally modified. Idempotent — already-implemented returns true.
	 *
	 * After this call, the interface's BlueprintImplementableEvent functions are
	 * overridable on the Blueprint (add_event_override / add_function_override).
	 *
	 * @param Blueprint       The Blueprint to modify (e.g. a pawn like BP_Notera).
	 * @param InterfaceClass  Path or name of the interface class to implement.
	 * @return True if the interface was added or was already implemented.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Event Graph",
		meta = (DisplayName = "Implement Interface"))
	static bool ImplementInterface(
		UBlueprint* Blueprint,
		const FString& InterfaceClass
	);

	/**
	 * Remove an interface a Blueprint implements — the counterpart to
	 * ImplementInterface.
	 *
	 * Like ImplementInterface, this has no stock Python path: the Blueprint's
	 * ImplementedInterfaces array is protected and FBlueprintEditorUtils is C++
	 * only. Resolves the interface class by full path
	 * ("/Script/Module.UMyInterface"), by name ("MyInterface"), or by U-prefixed
	 * name ("UMyInterface"), then removes it via
	 * FBlueprintEditorUtils::RemoveInterface and marks the Blueprint structurally
	 * modified. The interface's implementing function graphs are dropped along
	 * with it (bPreserveFunctions = false). Idempotent — if the Blueprint does
	 * not implement the interface, returns true.
	 *
	 * @param Blueprint       The Blueprint to modify (e.g. a waypoint like CBP_Sitting).
	 * @param InterfaceClass  Path or name of the interface class to remove.
	 * @return True if the interface was removed or was already absent.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Event Graph",
		meta = (DisplayName = "Remove Interface"))
	static bool RemoveInterface(
		UBlueprint* Blueprint,
		const FString& InterfaceClass
	);

	/**
	 * Compile a Blueprint and return the compiler's ACTUAL messages.
	 *
	 * The stock Python path (BlueprintEditorLibrary.compile_blueprint) returns
	 * nothing, so callers can only read a coarse pass/fail status enum and never
	 * see WHY a Blueprint failed. This routes the compile through an
	 * FCompilerResultsLog and returns every tokenized message as text, so an
	 * agent can read the real error (e.g. "A node named 'Box' already exists")
	 * instead of guessing.
	 *
	 * The returned array's first entry is always a summary line of the form
	 * "SUMMARY: errors=N warnings=M". Each remaining entry is one compiler
	 * message tagged by severity: "ERROR: ...", "WARNING: ...", or "NOTE: ...".
	 * A clean compile returns just the summary with errors=0.
	 *
	 * @param Blueprint  The Blueprint to compile.
	 * @return Summary line followed by one tagged line per compiler message.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Event Graph",
		meta = (DisplayName = "Compile Blueprint With Messages"))
	static TArray<FString> CompileBlueprintWithMessages(
		UBlueprint* Blueprint
	);

	// --- Pin Wiring -----------------------------------------------------------

	/**
	 * Connect two pins between nodes in the EventGraph.
	 *
	 * Works for both execution (exec) pins and data pins.  Pin names
	 * follow UE conventions: "execute", "then", "ReturnValue", etc.
	 * Use GetNodePins() to discover available pin names.
	 *
	 * @param Blueprint      The Blueprint containing the nodes.
	 * @param SourceNodeId   Node ID of the source node.
	 * @param SourcePinName  Name of the output pin on the source.
	 * @param TargetNodeId   Node ID of the target node.
	 * @param TargetPinName  Name of the input pin on the target.
	 * @return True if the connection was made successfully.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Event Graph",
		meta = (DisplayName = "Connect Pins"))
	static bool ConnectPins(
		UBlueprint* Blueprint,
		const FString& SourceNodeId,
		const FString& SourcePinName,
		const FString& TargetNodeId,
		const FString& TargetPinName
	);

	// --- Introspection --------------------------------------------------------

	/**
	 * List all pins on a node.
	 *
	 * Returns an array of strings in the format "PinName|Direction|Type"
	 * where Direction is "Input" or "Output" and Type is the pin category
	 * (e.g. "exec", "bool", "float", "object").
	 *
	 * @param Blueprint  The Blueprint containing the node.
	 * @param NodeId     Node ID to inspect.
	 * @return Array of "PinName|Direction|Type" strings.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Event Graph",
		meta = (DisplayName = "Get Node Pins"))
	static TArray<FString> GetNodePins(
		UBlueprint* Blueprint,
		const FString& NodeId
	);

	/**
	 * List all nodes in the Blueprint's EventGraph.
	 *
	 * Returns an array of strings in the format "NodeId|ClassName|Title".
	 *
	 * @param Blueprint  The Blueprint to inspect.
	 * @return Array of "NodeId|ClassName|Title" strings.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Event Graph",
		meta = (DisplayName = "List Event Graph Nodes"))
	static TArray<FString> ListEventGraphNodes(UBlueprint* Blueprint);

	/**
	 * Set the position of a node in the EventGraph.
	 *
	 * Useful for clean layout of programmatically created graphs.
	 *
	 * @param Blueprint  The Blueprint containing the node.
	 * @param NodeId     Node ID to reposition.
	 * @param X          Horizontal position.
	 * @param Y          Vertical position.
	 * @return True if the node was found and repositioned.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Event Graph",
		meta = (DisplayName = "Set Node Position"))
	static bool SetNodePosition(
		UBlueprint* Blueprint,
		const FString& NodeId,
		float X,
		float Y
	);

private:

	// --- Internal Helpers -----------------------------------------------------

	/** Get the main EventGraph (first UbergraphPage) from a Blueprint. */
	static UEdGraph* GetEventGraph(UBlueprint* Blueprint);

	/** Find a node in the EventGraph by its GUID string. */
	static UEdGraphNode* FindNodeById(UEdGraph* Graph, const FString& NodeId);

	/** Find a pin on a node by name, with flexible matching. */
	static UEdGraphPin* FindPinByName(UEdGraphNode* Node, const FString& PinName, EEdGraphPinDirection Direction = EGPD_MAX);

	/** Convert a node's GUID to a string for Python callers. */
	static FString NodeIdToString(UEdGraphNode* Node);
};
