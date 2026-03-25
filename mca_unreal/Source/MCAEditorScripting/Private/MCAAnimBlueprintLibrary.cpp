// MCA Animation Blueprint Library — Implementation.
//
// Implements the AnimBP graph editing operations. These functions
// manipulate UEdGraph nodes directly — the same operations that the
// visual AnimBP editor does when you drag and drop in the UI.
//
// Key patterns used throughout:
//   - FScopedTransaction for undo support
//   - FGraphNodeCreator<T> for proper node creation
//   - FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified() after changes
//   - All functions validate inputs and log errors via LogMCAScripting

#include "MCAAnimBlueprintLibrary.h"
#include "MCAEditorScriptingModule.h"

#include "Animation/AnimBlueprint.h"
#include "Animation/AnimSequenceBase.h"
#include "Animation/Skeleton.h"

#include "AnimGraphNode_Base.h"
#include "AnimGraphNode_StateMachine.h"
#include "AnimStateNode.h"
#include "AnimStateNodeBase.h"
#include "AnimStateEntryNode.h"
#include "AnimStateTransitionNode.h"
#include "AnimationStateMachineGraph.h"
#include "AnimationStateMachineSchema.h"
#include "AnimGraphNode_AssetPlayerBase.h"

#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphNode.h"
#include "EdGraph/EdGraphPin.h"

#include "Kismet2/BlueprintEditorUtils.h"
#include "Kismet2/KismetEditorUtilities.h"

#include "AssetToolsModule.h"
#include "Factories/AnimBlueprintFactory.h"
#include "ScopedTransaction.h"


// =============================================================================
// AnimBP Creation
// =============================================================================

UAnimBlueprint* UMCAAnimBlueprintLibrary::CreateAnimBlueprint(
	const FString& PackagePath,
	const FString& AssetName,
	USkeleton* Skeleton)
{
	if (!Skeleton)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("CreateAnimBlueprint: Skeleton is null"));
		return nullptr;
	}

	// Use the AssetTools factory to create the AnimBP properly.
	IAssetTools& AssetTools = FModuleManager::LoadModuleChecked<FAssetToolsModule>("AssetTools").Get();

	UAnimBlueprintFactory* Factory = NewObject<UAnimBlueprintFactory>();
	Factory->TargetSkeleton = Skeleton;
	// Parent class defaults to UAnimInstance, which is what we want.

	UObject* NewAsset = AssetTools.CreateAsset(
		AssetName,
		PackagePath,
		UAnimBlueprint::StaticClass(),
		Factory
	);

	UAnimBlueprint* AnimBP = Cast<UAnimBlueprint>(NewAsset);
	if (!AnimBP)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("CreateAnimBlueprint: Failed to create '%s/%s'"),
			*PackagePath, *AssetName);
		return nullptr;
	}

	UE_LOG(LogMCAScripting, Log, TEXT("CreateAnimBlueprint: Created '%s' with skeleton '%s'"),
		*AnimBP->GetPathName(), *Skeleton->GetName());

	return AnimBP;
}


// =============================================================================
// State Machine Operations
// =============================================================================

