// MCA Event Graph Library — Implementation.
//
// Implements EventGraph node creation and pin wiring for Blueprint
// automation.  All functions operate on the Blueprint's first
// UbergraphPage (the main EventGraph).
//
// Key patterns:
//   - FScopedTransaction for undo support
//   - FGraphNodeCreator<T> for proper node lifecycle
//   - FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified() after changes
//   - Node IDs are FGuid strings for stable cross-call references
//   - Pin lookup is flexible: tries exact match, then case-insensitive,
//     then friendly name fallback

#include "MCAEventGraphLibrary.h"
#include "MCAEditorScriptingModule.h"

#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphNode.h"
#include "EdGraph/EdGraphPin.h"
#include "EdGraphSchema_K2.h"

#include "K2Node_Event.h"
#include "K2Node_CallFunction.h"
#include "K2Node_DynamicCast.h"
#include "K2Node_VariableGet.h"
#include "K2Node_VariableSet.h"

#include "Engine/Blueprint.h"
#include "Kismet2/BlueprintEditorUtils.h"
#include "Kismet2/KismetEditorUtilities.h"
#include "Kismet2/CompilerResultsLog.h"
#include "Logging/TokenizedMessage.h"
#include "ScopedTransaction.h"

#include "UObject/UObjectIterator.h"


// =============================================================================
// Internal Helpers
// =============================================================================

UEdGraph* UMCAEventGraphLibrary::GetEventGraph(UBlueprint* Blueprint)
{
	if (!Blueprint)
	{
		return nullptr;
	}

	// The main EventGraph is the first entry in UbergraphPages.
	if (Blueprint->UbergraphPages.Num() > 0)
	{
		return Blueprint->UbergraphPages[0];
	}

	UE_LOG(LogMCAScripting, Warning, TEXT("GetEventGraph: Blueprint '%s' has no UbergraphPages"),
		*Blueprint->GetName());
	return nullptr;
}

UEdGraphNode* UMCAEventGraphLibrary::FindNodeById(UEdGraph* Graph, const FString& NodeId)
{
	if (!Graph)
	{
		return nullptr;
	}

	// Parse the string back to a GUID.
	FGuid TargetGuid;
	if (!FGuid::Parse(NodeId, TargetGuid))
	{
		UE_LOG(LogMCAScripting, Error, TEXT("FindNodeById: Invalid GUID string '%s'"), *NodeId);
		return nullptr;
	}

	for (UEdGraphNode* Node : Graph->Nodes)
	{
		if (Node && Node->NodeGuid == TargetGuid)
		{
			return Node;
		}
	}

	UE_LOG(LogMCAScripting, Warning, TEXT("FindNodeById: No node with ID '%s' in graph '%s'"),
		*NodeId, *Graph->GetName());
	return nullptr;
}

UEdGraphPin* UMCAEventGraphLibrary::FindPinByName(
	UEdGraphNode* Node,
	const FString& PinName,
	EEdGraphPinDirection Direction)
{
	if (!Node)
	{
		return nullptr;
	}

	// Phase 1: Exact match on pin name (with optional direction filter).
	for (UEdGraphPin* Pin : Node->Pins)
	{
		if (!Pin) continue;
		if (Direction != EGPD_MAX && Pin->Direction != Direction) continue;

		if (Pin->PinName.ToString() == PinName)
		{
			return Pin;
		}
	}

	// Phase 2: Case-insensitive match.
	for (UEdGraphPin* Pin : Node->Pins)
	{
		if (!Pin) continue;
		if (Direction != EGPD_MAX && Pin->Direction != Direction) continue;

		if (Pin->PinName.ToString().Equals(PinName, ESearchCase::IgnoreCase))
		{
			return Pin;
		}
	}

	// Phase 3: Match against friendly display name.
	for (UEdGraphPin* Pin : Node->Pins)
	{
		if (!Pin) continue;
		if (Direction != EGPD_MAX && Pin->Direction != Direction) continue;

		FText DisplayName = Pin->GetDisplayName();
		if (DisplayName.ToString().Equals(PinName, ESearchCase::IgnoreCase))
		{
			return Pin;
		}
	}

	return nullptr;
}

