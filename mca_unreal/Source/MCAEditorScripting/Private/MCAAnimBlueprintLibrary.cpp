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

// Runtime / baked-data introspection: the live state-machine node, the running
// AnimInstance, and the compiled generated class that carries the baked topology.
#include "Animation/AnimInstance.h"
#include "Animation/AnimNode_StateMachine.h"
#include "Animation/AnimBlueprintGeneratedClass.h"
#include "Animation/AnimStateMachineTypes.h"

// AnimGraph pose-flow introspection: slot, cached-pose save/use, and output-root nodes.
#include "AnimGraphNode_Slot.h"
#include "AnimGraphNode_SaveCachedPose.h"
#include "AnimGraphNode_UseCachedPose.h"
#include "AnimGraphNode_Root.h"
#include "AnimNodes/AnimNode_Slot.h"

#include "AnimGraphNode_Base.h"
#include "AnimGraphNode_StateMachine.h"
#include "AnimStateNode.h"
#include "AnimStateNodeBase.h"
#include "AnimStateEntryNode.h"
#include "AnimStateTransitionNode.h"
#include "AnimationStateMachineGraph.h"
#include "AnimationStateMachineSchema.h"
#include "AnimGraphNode_AssetPlayerBase.h"
#include "AnimGraphNode_SequencePlayer.h"

#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphNode.h"
#include "EdGraph/EdGraphPin.h"

#include "Kismet2/BlueprintEditorUtils.h"
#include "Kismet2/KismetEditorUtilities.h"