bool UMCAAnimBlueprintLibrary::AddStateMachine(
	UAnimBlueprint* AnimBlueprint,
	const FString& StateMachineName,
	bool bConnectToRoot)
{
	if (!AnimBlueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddStateMachine: AnimBlueprint is null"));
		return false;
	}

	// Get the root AnimGraph.
	UEdGraph* AnimGraph = GetAnimGraph(AnimBlueprint);
	if (!AnimGraph)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddStateMachine: No AnimGraph found in '%s'"),
			*AnimBlueprint->GetName());
		return false;
	}

	// Wrap in a transaction for undo support.
	FScopedTransaction Transaction(FText::FromString(
		FString::Printf(TEXT("MCA: Add State Machine '%s'"), *StateMachineName)));

	AnimGraph->Modify();

	// Create the state machine node using FGraphNodeCreator.
	FGraphNodeCreator<UAnimGraphNode_StateMachine> NodeCreator(*AnimGraph);
	UAnimGraphNode_StateMachine* SMNode = NodeCreator.CreateNode();

	// The state machine name comes from its EditorStateMachineGraph name.
	// Rename the graph to set the state machine's display name.
	if (SMNode->EditorStateMachineGraph)
	{
		SMNode->EditorStateMachineGraph->Rename(*StateMachineName, nullptr);
	}

	// Position the node so it doesn't overlap the output pose.
	SMNode->NodePosX = 0;
	SMNode->NodePosY = 0;

	// Finalize — this calls CreateNewGuid, PostPlacedNewNode, AllocateDefaultPins.
	NodeCreator.Finalize();

	// Wire to the output pose if requested.
	if (bConnectToRoot)
	{
		// Find the output pose node (Result node) in the AnimGraph.
		UEdGraphPin* OutputPosePin = nullptr;
		UEdGraphPin* SMOutputPin = nullptr;

		for (UEdGraphNode* Node : AnimGraph->Nodes)
		{
			// The result node has a pin named "Result" that accepts a pose.
			if (Node->IsA(UAnimGraphNode_Base::StaticClass()) && Node != SMNode)
			{
				for (UEdGraphPin* Pin : Node->Pins)
				{
					if (Pin->Direction == EGPD_Input && Pin->PinName == TEXT("Result"))
					{
						OutputPosePin = Pin;
						break;
					}
				}
			}
			if (OutputPosePin)
			{
				break;
			}
		}

		// Find the state machine's output pin (pose output).
		for (UEdGraphPin* Pin : SMNode->Pins)
		{
			if (Pin->Direction == EGPD_Output && Pin->PinType.PinCategory == UEdGraphSchema_K2::PC_Struct)
			{
				SMOutputPin = Pin;
				break;
			}
		}

		if (OutputPosePin && SMOutputPin)
		{
			// Break existing connections on the output pose.
			OutputPosePin->BreakAllPinLinks();
			// Connect state machine output to the result.
			OutputPosePin->MakeLinkTo(SMOutputPin);
			UE_LOG(LogMCAScripting, Log, TEXT("AddStateMachine: Wired '%s' to output pose"),
				*StateMachineName);
		}
		else
		{
			UE_LOG(LogMCAScripting, Warning, TEXT("AddStateMachine: Could not find output pose pin to wire to"));
		}
	}

	// Mark the blueprint as modified so it knows to recompile.
	FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(AnimBlueprint);

	UE_LOG(LogMCAScripting, Log, TEXT("AddStateMachine: Added '%s' to '%s'"),
		*StateMachineName, *AnimBlueprint->GetName());

	return true;
}


bool UMCAAnimBlueprintLibrary::ListStateMachines(
	UAnimBlueprint* AnimBlueprint,
	TArray<FString>& OutNames)
{
	OutNames.Empty();

	if (!AnimBlueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("ListStateMachines: AnimBlueprint is null"));
		return false;
	}

	UEdGraph* AnimGraph = GetAnimGraph(AnimBlueprint);
	if (!AnimGraph)
	{
		return false;
	}

	// Walk the AnimGraph nodes looking for state machine nodes.
	for (UEdGraphNode* Node : AnimGraph->Nodes)
	{
		UAnimGraphNode_StateMachine* SMNode = Cast<UAnimGraphNode_StateMachine>(Node);
		if (SMNode)
		{
			OutNames.Add(SMNode->GetStateMachineName());
		}
	}

	return true;
}


// =============================================================================
// State Operations
// =============================================================================