FString UMCAEventGraphLibrary::NodeIdToString(UEdGraphNode* Node)
{
	if (!Node)
	{
		return FString();
	}
	return Node->NodeGuid.ToString();
}


// =============================================================================
// AddEventNode
// =============================================================================

FString UMCAEventGraphLibrary::AddEventNode(
	UBlueprint* Blueprint,
	const FString& EventName)
{
	if (!Blueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddEventNode: Blueprint is null"));
		return FString();
	}

	UEdGraph* EventGraph = GetEventGraph(Blueprint);
	if (!EventGraph)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddEventNode: No EventGraph found"));
		return FString();
	}

	// Find the function this event corresponds to.
	// Search the generated class hierarchy for the event function.
	UClass* BPClass = Blueprint->GeneratedClass;
	if (!BPClass)
	{
		BPClass = Blueprint->ParentClass;
	}

	UFunction* EventFunc = nullptr;
	if (BPClass)
	{
		EventFunc = BPClass->FindFunctionByName(FName(*EventName));
	}

	if (!EventFunc)
	{
		UE_LOG(LogMCAScripting, Error,
			TEXT("AddEventNode: Could not find event function '%s' on class '%s'"),
			*EventName, BPClass ? *BPClass->GetName() : TEXT("null"));
		return FString();
	}

	FScopedTransaction Transaction(FText::FromString(
		FString::Printf(TEXT("MCA: Add Event '%s'"), *EventName)));

	// Create the event node using FGraphNodeCreator.
	FGraphNodeCreator<UK2Node_Event> NodeCreator(*EventGraph);
	UK2Node_Event* EventNode = NodeCreator.CreateNode(true);

	// Configure the event reference.
	EventNode->EventReference.SetExternalMember(FName(*EventName), BPClass);
	EventNode->bOverrideFunction = true;

	NodeCreator.Finalize();

	FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);

	FString NodeId = NodeIdToString(EventNode);
	UE_LOG(LogMCAScripting, Log, TEXT("AddEventNode: Created '%s' -> %s"), *EventName, *NodeId);
	return NodeId;
}


// =============================================================================
// AddFunctionCallNode
// =============================================================================

FString UMCAEventGraphLibrary::AddFunctionCallNode(
	UBlueprint* Blueprint,
	const FString& FunctionName,
	const FString& TargetClass)
{
	if (!Blueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddFunctionCallNode: Blueprint is null"));
		return FString();
	}

	UEdGraph* EventGraph = GetEventGraph(Blueprint);
	if (!EventGraph)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddFunctionCallNode: No EventGraph found"));
		return FString();
	}

	// Determine which class to search for the function.
	UClass* SearchClass = nullptr;

	if (!TargetClass.IsEmpty())
	{
		// Try to find the class by name.  Supports short names and full paths.
		SearchClass = FindFirstObject<UClass>( *TargetClass);
		if (!SearchClass)
		{
			// Try loading it as an asset path.
			SearchClass = LoadObject<UClass>(nullptr, *TargetClass);
		}
		if (!SearchClass)
		{
			// Try common engine class naming: add "U" or "A" prefix.
			SearchClass = FindFirstObject<UClass>( *(FString("U") + TargetClass));
			if (!SearchClass)
			{
				SearchClass = FindFirstObject<UClass>( *(FString("A") + TargetClass));
			}
		}
	}

	if (!SearchClass)
	{
		// Fall back to the Blueprint's generated class hierarchy.
		SearchClass = Blueprint->GeneratedClass ? Blueprint->GeneratedClass : Blueprint->ParentClass;
	}

	if (!SearchClass)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddFunctionCallNode: No valid class to search"));
		return FString();
	}

	// Find the function.
	UFunction* Func = SearchClass->FindFunctionByName(FName(*FunctionName));
	if (!Func)
	{
		// Search up the hierarchy explicitly.
		for (UClass* Super = SearchClass->GetSuperClass(); Super; Super = Super->GetSuperClass())
		{
			Func = Super->FindFunctionByName(FName(*FunctionName));
			if (Func) break;
		}
	}

	if (!Func)
	{
		UE_LOG(LogMCAScripting, Error,
			TEXT("AddFunctionCallNode: Function '%s' not found on '%s' or parents"),
			*FunctionName, *SearchClass->GetName());
		return FString();
	}

	FScopedTransaction Transaction(FText::FromString(
		FString::Printf(TEXT("MCA: Add Call '%s'"), *FunctionName)));

	FGraphNodeCreator<UK2Node_CallFunction> NodeCreator(*EventGraph);
	UK2Node_CallFunction* CallNode = NodeCreator.CreateNode(true);
	CallNode->SetFromFunction(Func);
	NodeCreator.Finalize();

	FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);

	FString NodeId = NodeIdToString(CallNode);
	UE_LOG(LogMCAScripting, Log, TEXT("AddFunctionCallNode: Created call to '%s' -> %s"),
		*FunctionName, *NodeId);
	return NodeId;
}