#include "AnimGraphNode_TransitionResult.h"
#include "K2Node_VariableGet.h"
#include "K2Node_CallFunction.h"
#include "Kismet/KismetMathLibrary.h"
#include "EdGraphSchema_K2.h"

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

	// Position the node so it doesn't overlap the output pose.
	SMNode->NodePosX = 0;
	SMNode->NodePosY = 0;

	// Finalize — this calls CreateNewGuid, PostPlacedNewNode, AllocateDefaultPins.
	// IMPORTANT: Must finalize BEFORE renaming because PostPlacedNewNode creates
	// the EditorStateMachineGraph sub-object. It doesn't exist until Finalize().
	NodeCreator.Finalize();

	// The state machine name comes from its EditorStateMachineGraph UObject name.
	// GetStateMachineName() returns EditorStateMachineGraph->GetName(), so we must
	// rename the actual UObject — FBlueprintEditorUtils::RenameGraph alone may only
	// set the friendly/display name without touching the UObject name.
	if (SMNode->EditorStateMachineGraph)
	{
		// Try RenameGraph first for editor bookkeeping (schema notifications, etc.).
		FBlueprintEditorUtils::RenameGraph(SMNode->EditorStateMachineGraph, StateMachineName);

		// If the UObject name didn't change, force-rename it directly.
		if (SMNode->EditorStateMachineGraph->GetName() != StateMachineName)
		{
			bool bRenamed = SMNode->EditorStateMachineGraph->Rename(
				*StateMachineName, SMNode->EditorStateMachineGraph->GetOuter(),
				REN_DontCreateRedirectors | REN_ForceNoResetLoaders);

			UE_LOG(LogMCAScripting, Log,
				TEXT("AddStateMachine: Direct UObject rename to '%s' %s (actual: '%s')"),
				*StateMachineName,
				bRenamed ? TEXT("succeeded") : TEXT("FAILED"),
				*SMNode->EditorStateMachineGraph->GetName());
		}
		else
		{
			UE_LOG(LogMCAScripting, Log,
				TEXT("AddStateMachine: RenameGraph set name to '%s'"),
				*SMNode->EditorStateMachineGraph->GetName());
		}
	}
	else
	{
		UE_LOG(LogMCAScripting, Warning,
			TEXT("AddStateMachine: EditorStateMachineGraph is null after Finalize — name not applied"));
	}

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
	// Use RenameGraph (not raw UObject::Rename) — it handles editor bookkeeping.
	UEdGraph* StateGraph = StateNode->GetBoundGraph();
	if (StateGraph)
	{
		FBlueprintEditorUtils::RenameGraph(StateGraph, StateName);
		UE_LOG(LogMCAScripting, Log, TEXT("AddState: Renamed bound graph to '%s' (actual: '%s')"),
			*StateName, *StateGraph->GetName());
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


bool UMCAAnimBlueprintLibrary::RemoveState(
	UAnimBlueprint* AnimBlueprint,
	const FString& StateMachineName,
	const FString& StateName)
{
	if (!AnimBlueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("RemoveState: AnimBlueprint is null"));
		return false;
	}

	UAnimationStateMachineGraph* SMGraph = FindStateMachineGraph(AnimBlueprint, StateMachineName);
	if (!SMGraph)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("RemoveState: State machine '%s' not found in '%s'"),
			*StateMachineName, *AnimBlueprint->GetName());
		return false;
	}

	UAnimStateNode* StateNode = FindStateNode(SMGraph, StateName);
	if (!StateNode)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("RemoveState: State '%s' not found in '%s'"),
			*StateName, *StateMachineName);
		return false;
	}

	FScopedTransaction Transaction(FText::FromString(
		FString::Printf(TEXT("MCA: Remove State '%s'"), *StateName)));

	SMGraph->Modify();

	// Collect every transition touching this state. Deleting a state in the visual
	// editor also deletes its connected transitions; if we left them, they would
	// dangle with a null endpoint (GetPreviousState/GetNextState returning null) and
	// corrupt the machine on the next compile. Gather first, then remove — never
	// mutate SMGraph->Nodes while iterating it.
	TArray<UAnimStateTransitionNode*> ConnectedTransitions;
	for (UEdGraphNode* Node : SMGraph->Nodes)
	{
		UAnimStateTransitionNode* TransNode = Cast<UAnimStateTransitionNode>(Node);
		if (!TransNode)
		{
			continue;
		}

		// A transition references the state either as its source or its destination.
		// Compare against the base-class pointer — GetPreviousState/GetNextState return
		// UAnimStateNodeBase*, and our target is the same UObject.
		UAnimStateNodeBase* PrevState = TransNode->GetPreviousState();
		UAnimStateNodeBase* NextState = TransNode->GetNextState();
		if (PrevState == StateNode || NextState == StateNode)
		{
			ConnectedTransitions.Add(TransNode);
		}
	}

	// Remove the connected transitions first (bDontRecompile = true to batch the work;
	// we mark the blueprint modified once at the end). RemoveNode runs the engine's
	// DestroyNode path, which also tears down each transition's bound rule graph.
	for (UAnimStateTransitionNode* TransNode : ConnectedTransitions)
	{
		FBlueprintEditorUtils::RemoveNode(AnimBlueprint, TransNode, /*bDontRecompile=*/ true);
	}

	// Now remove the state node itself. Its DestroyNode override removes the bound
	// state graph (the sub-graph that holds the state's animation player).
	FBlueprintEditorUtils::RemoveNode(AnimBlueprint, StateNode, /*bDontRecompile=*/ true);

	FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(AnimBlueprint);

	UE_LOG(LogMCAScripting, Log,
		TEXT("RemoveState: Removed '%s' from '%s' (and %d connected transition(s))"),
		*StateName, *StateMachineName, ConnectedTransitions.Num());

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
		// No existing player — create a SequencePlayer node and wire it up.
		// This handles UAnimSequence assets. BlendSpace and other types would
		// need additional node classes, but SequencePlayer covers the common case.
		UE_LOG(LogMCAScripting, Log,
			TEXT("SetStateAnimation: Creating new SequencePlayer in state '%s'"),
			*StateName);

		FGraphNodeCreator<UAnimGraphNode_SequencePlayer> PlayerCreator(*StateGraph);
		UAnimGraphNode_SequencePlayer* NewPlayer = PlayerCreator.CreateNode();
		NewPlayer->NodePosX = 200;
		NewPlayer->NodePosY = 0;
		PlayerCreator.Finalize();

		// Set the animation asset on the new player.
		NewPlayer->SetAnimationAsset(AnimAsset);

		// Wire the player's output pose to the state's result node.
		// The state graph has an AnimGraphNode_StateResult that accepts a pose.
		UEdGraphPin* PlayerOutputPin = nullptr;
		for (UEdGraphPin* Pin : NewPlayer->Pins)
		{
			if (Pin->Direction == EGPD_Output && Pin->PinType.PinCategory == UEdGraphSchema_K2::PC_Struct)
			{
				PlayerOutputPin = Pin;
				break;
			}
		}

		// Find the result node's input pose pin.
		UEdGraphPin* ResultInputPin = nullptr;
		for (UEdGraphNode* Node : StateGraph->Nodes)
		{
			// The result node is NOT an AssetPlayerBase — it is the output of the state.
			if (Node != NewPlayer && !Cast<UAnimGraphNode_AssetPlayerBase>(Node))
			{
				for (UEdGraphPin* Pin : Node->Pins)
				{
					if (Pin->Direction == EGPD_Input && Pin->PinType.PinCategory == UEdGraphSchema_K2::PC_Struct)
					{
						ResultInputPin = Pin;
						break;
					}
				}
				if (ResultInputPin)
				{
					break;
				}
			}
		}

		if (PlayerOutputPin && ResultInputPin)
		{
			ResultInputPin->BreakAllPinLinks();
			ResultInputPin->MakeLinkTo(PlayerOutputPin);
			UE_LOG(LogMCAScripting, Log,
				TEXT("SetStateAnimation: Wired SequencePlayer to state result in '%s'"),
				*StateName);
		}
		else
		{
			UE_LOG(LogMCAScripting, Warning,
				TEXT("SetStateAnimation: Created SequencePlayer but could not wire pose pins in '%s'"),
				*StateName);
		}
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