bool UMCAAnimBlueprintLibrary::AddState(
	UAnimBlueprint* AnimBlueprint,
	const FString& StateMachineName,
	const FString& StateName)
{
	if (!AnimBlueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddState: AnimBlueprint is null"));
		return false;
	}

	// Find the state machine graph.
	UAnimationStateMachineGraph* SMGraph = FindStateMachineGraph(AnimBlueprint, StateMachineName);
	if (!SMGraph)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddState: State machine '%s' not found in '%s'"),
			*StateMachineName, *AnimBlueprint->GetName());
		return false;
	}

	// Check for duplicate state name.
	if (FindStateNode(SMGraph, StateName))
	{
		UE_LOG(LogMCAScripting, Warning, TEXT("AddState: State '%s' already exists in '%s'"),
			*StateName, *StateMachineName);
		return false;
	}

	FScopedTransaction Transaction(FText::FromString(
		FString::Printf(TEXT("MCA: Add State '%s'"), *StateName)));

	SMGraph->Modify();

	// Create the state node using FGraphNodeCreator.
	FGraphNodeCreator<UAnimStateNode> NodeCreator(*SMGraph);
	UAnimStateNode* StateNode = NodeCreator.CreateNode();
	NodeCreator.Finalize();

	// The state name comes from its BoundGraph name (see GetStateName()).
	// Rename the bound graph to set the state's display name.
	UEdGraph* StateGraph = StateNode->GetBoundGraph();
	if (StateGraph)
	{
		StateGraph->Rename(*StateName, nullptr);
	}

	// Position states in a grid layout so they don't pile up.
	int32 StateCount = 0;
	for (UEdGraphNode* Node : SMGraph->Nodes)
	{
		if (Node->IsA(UAnimStateNode::StaticClass()))
		{
			StateCount++;
		}
	}
	// Arrange in a horizontal row offset from the entry node.
	StateNode->NodePosX = 250 + (StateCount - 1) * 300;
	StateNode->NodePosY = 0;

	FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(AnimBlueprint);

	UE_LOG(LogMCAScripting, Log, TEXT("AddState: Added '%s' to state machine '%s'"),
		*StateName, *StateMachineName);

	return true;
}


bool UMCAAnimBlueprintLibrary::SetDefaultState(
	UAnimBlueprint* AnimBlueprint,
	const FString& StateMachineName,
	const FString& StateName)
{
	if (!AnimBlueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("SetDefaultState: AnimBlueprint is null"));
		return false;
	}

	UAnimationStateMachineGraph* SMGraph = FindStateMachineGraph(AnimBlueprint, StateMachineName);
	if (!SMGraph)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("SetDefaultState: State machine '%s' not found"),
			*StateMachineName);
		return false;
	}

	UAnimStateNode* StateNode = FindStateNode(SMGraph, StateName);
	if (!StateNode)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("SetDefaultState: State '%s' not found in '%s'"),
			*StateName, *StateMachineName);
		return false;
	}

	// Find the entry node.
	UAnimStateEntryNode* EntryNode = SMGraph->EntryNode;
	if (!EntryNode)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("SetDefaultState: No entry node in state machine '%s'"),
			*StateMachineName);
		return false;
	}

	FScopedTransaction Transaction(FText::FromString(
		FString::Printf(TEXT("MCA: Set Default State '%s'"), *StateName)));

	SMGraph->Modify();

	// Wire the entry node's output to the target state's input.
	// UAnimStateEntryNode doesn't have GetOutputPin() — find it from Pins array.
	UEdGraphPin* EntryOutput = nullptr;
	for (UEdGraphPin* Pin : EntryNode->Pins)
	{
		if (Pin->Direction == EGPD_Output)
		{
			EntryOutput = Pin;
			break;
		}
	}
	UEdGraphPin* StateInput = StateNode->GetInputPin();

	if (EntryOutput && StateInput)
	{
		// Break existing entry connection.
		EntryOutput->BreakAllPinLinks();
		EntryOutput->MakeLinkTo(StateInput);

		FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(AnimBlueprint);

		UE_LOG(LogMCAScripting, Log, TEXT("SetDefaultState: Set '%s' as default in '%s'"),
			*StateName, *StateMachineName);
		return true;
	}

	UE_LOG(LogMCAScripting, Error, TEXT("SetDefaultState: Failed to wire entry to state '%s'"),
		*StateName);
	return false;
}