// =============================================================================
// AddCastNode
// =============================================================================

FString UMCAEventGraphLibrary::AddCastNode(
	UBlueprint* Blueprint,
	const FString& TargetClassName)
{
	if (!Blueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddCastNode: Blueprint is null"));
		return FString();
	}

	UEdGraph* EventGraph = GetEventGraph(Blueprint);
	if (!EventGraph)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddCastNode: No EventGraph found"));
		return FString();
	}

	// Resolve the target class.  Try direct lookup, then with U/A prefix,
	// then as an asset path (for Blueprint-generated classes).
	UClass* CastClass = FindFirstObject<UClass>( *TargetClassName);
	if (!CastClass)
	{
		CastClass = FindFirstObject<UClass>( *(FString("U") + TargetClassName));
	}
	if (!CastClass)
	{
		CastClass = FindFirstObject<UClass>( *(FString("A") + TargetClassName));
	}
	if (!CastClass)
	{
		// Try loading as a Blueprint asset — the _C suffix class.
		FString ClassPath = TargetClassName;
		if (!ClassPath.EndsWith("_C"))
		{
			ClassPath += "_C";
		}
		CastClass = LoadObject<UClass>(nullptr, *ClassPath);
	}

	if (!CastClass)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddCastNode: Could not resolve class '%s'"),
			*TargetClassName);
		return FString();
	}

	FScopedTransaction Transaction(FText::FromString(
		FString::Printf(TEXT("MCA: Add Cast to '%s'"), *TargetClassName)));

	FGraphNodeCreator<UK2Node_DynamicCast> NodeCreator(*EventGraph);
	UK2Node_DynamicCast* CastNode = NodeCreator.CreateNode(true);
	CastNode->TargetType = CastClass;
	NodeCreator.Finalize();

	FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);

	FString NodeId = NodeIdToString(CastNode);
	UE_LOG(LogMCAScripting, Log, TEXT("AddCastNode: Created cast to '%s' -> %s"),
		*CastClass->GetName(), *NodeId);
	return NodeId;
}


// =============================================================================
// AddVariableGetNode
// =============================================================================

FString UMCAEventGraphLibrary::AddVariableGetNode(
	UBlueprint* Blueprint,
	const FString& VarName)
{
	if (!Blueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddVariableGetNode: Blueprint is null"));
		return FString();
	}

	UEdGraph* EventGraph = GetEventGraph(Blueprint);
	if (!EventGraph)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddVariableGetNode: No EventGraph found"));
		return FString();
	}

	FScopedTransaction Transaction(FText::FromString(
		FString::Printf(TEXT("MCA: Add Get '%s'"), *VarName)));

	FGraphNodeCreator<UK2Node_VariableGet> NodeCreator(*EventGraph);
	UK2Node_VariableGet* GetNode = NodeCreator.CreateNode(true);

	// Set the variable reference to point at this Blueprint's variable.
	GetNode->VariableReference.SetSelfMember(FName(*VarName));

	NodeCreator.Finalize();

	FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);

	FString NodeId = NodeIdToString(GetNode);
	UE_LOG(LogMCAScripting, Log, TEXT("AddVariableGetNode: Created GET '%s' -> %s"),
		*VarName, *NodeId);
	return NodeId;
}