// =============================================================================
// Anim Notify Operations
// =============================================================================

bool UMCAAnimBlueprintLibrary::AddAnimNotify(
	UAnimSequenceBase* AnimSequence,
	const FString& NotifyName,
	float TriggerTime)
{
	if (!AnimSequence)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("AddAnimNotify: AnimSequence is null"));
		return false;
	}

	FScopedTransaction Transaction(FText::FromString(
		FString::Printf(TEXT("MCA: Add Anim Notify '%s'"), *NotifyName)));

	AnimSequence->Modify();

	// Append a simple named notify (no notify-state, no custom UAnimNotify class).
	const int32 NewIndex = AnimSequence->Notifies.Add(FAnimNotifyEvent());
	FAnimNotifyEvent& Event = AnimSequence->Notifies[NewIndex];
	Event.NotifyName = FName(*NotifyName);
	Event.Guid = FGuid::NewGuid();
	Event.NotifyStateClass = nullptr;
	Event.Notify = nullptr;
	Event.TrackIndex = 0;

	// Anchor the notify on the sequence timeline at TriggerTime seconds.
	Event.Link(AnimSequence, TriggerTime);
	Event.TriggerTimeOffset = GetTriggerTimeOffsetForType(
		AnimSequence->CalculateOffsetForNotify(TriggerTime));

	// Persist + refresh cached notify data so editor and runtime pick it up.
	AnimSequence->PostEditChange();
	AnimSequence->MarkPackageDirty();

	UE_LOG(LogMCAScripting, Log, TEXT("AddAnimNotify: Added '%s' to '%s' at %.3fs"),
		*NotifyName, *AnimSequence->GetName(), TriggerTime);

	return true;
}


// =============================================================================
// Transition Bool Condition
// =============================================================================