bool UMCAAnimBlueprintLibrary::ListStates(
	UAnimBlueprint* AnimBlueprint,
	const FString& StateMachineName,
	TArray<FString>& OutNames)
{
	OutNames.Empty();

	if (!AnimBlueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("ListStates: AnimBlueprint is null"));
		return false;
	}

	UAnimationStateMachineGraph* SMGraph = FindStateMachineGraph(AnimBlueprint, StateMachineName);
	if (!SMGraph)
	{
		return false;
	}

	for (UEdGraphNode* Node : SMGraph->Nodes)
	{
		UAnimStateNode* StateNode = Cast<UAnimStateNode>(Node);
		if (StateNode)
		{
			OutNames.Add(StateNode->GetStateName());
		}
	}

	return true;
}


// =============================================================================
// Animation Assignment
// =============================================================================

bool UMCAAnimBlueprintLibrary::SetStateAnimation(
	UAnimBlueprint* AnimBlueprint,
	const FString& StateMachineName,
	const FString& StateName,
	UAnimSequenceBase* AnimAsset)
{
	if (!AnimBlueprint || !AnimAsset)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("SetStateAnimation: AnimBlueprint or AnimAsset is null"));
		return false;
	}

	UAnimationStateMachineGraph* SMGraph = FindStateMachineGraph(AnimBlueprint, StateMachineName);
	if (!SMGraph)
	{
		return false;
	}

	UAnimStateNode* StateNode = FindStateNode(SMGraph, StateName);
	if (!StateNode)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("SetStateAnimation: State '%s' not found"), *StateName);
		return false;
	}

	// Get the state's bound graph — this is where the animation player lives.
	UEdGraph* StateGraph = StateNode->GetBoundGraph();
	if (!StateGraph)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("SetStateAnimation: State '%s' has no bound graph"),
			*StateName);
		return false;
	}

	FScopedTransaction Transaction(FText::FromString(
		FString::Printf(TEXT("MCA: Set Animation for '%s'"), *StateName)));

	StateGraph->Modify();

	// Look for an existing asset player node and update it, or note that
	// we need to create one. The state's bound graph contains anim nodes.
	UAnimGraphNode_AssetPlayerBase* PlayerNode = nullptr;
	for (UEdGraphNode* Node : StateGraph->Nodes)
	{
		PlayerNode = Cast<UAnimGraphNode_AssetPlayerBase>(Node);
		if (PlayerNode)
		{
			break;
		}
	}

	if (PlayerNode)
	{
		// Update the existing player's asset reference.
		PlayerNode->SetAnimationAsset(AnimAsset);
		UE_LOG(LogMCAScripting, Log, TEXT("SetStateAnimation: Updated existing player in '%s' to '%s'"),
			*StateName, *AnimAsset->GetName());
	}
	else
	{
		// No existing player — we can't easily create one from C++ without
		// knowing the exact node class (AnimSequence vs BlendSpace, etc.).
		// Log a clear message so the caller knows to use execute_python.
		UE_LOG(LogMCAScripting, Warning,
			TEXT("SetStateAnimation: No existing animation player in state '%s'. "
				 "Use the editor UI or execute_python to add the initial player node, "
				 "then this function can update the animation asset."),
			*StateName);
		return false;
	}

	FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(AnimBlueprint);
	return true;
}


// =============================================================================
// Transition Operations
// =============================================================================