// =============================================================================
// AddVariableSetNode
// =============================================================================

FString UMCAEventGraphLibrary::AddVariableSetNode(
	UBlueprint* Blueprint,
	const FString& VarName)
{
	if (!Blueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddVariableSetNode: Blueprint is null"));
		return FString();
	}

	UEdGraph* EventGraph = GetEventGraph(Blueprint);
	if (!EventGraph)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddVariableSetNode: No EventGraph found"));
		return FString();
	}

	FScopedTransaction Transaction(FText::FromString(
		FString::Printf(TEXT("MCA: Add Set '%s'"), *VarName)));

	FGraphNodeCreator<UK2Node_VariableSet> NodeCreator(*EventGraph);
	UK2Node_VariableSet* SetNode = NodeCreator.CreateNode(true);

	// Set the variable reference to point at this Blueprint's variable.
	SetNode->VariableReference.SetSelfMember(FName(*VarName));

	NodeCreator.Finalize();

	FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);

	FString NodeId = NodeIdToString(SetNode);
	UE_LOG(LogMCAScripting, Log, TEXT("AddVariableSetNode: Created SET '%s' -> %s"),
		*VarName, *NodeId);
	return NodeId;
}


// =============================================================================
// ConnectPins
// =============================================================================

bool UMCAEventGraphLibrary::ConnectPins(
	UBlueprint* Blueprint,
	const FString& SourceNodeId,
	const FString& SourcePinName,
	const FString& TargetNodeId,
	const FString& TargetPinName)
{
	if (!Blueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("ConnectPins: Blueprint is null"));
		return false;
	}

	UEdGraph* EventGraph = GetEventGraph(Blueprint);
	if (!EventGraph)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("ConnectPins: No EventGraph found"));
		return false;
	}

	// Find both nodes.
	UEdGraphNode* SourceNode = FindNodeById(EventGraph, SourceNodeId);
	UEdGraphNode* TargetNode = FindNodeById(EventGraph, TargetNodeId);

	if (!SourceNode)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("ConnectPins: Source node '%s' not found"), *SourceNodeId);
		return false;
	}
	if (!TargetNode)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("ConnectPins: Target node '%s' not found"), *TargetNodeId);
		return false;
	}

	// Find pins — source should be an output, target should be an input.
	UEdGraphPin* SourcePin = FindPinByName(SourceNode, SourcePinName, EGPD_Output);
	if (!SourcePin)
	{
		// Fallback: try without direction constraint (some pins are flexible).
		SourcePin = FindPinByName(SourceNode, SourcePinName);
	}

	UEdGraphPin* TargetPin = FindPinByName(TargetNode, TargetPinName, EGPD_Input);
	if (!TargetPin)
	{
		TargetPin = FindPinByName(TargetNode, TargetPinName);
	}

	if (!SourcePin)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("ConnectPins: Pin '%s' not found on source node"),
			*SourcePinName);
		return false;
	}
	if (!TargetPin)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("ConnectPins: Pin '%s' not found on target node"),
			*TargetPinName);
		return false;
	}

	FScopedTransaction Transaction(FText::FromString(TEXT("MCA: Connect Pins")));

	// Use the K2 schema to make the connection.
	const UEdGraphSchema_K2* Schema = GetDefault<UEdGraphSchema_K2>();
	bool bSuccess = Schema->TryCreateConnection(SourcePin, TargetPin);

	if (bSuccess)
	{
		FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
		UE_LOG(LogMCAScripting, Log, TEXT("ConnectPins: Connected %s.%s -> %s.%s"),
			*SourceNode->GetNodeTitle(ENodeTitleType::ListView).ToString(),
			*SourcePinName,
			*TargetNode->GetNodeTitle(ENodeTitleType::ListView).ToString(),
			*TargetPinName);
	}
	else
	{
		UE_LOG(LogMCAScripting, Error, TEXT("ConnectPins: Failed to connect %s.%s -> %s.%s"),
			*SourcePinName, *SourceNodeId, *TargetPinName, *TargetNodeId);
	}

	return bSuccess;
}