bool UMCAAnimBlueprintLibrary::SetTransitionBoolCondition(
	UAnimBlueprint* AnimBlueprint,
	const FString& StateMachineName,
	const FString& FromStateName,
	const FString& ToStateName,
	const FString& BoolVariableName,
	bool bEqualsValue)
{
	if (!AnimBlueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("SetTransitionBoolCondition: AnimBlueprint is null"));
		return false;
	}

	UAnimationStateMachineGraph* SMGraph = FindStateMachineGraph(AnimBlueprint, StateMachineName);
	if (!SMGraph)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("SetTransitionBoolCondition: State machine '%s' not found"),
			*StateMachineName);
		return false;
	}

	UAnimStateTransitionNode* TransNode = FindTransition(SMGraph, FromStateName, ToStateName);
	if (!TransNode)
	{
		UE_LOG(LogMCAScripting, Error,
			TEXT("SetTransitionBoolCondition: Transition '%s' -> '%s' not found"),
			*FromStateName, *ToStateName);
		return false;
	}

	// A transition's rule lives in its bound graph — a small AnimGraph whose
	// TransitionResult node carries a bool input pin ("bCanEnterTransition").
	UEdGraph* RuleGraph = TransNode->GetBoundGraph();
	if (!RuleGraph)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("SetTransitionBoolCondition: Transition has no bound graph"));
		return false;
	}

	// Find the result node.
	UAnimGraphNode_TransitionResult* ResultNode = nullptr;
	for (UEdGraphNode* Node : RuleGraph->Nodes)
	{
		ResultNode = Cast<UAnimGraphNode_TransitionResult>(Node);
		if (ResultNode)
		{
			break;
		}
	}
	if (!ResultNode)
	{
		UE_LOG(LogMCAScripting, Error,
			TEXT("SetTransitionBoolCondition: No TransitionResult node in rule graph"));
		return false;
	}

	// The result node's bool input pin is the "can enter" gate.
	UEdGraphPin* CanEnterPin = nullptr;
	for (UEdGraphPin* Pin : ResultNode->Pins)
	{
		if (Pin->Direction == EGPD_Input && Pin->PinType.PinCategory == UEdGraphSchema_K2::PC_Boolean)
		{
			CanEnterPin = Pin;
			break;
		}
	}
	if (!CanEnterPin)
	{
		UE_LOG(LogMCAScripting, Error,
			TEXT("SetTransitionBoolCondition: No bool input pin on result node"));
		return false;
	}

	FScopedTransaction Transaction(FText::FromString(TEXT("MCA: Set Transition Bool Condition")));
	RuleGraph->Modify();

	// Clean re-author: drop whatever currently drives the rule.
	CanEnterPin->BreakAllPinLinks();

	// Add a variable-get node for the bool. Resolved on self (the AnimInstance) —
	// the variable must already exist on the AnimBP.
	FGraphNodeCreator<UK2Node_VariableGet> VarCreator(*RuleGraph);
	UK2Node_VariableGet* VarNode = VarCreator.CreateNode();
	VarNode->VariableReference.SetSelfMember(FName(*BoolVariableName));
	VarNode->NodePosX = ResultNode->NodePosX - 400;
	VarNode->NodePosY = ResultNode->NodePosY;
	VarCreator.Finalize();

	// The get node's output bool pin.
	UEdGraphPin* VarOutPin = nullptr;
	for (UEdGraphPin* Pin : VarNode->Pins)
	{
		if (Pin->Direction == EGPD_Output && Pin->PinType.PinCategory == UEdGraphSchema_K2::PC_Boolean)
		{
			VarOutPin = Pin;
			break;
		}
	}
	if (!VarOutPin)
	{
		UE_LOG(LogMCAScripting, Error,
			TEXT("SetTransitionBoolCondition: Variable '%s' produced no bool pin (does it exist on the AnimBP?)"),
			*BoolVariableName);
		return false;
	}

	if (bEqualsValue)
	{
		// "Var == true": wire the bool straight into the can-enter gate.
		VarOutPin->MakeLinkTo(CanEnterPin);
	}
	else
	{
		// "Var == false": insert a boolean NOT between the variable and the gate.
		FGraphNodeCreator<UK2Node_CallFunction> NotCreator(*RuleGraph);
		UK2Node_CallFunction* NotNode = NotCreator.CreateNode();
		UFunction* NotFunc = UKismetMathLibrary::StaticClass()->FindFunctionByName(TEXT("Not_PreBool"));
		NotNode->SetFromFunction(NotFunc);
		NotNode->NodePosX = ResultNode->NodePosX - 200;
		NotNode->NodePosY = ResultNode->NodePosY;
		NotCreator.Finalize();

		UEdGraphPin* NotInputPin = NotNode->FindPin(FName(TEXT("A")), EGPD_Input);
		UEdGraphPin* NotReturnPin = NotNode->GetReturnValuePin();
		if (!NotInputPin || !NotReturnPin)
		{
			UE_LOG(LogMCAScripting, Error,
				TEXT("SetTransitionBoolCondition: NOT node pins not found"));
			return false;
		}
		VarOutPin->MakeLinkTo(NotInputPin);
		NotReturnPin->MakeLinkTo(CanEnterPin);
	}

	FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(AnimBlueprint);

	UE_LOG(LogMCAScripting, Log,
		TEXT("SetTransitionBoolCondition: '%s' -> '%s' now requires %s == %s"),
		*FromStateName, *ToStateName, *BoolVariableName,
		bEqualsValue ? TEXT("true") : TEXT("false"));

	return true;
}