bool UMCAAnimBlueprintLibrary::AddTransition(
	UAnimBlueprint* AnimBlueprint,
	const FString& StateMachineName,
	const FString& FromStateName,
	const FString& ToStateName,
	float CrossfadeDuration)
{
	if (!AnimBlueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddTransition: AnimBlueprint is null"));
		return false;
	}

	UAnimationStateMachineGraph* SMGraph = FindStateMachineGraph(AnimBlueprint, StateMachineName);
	if (!SMGraph)
	{
		return false;
	}

	UAnimStateNode* FromState = FindStateNode(SMGraph, FromStateName);
	UAnimStateNode* ToState = FindStateNode(SMGraph, ToStateName);

	if (!FromState)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddTransition: From state '%s' not found"), *FromStateName);
		return false;
	}
	if (!ToState)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddTransition: To state '%s' not found"), *ToStateName);
		return false;
	}

	// Check if transition already exists.
	if (FindTransition(SMGraph, FromStateName, ToStateName))
	{
		UE_LOG(LogMCAScripting, Warning, TEXT("AddTransition: Transition '%s' -> '%s' already exists"),
			*FromStateName, *ToStateName);
		return false;
	}

	FScopedTransaction Transaction(FText::FromString(
		FString::Printf(TEXT("MCA: Add Transition '%s' -> '%s'"), *FromStateName, *ToStateName)));

	SMGraph->Modify();

	// Create the transition node.
	FGraphNodeCreator<UAnimStateTransitionNode> NodeCreator(*SMGraph);
	UAnimStateTransitionNode* TransNode = NodeCreator.CreateNode();
	NodeCreator.Finalize();

	// Set crossfade duration.
	TransNode->CrossfadeDuration = CrossfadeDuration;

	// Position between the two states.
	TransNode->NodePosX = (FromState->NodePosX + ToState->NodePosX) / 2;
	TransNode->NodePosY = (FromState->NodePosY + ToState->NodePosY) / 2;

	// Wire: FromState output -> Transition input, Transition output -> ToState input.
	UEdGraphPin* FromOutput = FromState->GetOutputPin();
	UEdGraphPin* TransInput = TransNode->GetInputPin();
	UEdGraphPin* TransOutput = TransNode->GetOutputPin();
	UEdGraphPin* ToInput = ToState->GetInputPin();

	if (FromOutput && TransInput && TransOutput && ToInput)
	{
		FromOutput->MakeLinkTo(TransInput);
		TransOutput->MakeLinkTo(ToInput);
	}
	else
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddTransition: Failed to wire pins"));
		return false;
	}

	FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(AnimBlueprint);

	UE_LOG(LogMCAScripting, Log, TEXT("AddTransition: Created '%s' -> '%s' (crossfade: %.2fs)"),
		*FromStateName, *ToStateName, CrossfadeDuration);

	return true;
}


bool UMCAAnimBlueprintLibrary::SetAutoTransitionRule(
	UAnimBlueprint* AnimBlueprint,
	const FString& StateMachineName,
	const FString& FromStateName,
	const FString& ToStateName,
	float TriggerTime)
{
	if (!AnimBlueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("SetAutoTransitionRule: AnimBlueprint is null"));
		return false;
	}

	UAnimationStateMachineGraph* SMGraph = FindStateMachineGraph(AnimBlueprint, StateMachineName);
	if (!SMGraph)
	{
		return false;
	}

	UAnimStateTransitionNode* TransNode = FindTransition(SMGraph, FromStateName, ToStateName);
	if (!TransNode)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("SetAutoTransitionRule: Transition '%s' -> '%s' not found"),
			*FromStateName, *ToStateName);
		return false;
	}

	FScopedTransaction Transaction(FText::FromString(TEXT("MCA: Set Auto Transition Rule")));

	TransNode->Modify();

	// Enable automatic rule based on sequence player remaining time.
	TransNode->bAutomaticRuleBasedOnSequencePlayerInState = true;
	TransNode->AutomaticRuleTriggerTime = TriggerTime;

	FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(AnimBlueprint);

	UE_LOG(LogMCAScripting, Log,
		TEXT("SetAutoTransitionRule: '%s' -> '%s' fires at %.2fs remaining"),
		*FromStateName, *ToStateName, TriggerTime);

	return true;
}