// =============================================================================
// GetNodePins
// =============================================================================

TArray<FString> UMCAEventGraphLibrary::GetNodePins(
	UBlueprint* Blueprint,
	const FString& NodeId)
{
	TArray<FString> Result;

	if (!Blueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("GetNodePins: Blueprint is null"));
		return Result;
	}

	UEdGraph* EventGraph = GetEventGraph(Blueprint);
	if (!EventGraph)
	{
		return Result;
	}

	UEdGraphNode* Node = FindNodeById(EventGraph, NodeId);
	if (!Node)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("GetNodePins: Node '%s' not found"), *NodeId);
		return Result;
	}

	for (UEdGraphPin* Pin : Node->Pins)
	{
		if (!Pin) continue;

		// Skip hidden pins — they are not useful for scripted wiring.
		if (Pin->bHidden) continue;

		FString DirStr = (Pin->Direction == EGPD_Input) ? TEXT("Input") : TEXT("Output");
		FString TypeStr = Pin->PinType.PinCategory.ToString();

		// Format: "PinName|Direction|Type"
		Result.Add(FString::Printf(TEXT("%s|%s|%s"),
			*Pin->PinName.ToString(), *DirStr, *TypeStr));
	}

	return Result;
}


// =============================================================================
// ListEventGraphNodes
// =============================================================================

TArray<FString> UMCAEventGraphLibrary::ListEventGraphNodes(UBlueprint* Blueprint)
{
	TArray<FString> Result;

	if (!Blueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("ListEventGraphNodes: Blueprint is null"));
		return Result;
	}

	UEdGraph* EventGraph = GetEventGraph(Blueprint);
	if (!EventGraph)
	{
		return Result;
	}

	for (UEdGraphNode* Node : EventGraph->Nodes)
	{
		if (!Node) continue;

		FString NodeId = NodeIdToString(Node);
		FString ClassName = Node->GetClass()->GetName();
		FString Title = Node->GetNodeTitle(ENodeTitleType::ListView).ToString();

		// Format: "NodeId|ClassName|Title"
		Result.Add(FString::Printf(TEXT("%s|%s|%s"),
			*NodeId, *ClassName, *Title));
	}

	return Result;
}


// =============================================================================
// SetNodePosition
// =============================================================================

bool UMCAEventGraphLibrary::SetNodePosition(
	UBlueprint* Blueprint,
	const FString& NodeId,
	float X,
	float Y)
{
	if (!Blueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("SetNodePosition: Blueprint is null"));
		return false;
	}

	UEdGraph* EventGraph = GetEventGraph(Blueprint);
	if (!EventGraph)
	{
		return false;
	}

	UEdGraphNode* Node = FindNodeById(EventGraph, NodeId);
	if (!Node)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("SetNodePosition: Node '%s' not found"), *NodeId);
		return false;
	}

	Node->NodePosX = static_cast<int32>(X);
	Node->NodePosY = static_cast<int32>(Y);

	UE_LOG(LogMCAScripting, Log, TEXT("SetNodePosition: '%s' -> (%d, %d)"),
		*NodeId, Node->NodePosX, Node->NodePosY);
	return true;
}


// =============================================================================
// Variable Management
// =============================================================================