// =============================================================================
// Read-back: Transition Rule
// =============================================================================

bool UMCAAnimBlueprintLibrary::GetTransitionRule(
	UAnimBlueprint* AnimBlueprint,
	const FString& StateMachineName,
	const FString& FromStateName,
	const FString& ToStateName,
	FString& OutSummary)
{
	OutSummary.Empty();

	if (!AnimBlueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("GetTransitionRule: AnimBlueprint is null"));
		return false;
	}

	UAnimationStateMachineGraph* SMGraph = FindStateMachineGraph(AnimBlueprint, StateMachineName);
	if (!SMGraph)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("GetTransitionRule: State machine '%s' not found"),
			*StateMachineName);
		return false;
	}

	UAnimStateTransitionNode* TransNode = FindTransition(SMGraph, FromStateName, ToStateName);
	if (!TransNode)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("GetTransitionRule: Transition '%s' -> '%s' not found"),
			*FromStateName, *ToStateName);
		return false;
	}

	// The automatic (sequence-player remaining-time) rule short-circuits the rest.
	if (TransNode->bAutomaticRuleBasedOnSequencePlayerInState)
	{
		OutSummary = FString::Printf(TEXT("AUTO (remaining <= %.3fs); crossfade=%.2fs"),
			TransNode->AutomaticRuleTriggerTime, TransNode->CrossfadeDuration);
		return true;
	}

	UEdGraph* RuleGraph = TransNode->GetBoundGraph();
	if (!RuleGraph)
	{
		OutSummary = TEXT("(no bound graph)");
		return true;
	}

	// Find the TransitionResult node + its bool "can enter" pin.
	UAnimGraphNode_TransitionResult* ResultNode = nullptr;
	for (UEdGraphNode* Node : RuleGraph->Nodes)
	{
		ResultNode = Cast<UAnimGraphNode_TransitionResult>(Node);
		if (ResultNode)
		{
			break;
		}
	}
	if (!ResultNode)
	{
		OutSummary = TEXT("(no result node)");
		return true;
	}

	UEdGraphPin* CanEnterPin = nullptr;
	for (UEdGraphPin* Pin : ResultNode->Pins)
	{
		if (Pin->Direction == EGPD_Input && Pin->PinType.PinCategory == UEdGraphSchema_K2::PC_Boolean)
		{
			CanEnterPin = Pin;
			break;
		}
	}
	if (!CanEnterPin)
	{
		OutSummary = TEXT("(no can-enter pin)");
		return true;
	}

	// Nothing wired -> the pin's literal default is the rule.
	if (CanEnterPin->LinkedTo.Num() == 0)
	{
		OutSummary = FString::Printf(TEXT("CONST %s"),
			CanEnterPin->DefaultValue.IsEmpty() ? TEXT("false") : *CanEnterPin->DefaultValue);
		return true;
	}

	// Decode the node driving the gate. Handle the two shapes this library authors
	// (a bool variable, optionally through a NOT), and describe anything else.
	UEdGraphPin* SrcPin = CanEnterPin->LinkedTo[0];
	UEdGraphNode* SrcNode = SrcPin ? SrcPin->GetOwningNode() : nullptr;

	if (UK2Node_VariableGet* VarGet = Cast<UK2Node_VariableGet>(SrcNode))
	{
		OutSummary = FString::Printf(TEXT("%s == true"), *VarGet->GetVarName().ToString());
	}
	else if (UK2Node_CallFunction* CallFn = Cast<UK2Node_CallFunction>(SrcNode))
	{
		const FString FuncName = CallFn->GetFunctionName().ToString();
		if (FuncName == TEXT("Not_PreBool"))
		{
			// Trace the NOT's "A" input back to a variable (the "Var == false" shape).
			UEdGraphPin* AIn = CallFn->FindPin(FName(TEXT("A")), EGPD_Input);
			UK2Node_VariableGet* InnerVar = (AIn && AIn->LinkedTo.Num() > 0)
				? Cast<UK2Node_VariableGet>(AIn->LinkedTo[0]->GetOwningNode())
				: nullptr;
			OutSummary = InnerVar
				? FString::Printf(TEXT("%s == false"), *InnerVar->GetVarName().ToString())
				: TEXT("NOT(<complex>)");
		}
		else
		{
			OutSummary = FString::Printf(TEXT("%s()"), *FuncName);
		}
	}
	else
	{
		OutSummary = FString::Printf(TEXT("<%s>"),
			SrcNode ? *SrcNode->GetClass()->GetName() : TEXT("null"));
	}

	return true;
}