// =============================================================================
// Compilation
// =============================================================================

bool UMCAAnimBlueprintLibrary::CompileAnimBlueprint(UAnimBlueprint* AnimBlueprint)
{
	if (!AnimBlueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("CompileAnimBlueprint: AnimBlueprint is null"));
		return false;
	}

	FKismetEditorUtilities::CompileBlueprint(AnimBlueprint);

	bool bSuccess = (AnimBlueprint->Status != BS_Error);

	UE_LOG(LogMCAScripting, Log, TEXT("CompileAnimBlueprint: '%s' — %s"),
		*AnimBlueprint->GetName(),
		bSuccess ? TEXT("SUCCESS") : TEXT("ERRORS"));

	return bSuccess;
}


// =============================================================================
// Internal Helpers
// =============================================================================

UEdGraph* UMCAAnimBlueprintLibrary::GetAnimGraph(UAnimBlueprint* AnimBlueprint)
{
	if (!AnimBlueprint)
	{
		return nullptr;
	}

	// The AnimGraph is typically the first function graph in the blueprint.
	for (UEdGraph* Graph : AnimBlueprint->FunctionGraphs)
	{
		// The root AnimGraph has the schema set to UAnimationGraphSchema.
		if (Graph && Graph->GetFName() == TEXT("AnimGraph"))
		{
			return Graph;
		}
	}

	// Fallback: check all function graphs.
	if (AnimBlueprint->FunctionGraphs.Num() > 0)
	{
		return AnimBlueprint->FunctionGraphs[0];
	}

	return nullptr;
}


UAnimationStateMachineGraph* UMCAAnimBlueprintLibrary::FindStateMachineGraph(
	UAnimBlueprint* AnimBlueprint,
	const FString& StateMachineName)
{
	UEdGraph* AnimGraph = GetAnimGraph(AnimBlueprint);
	if (!AnimGraph)
	{
		return nullptr;
	}

	// Walk AnimGraph nodes looking for the matching state machine.
	for (UEdGraphNode* Node : AnimGraph->Nodes)
	{
		UAnimGraphNode_StateMachine* SMNode = Cast<UAnimGraphNode_StateMachine>(Node);
		if (SMNode && SMNode->GetStateMachineName() == StateMachineName)
		{
			// The state machine's editor graph is in the node's subgraph.
			return Cast<UAnimationStateMachineGraph>(SMNode->EditorStateMachineGraph);
		}
	}

	return nullptr;
}


UAnimStateNode* UMCAAnimBlueprintLibrary::FindStateNode(
	UAnimationStateMachineGraph* SMGraph,
	const FString& StateName)
{
	if (!SMGraph)
	{
		return nullptr;
	}

	for (UEdGraphNode* Node : SMGraph->Nodes)
	{
		UAnimStateNode* StateNode = Cast<UAnimStateNode>(Node);
		if (StateNode && StateNode->GetStateName() == StateName)
		{
			return StateNode;
		}
	}

	return nullptr;
}


UAnimStateTransitionNode* UMCAAnimBlueprintLibrary::FindTransition(
	UAnimationStateMachineGraph* SMGraph,
	const FString& FromStateName,
	const FString& ToStateName)
{
	if (!SMGraph)
	{
		return nullptr;
	}

	for (UEdGraphNode* Node : SMGraph->Nodes)
	{
		UAnimStateTransitionNode* TransNode = Cast<UAnimStateTransitionNode>(Node);
		if (!TransNode)
		{
			continue;
		}

		// Check if this transition connects the right states.
		UAnimStateNodeBase* PrevState = TransNode->GetPreviousState();
		UAnimStateNodeBase* NextState = TransNode->GetNextState();

		if (PrevState && NextState)
		{
			if (PrevState->GetStateName() == FromStateName &&
				NextState->GetStateName() == ToStateName)
			{
				return TransNode;
			}
		}
	}

	return nullptr;
}