bool UMCAEventGraphLibrary::AddMemberVariable(
	UBlueprint* Blueprint,
	const FString& VariableName,
	const FString& PinCategory,
	bool bInstanceEditable)
{
	if (!Blueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddMemberVariable: Blueprint is null"));
		return false;
	}

	const FName VarFName(*VariableName);

	// Reject duplicates up front — AddMemberVariable would otherwise no-op.
	for (const FBPVariableDescription& ExistingVar : Blueprint->NewVariables)
	{
		if (ExistingVar.VarName == VarFName)
		{
			UE_LOG(LogMCAScripting, Warning,
				TEXT("AddMemberVariable: Variable '%s' already exists on '%s'"),
				*VariableName, *Blueprint->GetName());
			return false;
		}
	}

	// Build the pin type from the category string. This is the operation that
	// is broken from UE's Python bindings in 5.8 (FEdGraphPinType ctor), so it
	// has to be done here in C++.
	FEdGraphPinType PinType;
	PinType.PinSubCategory = NAME_None;
	PinType.PinSubCategoryObject = nullptr;
	PinType.ContainerType = EPinContainerType::None;

	const FString Cat = PinCategory.ToLower();
	if (Cat == TEXT("bool") || Cat == TEXT("boolean"))
	{
		PinType.PinCategory = UEdGraphSchema_K2::PC_Boolean;
	}
	else if (Cat == TEXT("int") || Cat == TEXT("integer"))
	{
		PinType.PinCategory = UEdGraphSchema_K2::PC_Int;
	}
	else if (Cat == TEXT("float") || Cat == TEXT("double") || Cat == TEXT("real"))
	{
		// UE5 stores floats as PC_Real with a Double sub-category.
		PinType.PinCategory = UEdGraphSchema_K2::PC_Real;
		PinType.PinSubCategory = UEdGraphSchema_K2::PC_Double;
	}
	else if (Cat == TEXT("string"))
	{
		PinType.PinCategory = UEdGraphSchema_K2::PC_String;
	}
	else if (Cat == TEXT("name"))
	{
		PinType.PinCategory = UEdGraphSchema_K2::PC_Name;
	}
	else
	{
		UE_LOG(LogMCAScripting, Error,
			TEXT("AddMemberVariable: Unsupported pin category '%s' (use bool/int/float/string/name)"),
			*PinCategory);
		return false;
	}

	FScopedTransaction Transaction(FText::FromString(
		FString::Printf(TEXT("MCA: Add Variable '%s'"), *VariableName)));

	// Default flags applied by AddMemberVariable are CPF_Edit | CPF_BlueprintVisible.
	const bool bAdded = FBlueprintEditorUtils::AddMemberVariable(Blueprint, VarFName, PinType);
	if (!bAdded)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddMemberVariable: Failed to add '%s' to '%s'"),
			*VariableName, *Blueprint->GetName());
		return false;
	}

	// "Instance Editable" in the details panel == the CPF_DisableEditOnInstance
	// flag being CLEARED. Set or clear it to match the request.
	for (FBPVariableDescription& Var : Blueprint->NewVariables)
	{
		if (Var.VarName == VarFName)
		{
			if (bInstanceEditable)
			{
				Var.PropertyFlags &= ~CPF_DisableEditOnInstance;
			}
			else
			{
				Var.PropertyFlags |= CPF_DisableEditOnInstance;
			}
			break;
		}
	}

	FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);

	UE_LOG(LogMCAScripting, Log,
		TEXT("AddMemberVariable: Added '%s' (%s, instance_editable=%s) to '%s'"),
		*VariableName, *PinCategory,
		bInstanceEditable ? TEXT("true") : TEXT("false"),
		*Blueprint->GetName());

	return true;
}


// =============================================================================
// Read-back: Member Variables
// =============================================================================