// =============================================================================
// Read-back: Transitions + Notifies
// =============================================================================

bool UMCAAnimBlueprintLibrary::ListTransitions(
	UAnimBlueprint* AnimBlueprint,
	const FString& StateMachineName,
	TArray<FString>& OutTransitions)
{
	OutTransitions.Empty();

	if (!AnimBlueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("ListTransitions: AnimBlueprint is null"));
		return false;
	}

	UAnimationStateMachineGraph* SMGraph = FindStateMachineGraph(AnimBlueprint, StateMachineName);
	if (!SMGraph)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("ListTransitions: State machine '%s' not found"),
			*StateMachineName);
		return false;
	}

	// Walk the state machine graph collecting every transition's endpoints.
	for (UEdGraphNode* Node : SMGraph->Nodes)
	{
		UAnimStateTransitionNode* TransNode = Cast<UAnimStateTransitionNode>(Node);
		if (!TransNode)
		{
			continue;
		}

		UAnimStateNodeBase* PrevState = TransNode->GetPreviousState();
		UAnimStateNodeBase* NextState = TransNode->GetNextState();
		const FString From = PrevState ? PrevState->GetStateName() : TEXT("?");
		const FString To = NextState ? NextState->GetStateName() : TEXT("?");
		OutTransitions.Add(FString::Printf(TEXT("%s -> %s"), *From, *To));
	}

	return true;
}


bool UMCAAnimBlueprintLibrary::ListAnimNotifies(
	UAnimSequenceBase* AnimSequence,
	TArray<FString>& OutNotifies)
{
	OutNotifies.Empty();

	if (!AnimSequence)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("ListAnimNotifies: AnimSequence is null"));
		return false;
	}

	// Notifies is editor-protected (unreadable from Python) — read it here in C++.
	for (const FAnimNotifyEvent& Event : AnimSequence->Notifies)
	{
		OutNotifies.Add(FString::Printf(TEXT("%s@%.3f"),
			*Event.NotifyName.ToString(), Event.GetTime()));
	}

	return true;
}


// =============================================================================
// Runtime / Baked Introspection
// =============================================================================

