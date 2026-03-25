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
