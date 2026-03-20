// Python Bridge — Interface to UE's Python interpreter.
//
// Provides two execution modes mirroring Maya's dual adapter pattern:
//   1. In-Process: Direct execution via IPythonScriptPlugin (like InternalMayaAdapter)
//   2. Remote: TCP via UE Remote Execution protocol (like MayaAdapter)
//
// Output is captured synchronously via ExecPythonCommandEx's LogOutput
// array. This avoids the async timing issues of GEngine->Exec("py ...").

#pragma once

#include "CoreMinimal.h"

/** Delegate fired when Python produces output (print, warnings, errors). */
DECLARE_MULTICAST_DELEGATE_ThreeParams(FOnPythonOutput, const FString& /* Output */, const FString& /* Severity */, bool /* bIsError */);

/**
 * Bridge between MCA Editor and UE's Python interpreter.
 *
 * Handles code execution, output capture, and (optionally) remote
 * execution via the UE Remote Execution TCP protocol.
 */
class FPythonBridge
{
public:

	FPythonBridge();
	~FPythonBridge();

	// --- Execution --------------------------------------------------------

	/**
	 * Execute Python code in-process via UE's Python plugin.
	 *
	 * Uses IPythonScriptPlugin::ExecPythonCommandEx internally.
	 * Output is captured synchronously in the LogOutput array and
	 * broadcast through the OnPythonOutput delegate.
	 *
	 * @param Code      The Python code string to execute.
	 * @param OutResult The command result text (if any).
	 * @return True if execution succeeded without errors.
	 */
	bool ExecuteCode(const FString& Code, FString& OutResult);

	/**
	 * Execute Python code on a remote UE instance via TCP.
	 *
	 * Uses the Remote Execution protocol (same as ue_remote_exec_spike.py).
	 * Falls back to in-process if remote connection fails.
	 *
	 * @param Code      The Python code string to execute.
	 * @param Host      Remote host IP (default "127.0.0.1").
	 * @param Port      Remote command port (default 6776).
	 * @param OutResult The captured result text.
	 * @return True if execution succeeded.
	 */
	bool ExecuteRemote(const FString& Code, const FString& Host, int32 Port, FString& OutResult);

	// --- State ------------------------------------------------------------

	/** Check if the Python Script Plugin is available and loaded. */
	bool IsPythonAvailable() const;

	/** Get the Python version string from UE's interpreter. */
	FString GetPythonVersion() const;

	// --- Output Delegate --------------------------------------------------

	/** Broadcast delegate for Python output. UI widgets bind to this. */
	FOnPythonOutput OnPythonOutput;
};
