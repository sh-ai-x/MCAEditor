// MCA Animation Blueprint Library — Public API header.
//
// Exposes Animation Blueprint graph editing operations to Python.
// These functions let you programmatically create AnimBPs, add state
// machines, states, transitions, and wire them up — operations that
// are normally only possible through the visual graph editor UI.
//
// All functions are static BlueprintCallable, so they appear in Python as:
//   unreal.MCAAnimBlueprintLibrary.create_anim_blueprint(...)
//   unreal.MCAAnimBlueprintLibrary.add_state_machine(...)

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "MCAAnimBlueprintLibrary.generated.h"

class UAnimBlueprint;
class USkeleton;
class UAnimSequenceBase;

/**
 * Static library of Animation Blueprint graph editing functions.
 *
 * Exposes operations that are normally only available through UE's
 * visual AnimBP editor — state machine creation, state management,
 * transition wiring, and animation assignment.
 *
 * All write operations are wrapped in FScopedTransaction for Ctrl+Z
 * undo support. All functions accept asset paths or loaded UObjects.
 */
UCLASS()
class MCAEDITORSCRIPTING_API UMCAAnimBlueprintLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:

	// --- AnimBP Creation ---------------------------------------------------

	/**
	 * Create a new Animation Blueprint asset.
	 *
	 * @param PackagePath  Content path for the new asset (e.g. "/Game/Characters/AnimBPs").
	 * @param AssetName    Name for the new AnimBP asset (e.g. "ABP_MyCharacter").
	 * @param Skeleton     The skeleton this AnimBP targets.
	 * @return The created AnimBlueprint, or nullptr on failure.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Animation Blueprint",
		meta = (DisplayName = "Create Animation Blueprint"))
	static UAnimBlueprint* CreateAnimBlueprint(
		const FString& PackagePath,
		const FString& AssetName,
		USkeleton* Skeleton
	);

	// --- State Machine Operations ------------------------------------------

	/**
	 * Add a new state machine to an Animation Blueprint's AnimGraph.
	 *
	 * Creates an UAnimGraphNode_StateMachine node in the AnimBP's root
	 * AnimGraph and wires it to the output pose.
	 *
	 * @param AnimBlueprint     The target Animation Blueprint.
	 * @param StateMachineName  Name for the new state machine.
	 * @param bConnectToRoot    If true, wire the state machine's output to the AnimGraph's output pose.
	 * @return True if the state machine was created successfully.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Animation Blueprint",
		meta = (DisplayName = "Add State Machine"))
	static bool AddStateMachine(
		UAnimBlueprint* AnimBlueprint,
		const FString& StateMachineName,
		bool bConnectToRoot = true
	);

	/**
	 * List all state machines in an Animation Blueprint.
	 *
	 * @param AnimBlueprint  The Animation Blueprint to inspect.
	 * @param OutNames       Output array of state machine names.
	 * @return True if the AnimBP was valid and inspected.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Animation Blueprint",
		meta = (DisplayName = "List State Machines"))
	static bool ListStateMachines(
		UAnimBlueprint* AnimBlueprint,
		TArray<FString>& OutNames
	);

	// --- State Operations --------------------------------------------------

	/**
	 * Add a new state to a state machine.
	 *
	 * @param AnimBlueprint     The Animation Blueprint containing the state machine.
	 * @param StateMachineName  Name of the target state machine.
	 * @param StateName         Name for the new state.
	 * @return True if the state was created successfully.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Animation Blueprint",
		meta = (DisplayName = "Add State"))
	static bool AddState(
		UAnimBlueprint* AnimBlueprint,
		const FString& StateMachineName,
		const FString& StateName
	);

	/**
	 * Set the default state (entry point) of a state machine.
	 *
	 * Wires the state machine's entry node to the specified state.
	 *
	 * @param AnimBlueprint     The Animation Blueprint.
	 * @param StateMachineName  Name of the state machine.
	 * @param StateName         Name of the state to use as entry.
	 * @return True if the entry was set successfully.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Animation Blueprint",
		meta = (DisplayName = "Set Default State"))
	static bool SetDefaultState(
		UAnimBlueprint* AnimBlueprint,
		const FString& StateMachineName,
		const FString& StateName
	);

	/**
	 * List all states in a state machine.
	 *
	 * @param AnimBlueprint     The Animation Blueprint.
	 * @param StateMachineName  Name of the state machine to inspect.
	 * @param OutNames          Output array of state names.
	 * @return True if the state machine was found and inspected.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Animation Blueprint",
		meta = (DisplayName = "List States"))
	static bool ListStates(
		UAnimBlueprint* AnimBlueprint,
		const FString& StateMachineName,
		TArray<FString>& OutNames
	);

	/**
	 * List all transitions in a state machine.
	 *
	 * Each entry is formatted "FromState -> ToState" so a caller can see the
	 * graph topology and then inspect/author individual transition rules.
	 *
	 * @param AnimBlueprint     The Animation Blueprint.
	 * @param StateMachineName  Name of the state machine to inspect.
	 * @param OutTransitions    Output array of "From -> To" strings.
	 * @return True if the state machine was found and inspected.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Animation Blueprint",
		meta = (DisplayName = "List Transitions"))
	static bool ListTransitions(
		UAnimBlueprint* AnimBlueprint,
		const FString& StateMachineName,
		TArray<FString>& OutTransitions
	);

	// --- Animation Assignment ----------------------------------------------

	/**
	 * Set the animation asset for a state.
	 *
	 * Creates or replaces the animation player node inside the state's
	 * bound graph, wired to the state's output pose pin.
	 *
	 * @param AnimBlueprint     The Animation Blueprint.
	 * @param StateMachineName  Name of the state machine.
	 * @param StateName         Name of the state.
	 * @param AnimAsset         The animation asset (AnimSequence or BlendSpace).
	 * @return True if the animation was set successfully.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Animation Blueprint",
		meta = (DisplayName = "Set State Animation"))
	static bool SetStateAnimation(
		UAnimBlueprint* AnimBlueprint,
		const FString& StateMachineName,
		const FString& StateName,
		UAnimSequenceBase* AnimAsset
	);

	// --- Anim Notify Operations --------------------------------------------

	/**
	 * Add a simple named AnimNotify to an animation sequence at a given time.
	 *
	 * Creates a plain (non-state) notify with the given name on the sequence's
	 * timeline. Use this to mark animation events the gameplay/driver layer
	 * listens for — e.g. an "End_Sit" notify at the end of a stand-up clip so
	 * the driver can release its movement lock at animation-precise timing.
	 *
	 * @param AnimSequence  The animation sequence to modify.
	 * @param NotifyName    Name of the notify event (e.g. "End_Sit").
	 * @param TriggerTime   Time in seconds along the sequence to place the notify.
	 * @return True if the notify was added.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Animation Blueprint",
		meta = (DisplayName = "Add Anim Notify"))
	static bool AddAnimNotify(
		UAnimSequenceBase* AnimSequence,
		const FString& NotifyName,
		float TriggerTime
	);

	/**
	 * List the named notifies on an animation sequence.
	 *
	 * Each entry is formatted "NotifyName@Time" (time in seconds, 3 decimals).
	 * This is the read-back counterpart to AddAnimNotify — the sequence's
	 * Notifies array is protected and not readable from Python, so this C++
	 * accessor is the only way to verify notify state programmatically.
	 *
	 * @param AnimSequence  The animation sequence to inspect.
	 * @param OutNotifies   Output array of "Name@Time" strings.
	 * @return True if the sequence was valid and inspected.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Animation Blueprint",
		meta = (DisplayName = "List Anim Notifies"))
	static bool ListAnimNotifies(
		UAnimSequenceBase* AnimSequence,
		TArray<FString>& OutNotifies
	);

	// --- Transition Operations ---------------------------------------------

	/**
	 * Add a transition between two states.
	 *
	 * Creates a transition node connecting the output of FromState to
	 * the input of ToState.
	 *
	 * @param AnimBlueprint     The Animation Blueprint.
	 * @param StateMachineName  Name of the state machine.
	 * @param FromStateName     Source state name.
	 * @param ToStateName       Destination state name.
	 * @param CrossfadeDuration Blend duration in seconds (default 0.2).
	 * @return True if the transition was created.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Animation Blueprint",
		meta = (DisplayName = "Add Transition"))
	static bool AddTransition(
		UAnimBlueprint* AnimBlueprint,
		const FString& StateMachineName,
		const FString& FromStateName,
		const FString& ToStateName,
		float CrossfadeDuration = 0.2f
	);

	/**
	 * Set an automatic rule on a transition based on remaining animation time.
	 *
	 * This configures the transition to fire automatically when the source
	 * state's animation has the specified time remaining — the most common
	 * transition rule for animation state machines.
	 *
	 * @param AnimBlueprint     The Animation Blueprint.
	 * @param StateMachineName  Name of the state machine.
	 * @param FromStateName     Source state (identifies the transition).
	 * @param ToStateName       Destination state (identifies the transition).
	 * @param TriggerTime       Time remaining (seconds) to trigger transition.
	 * @return True if the rule was set.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Animation Blueprint",
		meta = (DisplayName = "Set Auto Transition Rule"))
	static bool SetAutoTransitionRule(
		UAnimBlueprint* AnimBlueprint,
		const FString& StateMachineName,
		const FString& FromStateName,
		const FString& ToStateName,
		float TriggerTime = 0.0f
	);

	/**
	 * Set a bool-variable condition on an existing transition.
	 *
	 * Authors the transition's rule graph so the transition fires based on a
	 * boolean AnimBP variable — "Var == true" wires the variable straight into
	 * the result; "Var == false" inserts a boolean NOT. This is the real
	 * data-driven rule (e.g. IsSitting == false to leave a sit state), as
	 * opposed to the time-remaining SetAutoTransitionRule.
	 *
	 * The variable must already exist on the Animation Blueprint (self member).
	 * Any existing rule wiring on the transition is replaced.
	 *
	 * @param AnimBlueprint     The Animation Blueprint.
	 * @param StateMachineName  Name of the state machine.
	 * @param FromStateName     Source state (identifies the transition).
	 * @param ToStateName       Destination state (identifies the transition).
	 * @param BoolVariableName  Name of the bool variable on the AnimBP.
	 * @param bEqualsValue      The value the variable must equal for the transition to fire.
	 * @return True if the condition was authored.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Animation Blueprint",
		meta = (DisplayName = "Set Transition Bool Condition"))
	static bool SetTransitionBoolCondition(
		UAnimBlueprint* AnimBlueprint,
		const FString& StateMachineName,
		const FString& FromStateName,
		const FString& ToStateName,
		const FString& BoolVariableName,
		bool bEqualsValue
	);

	// --- Compilation -------------------------------------------------------

	/**
	 * Compile an Animation Blueprint and report the result.
	 *
	 * @param AnimBlueprint  The Animation Blueprint to compile.
	 * @return True if compilation succeeded with no errors.
	 */
	UFUNCTION(BlueprintCallable, Category = "MCA|Animation Blueprint",
		meta = (DisplayName = "Compile Animation Blueprint"))
	static bool CompileAnimBlueprint(UAnimBlueprint* AnimBlueprint);

private:

	// --- Internal Helpers --------------------------------------------------

	/** Find a state machine graph by name inside an AnimBP. */
	static class UAnimationStateMachineGraph* FindStateMachineGraph(
		UAnimBlueprint* AnimBlueprint,
		const FString& StateMachineName
	);

	/** Find a state node by name inside a state machine graph. */
	static class UAnimStateNode* FindStateNode(
		class UAnimationStateMachineGraph* SMGraph,
		const FString& StateName
	);

	/** Find a transition between two states. */
	static class UAnimStateTransitionNode* FindTransition(
		class UAnimationStateMachineGraph* SMGraph,
		const FString& FromStateName,
		const FString& ToStateName
	);

	/** Get the root AnimGraph from an AnimBP. */
	static class UEdGraph* GetAnimGraph(UAnimBlueprint* AnimBlueprint);
};