bool UMCAEventGraphLibrary::ListMemberVariables(
	UBlueprint* Blueprint,
	TArray<FString>& OutVars)
{
	OutVars.Empty();

	if (!Blueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("ListMemberVariables: Blueprint is null"));
		return false;
	}

	// Read the Blueprint's variable descriptions directly — the stock
	// list_blueprint_variables path returns nothing for graph BPs in 5.8.
	for (const FBPVariableDescription& Var : Blueprint->NewVariables)
	{
		// Type = pin category, plus sub-category for reals (e.g. real/double).
		FString TypeStr = Var.VarType.PinCategory.ToString();
		if (!Var.VarType.PinSubCategory.IsNone())
		{
			TypeStr += TEXT("/") + Var.VarType.PinSubCategory.ToString();
		}

		// Instance Editable == CPF_DisableEditOnInstance NOT set.
		const bool bInstanceEditable = (Var.PropertyFlags & CPF_DisableEditOnInstance) == 0;

		OutVars.Add(FString::Printf(TEXT("%s|%s|%s"),
			*Var.VarName.ToString(),
			*TypeStr,
			bInstanceEditable ? TEXT("true") : TEXT("false")));
	}

	return true;
}


// =============================================================================
// ImplementInterface
// =============================================================================

bool UMCAEventGraphLibrary::ImplementInterface(
	UBlueprint* Blueprint,
	const FString& InterfaceClass)
{
	if (!Blueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("ImplementInterface: Blueprint is null"));
		return false;
	}

	// Resolve the interface UClass. Try a full object path first (e.g.
	// "/Script/BotTown.BPI_Interactable"), then a bare name, then the U-prefixed
	// name — native interface classes carry the leading 'U'.
	UClass* IfaceClass = LoadObject<UClass>(nullptr, *InterfaceClass);
	if (!IfaceClass)
	{
		IfaceClass = FindFirstObject<UClass>(*InterfaceClass);
	}
	if (!IfaceClass)
	{
		IfaceClass = FindFirstObject<UClass>(*(FString("U") + InterfaceClass));
	}

	if (!IfaceClass || !IfaceClass->HasAnyClassFlags(CLASS_Interface))
	{
		UE_LOG(LogMCAScripting, Error,
			TEXT("ImplementInterface: '%s' did not resolve to an interface class"),
			*InterfaceClass);
		return false;
	}

	// Idempotent: if the Blueprint already implements it, report success.
	for (const FBPInterfaceDescription& Desc : Blueprint->ImplementedInterfaces)
	{
		if (Desc.Interface == IfaceClass)
		{
			UE_LOG(LogMCAScripting, Log,
				TEXT("ImplementInterface: '%s' already implements '%s'"),
				*Blueprint->GetName(), *IfaceClass->GetName());
			return true;
		}
	}

	FScopedTransaction Transaction(FText::FromString(
		FString::Printf(TEXT("MCA: Implement Interface '%s'"), *IfaceClass->GetName())));

	// ImplementNewInterface takes the class PATH name in UE5; it adds the
	// interface and generates override stubs for its functions.
	const bool bAdded = FBlueprintEditorUtils::ImplementNewInterface(
		Blueprint, IfaceClass->GetClassPathName());

	if (bAdded)
	{
		FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
		UE_LOG(LogMCAScripting, Log, TEXT("ImplementInterface: '%s' now implements '%s'"),
			*Blueprint->GetName(), *IfaceClass->GetName());
	}
	else
	{
		UE_LOG(LogMCAScripting, Error, TEXT("ImplementInterface: Failed to add '%s' to '%s'"),
			*IfaceClass->GetName(), *Blueprint->GetName());
	}

	return bAdded;
}