FString UMCAAnimBlueprintLibrary::GetActiveStateName(
	UAnimInstance* AnimInstance,
	const FString& StateMachineName)
{
	if (!AnimInstance)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("GetActiveStateName: AnimInstance is null"));
		return TEXT("(no anim instance)");
	}

	// Resolve the LIVE state-machine node by name. This is the runtime instance the
	// AnimInstance actually evaluates — the ground truth, not an author-set proxy var.
	const FAnimNode_StateMachine* StateMachine =
		AnimInstance->GetStateMachineInstanceFromName(FName(*StateMachineName));
	if (!StateMachine)
	{
		UE_LOG(LogMCAScripting, Warning,
			TEXT("GetActiveStateName: State machine '%s' not found on '%s'"),
			*StateMachineName, *AnimInstance->GetName());
		return TEXT("(machine not found)");
	}

	// GetCurrentStateName() reads the node's active state index — the authoritative answer.
	const FName ActiveState = StateMachine->GetCurrentStateName();

	UE_LOG(LogMCAScripting, Log, TEXT("GetActiveStateName: '%s' active state = '%s'"),
		*StateMachineName, *ActiveState.ToString());

	return ActiveState.ToString();
}


bool UMCAAnimBlueprintLibrary::DumpBakedTransitions(
	UAnimBlueprint* AnimBlueprint,
	const FString& StateMachineName,
	TArray<FString>& OutTransitions)
{
	OutTransitions.Empty();

	if (!AnimBlueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("DumpBakedTransitions: AnimBlueprint is null"));
		return false;
	}

	// The baked state machines live on the COMPILED generated class, not the editor
	// graph. If the AnimBP was never compiled there is nothing baked to read.
	UAnimBlueprintGeneratedClass* AnimClass =
		Cast<UAnimBlueprintGeneratedClass>(AnimBlueprint->GeneratedClass);
	if (!AnimClass)
	{
		UE_LOG(LogMCAScripting, Error,
			TEXT("DumpBakedTransitions: '%s' has no generated class — compile it first"),
			*AnimBlueprint->GetName());
		return false;
	}

	const TArray<FBakedAnimationStateMachine>& Machines = AnimClass->GetBakedStateMachines();

	// Locate the requested baked machine by name.
	const FBakedAnimationStateMachine* Machine = nullptr;
	for (const FBakedAnimationStateMachine& Candidate : Machines)
	{
		if (Candidate.MachineName == FName(*StateMachineName))
		{
			Machine = &Candidate;
			break;
		}
	}
	if (!Machine)
	{
		// Help the caller by naming the baked machines that DO exist.
		FString Available;
		for (const FBakedAnimationStateMachine& Candidate : Machines)
		{
			Available += (Available.IsEmpty() ? TEXT("") : TEXT(", "));
			Available += Candidate.MachineName.ToString();
		}
		UE_LOG(LogMCAScripting, Error,
			TEXT("DumpBakedTransitions: Baked machine '%s' not found. Available: [%s]"),
			*StateMachineName, *Available);
		return false;
	}

	// Walk EVERY state's baked exit transitions. Listing exits per-source-state is what
	// exposes an edge the authoring-graph reader misses — a state's true runtime out-edges
	// are recorded right here in the compiled data, keyed off the state itself.
	for (const FBakedAnimationState& State : Machine->States)
	{
		for (const FBakedStateExitTransition& Exit : State.Transitions)
		{
			// The exit references a transition slot; resolve its destination state.
			FString ToName = TEXT("?");
			if (Machine->Transitions.IsValidIndex(Exit.TransitionIndex))
			{
				const FAnimationTransitionBetweenStates& Trans =
					Machine->Transitions[Exit.TransitionIndex];
				if (Machine->States.IsValidIndex(Trans.NextState))
				{
					ToName = Machine->States[Trans.NextState].StateName.ToString();
				}
			}

			OutTransitions.Add(FString::Printf(
				TEXT("%s -> %s [auto=%s desired=%s canTakeIdx=%d transIdx=%d]"),
				*State.StateName.ToString(),
				*ToName,
				Exit.bAutomaticRemainingTimeRule ? TEXT("true") : TEXT("false"),
				Exit.bDesiredTransitionReturnValue ? TEXT("true") : TEXT("false"),
				Exit.CanTakeDelegateIndex,
				Exit.TransitionIndex));
		}
	}

	UE_LOG(LogMCAScripting, Log,
		TEXT("DumpBakedTransitions: '%s' — %d baked exit transition(s) across %d state(s)"),
		*StateMachineName, OutTransitions.Num(), Machine->States.Num());

	return true;
}