bool UMCAEventGraphLibrary::RemoveInterface(
	UBlueprint* Blueprint,
	const FString& InterfaceClass)
{
	if (!Blueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("RemoveInterface: Blueprint is null"));
		return false;
	}

	// Resolve the interface UClass with the same three-step fallback as
	// ImplementInterface: full object path, then bare name, then U-prefixed name
	// (native interface classes carry the leading 'U').
	UClass* IfaceClass = LoadObject<UClass>(nullptr, *InterfaceClass);
	if (!IfaceClass)
	{
		IfaceClass = FindFirstObject<UClass>(*InterfaceClass);
	}
	if (!IfaceClass)
	{
		IfaceClass = FindFirstObject<UClass>(*(FString("U") + InterfaceClass));
	}

	if (!IfaceClass || !IfaceClass->HasAnyClassFlags(CLASS_Interface))
	{
		UE_LOG(LogMCAScripting, Error,
			TEXT("RemoveInterface: '%s' did not resolve to an interface class"),
			*InterfaceClass);
		return false;
	}

	// Idempotent: if the Blueprint does not implement it, there is nothing to do.
	bool bImplemented = false;
	for (const FBPInterfaceDescription& Desc : Blueprint->ImplementedInterfaces)
	{
		if (Desc.Interface == IfaceClass)
		{
			bImplemented = true;
			break;
		}
	}

	if (!bImplemented)
	{
		UE_LOG(LogMCAScripting, Log,
			TEXT("RemoveInterface: '%s' does not implement '%s' (nothing to remove)"),
			*Blueprint->GetName(), *IfaceClass->GetName());
		return true;
	}

	FScopedTransaction Transaction(FText::FromString(
		FString::Printf(TEXT("MCA: Remove Interface '%s'"), *IfaceClass->GetName())));

	// RemoveInterface returns void in UE5; use the FTopLevelAssetPath overload to
	// mirror ImplementNewInterface. bPreserveFunctions = false drops the
	// interface's implementing function graphs along with the interface itself
	// (e.g. the auto-generated GetCurrentTarget stub on a waypoint).
	FBlueprintEditorUtils::RemoveInterface(
		Blueprint, IfaceClass->GetClassPathName(), /*bPreserveFunctions=*/false);

	FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);

	// Confirm the descriptor is actually gone — RemoveInterface gives no return
	// value, so we re-scan to report a trustworthy result.
	bool bStillImplemented = false;
	for (const FBPInterfaceDescription& Desc : Blueprint->ImplementedInterfaces)
	{
		if (Desc.Interface == IfaceClass)
		{
			bStillImplemented = true;
			break;
		}
	}

	if (bStillImplemented)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("RemoveInterface: Failed to remove '%s' from '%s'"),
			*IfaceClass->GetName(), *Blueprint->GetName());
		return false;
	}

	UE_LOG(LogMCAScripting, Log, TEXT("RemoveInterface: '%s' no longer implements '%s'"),
		*Blueprint->GetName(), *IfaceClass->GetName());
	return true;
}

TArray<FString> UMCAEventGraphLibrary::CompileBlueprintWithMessages(UBlueprint* Blueprint)
{
	TArray<FString> Out;

	if (!Blueprint)
	{
		Out.Add(TEXT("SUMMARY: errors=1 warnings=0"));
		Out.Add(TEXT("ERROR: Blueprint is null"));
		return Out;
	}

	// Compile through an FCompilerResultsLog so we capture the compiler's own
	// tokenized messages — this is the whole point of the helper. The stock
	// BlueprintEditorLibrary.compile_blueprint discards them.
	FCompilerResultsLog Results;
	Results.SetSourcePath(Blueprint->GetPathName());
	FKismetEditorUtilities::CompileBlueprint(Blueprint, EBlueprintCompileOptions::None, &Results);

	// Summary line first so a caller can branch on pass/fail without parsing
	// every row (the Python tool keys off errors=N here).
	Out.Add(FString::Printf(TEXT("SUMMARY: errors=%d warnings=%d"),
		Results.NumErrors, Results.NumWarnings));

	// One tagged line per compiler message. Severity → human prefix; the two
	// warning severities collapse to a single "WARNING" tag.
	for (const TSharedRef<FTokenizedMessage>& Message : Results.Messages)
	{
		FString Prefix;
		switch (Message->GetSeverity())
		{
			case EMessageSeverity::Error:
				Prefix = TEXT("ERROR");
				break;
			case EMessageSeverity::Warning:
			case EMessageSeverity::PerformanceWarning:
				Prefix = TEXT("WARNING");
				break;
			default:
				Prefix = TEXT("NOTE");
				break;
		}
		Out.Add(FString::Printf(TEXT("%s: %s"), *Prefix, *Message->ToText().ToString()));
	}

	return Out;
}