// =============================================================================
// AnimGraph Pose-Flow Introspection
// =============================================================================

// File-local: build a meaningful one-line descriptor for an AnimGraph node. Names the
// load-bearing node types by their identity so the dump reads like the visual graph.
static FString MCA_DescribeAnimNode(UEdGraphNode* Node)
{
	if (!Node)
	{
		return TEXT("null");
	}
	if (UAnimGraphNode_StateMachine* SM = Cast<UAnimGraphNode_StateMachine>(Node))
	{
		return FString::Printf(TEXT("StateMachine('%s')"), *SM->GetStateMachineName());
	}
	if (UAnimGraphNode_Slot* Slot = Cast<UAnimGraphNode_Slot>(Node))
	{
		return FString::Printf(TEXT("Slot('%s')"), *Slot->Node.SlotName.ToString());
	}
	if (UAnimGraphNode_SaveCachedPose* Save = Cast<UAnimGraphNode_SaveCachedPose>(Node))
	{
		return FString::Printf(TEXT("SaveCachedPose('%s')"), *Save->CacheName);
	}
	if (UAnimGraphNode_UseCachedPose* Use = Cast<UAnimGraphNode_UseCachedPose>(Node))
	{
		// NameOfCache is private; read the public weak-ptr to the linked save node instead.
		const FString CacheNm = Use->SaveCachedPoseNode.IsValid()
			? Use->SaveCachedPoseNode->CacheName
			: TEXT("?");
		return FString::Printf(TEXT("UseCachedPose('%s')"), *CacheNm);
	}
	if (Cast<UAnimGraphNode_Root>(Node))
	{
		return TEXT("OutputPose");
	}

	// Fall back to the stripped class name (e.g. "BlendListByBool", "LayeredBoneBlend").
	FString Cls = Node->GetClass()->GetName();
	Cls.RemoveFromStart(TEXT("AnimGraphNode_"));
	return Cls;
}


bool UMCAAnimBlueprintLibrary::DumpAnimGraph(
	UAnimBlueprint* AnimBlueprint,
	TArray<FString>& OutNodes)
{
	OutNodes.Empty();

	if (!AnimBlueprint)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("DumpAnimGraph: AnimBlueprint is null"));
		return false;
	}

	UEdGraph* AnimGraph = GetAnimGraph(AnimBlueprint);
	if (!AnimGraph)
	{
		UE_LOG(LogMCAScripting, Error, TEXT("DumpAnimGraph: No AnimGraph found in '%s'"),
			*AnimBlueprint->GetName());
		return false;
	}

	// One line per node: its descriptor plus every LINKED input pin and the node feeding
	// it. Pose links reveal the relevancy chain; data-driver links (alpha/weight/bool)
	// reveal what could zero a branch and de-relevant a state machine downstream.
	for (UEdGraphNode* Node : AnimGraph->Nodes)
	{
		if (!Node)
		{
			continue;
		}

		const FString Desc = MCA_DescribeAnimNode(Node);

		TArray<FString> Links;
		for (UEdGraphPin* Pin : Node->Pins)
		{
			if (!Pin || Pin->Direction != EGPD_Input)
			{
				continue;
			}
			for (UEdGraphPin* Linked : Pin->LinkedTo)
			{
				if (!Linked)
				{
					continue;
				}
				Links.Add(FString::Printf(TEXT("%s:%s"),
					*Pin->PinName.ToString(),
					*MCA_DescribeAnimNode(Linked->GetOwningNode())));
			}
		}

		if (Links.Num() > 0)
		{
			OutNodes.Add(FString::Printf(TEXT("%s <- [%s]"), *Desc, *FString::Join(Links, TEXT(", "))));
		}
		else
		{
			OutNodes.Add(Desc);
		}
	}

	UE_LOG(LogMCAScripting, Log, TEXT("DumpAnimGraph: '%s' — %d AnimGraph node(s)"),
		*AnimBlueprint->GetName(), OutNodes.Num());

	return true;
}
