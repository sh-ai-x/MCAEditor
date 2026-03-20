// Python Bridge — Interface to UE's Python interpreter.
//
// Provides two execution modes mirroring Maya's dual adapter pattern:
//   1. In-Process: Direct execution via IPythonScriptPlugin (like InternalMayaAdapter)
//   2. Remote: TCP via UE Remote Execution protocol (like MayaAdapter)
//
// Output capture strategy is determined by the Phase 0 spike
// (tools/ue_remote_exec_spike.py). If ExecPythonCommand doesn't return
// stdout, we wrap code in a StringIO redirect pattern.

#pragma once

#include "CoreMinimal.h"

// Forward declare the output device.
class FMCAOutputDevice;

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
	 * Uses IPythonScriptPlugin::ExecPythonCommand internally.
	 * Output is captured via a custom FOutputDevice and broadcast
	 * through the OnPythonOutput delegate.
	 *
	 * @param Code      The Python code string to execute.
	 * @param OutResult The captured stdout/result text (if any).
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

private:

	// --- Output Capture ---------------------------------------------------

	/** Custom output device that intercepts Python log messages. */
	TUniquePtr<FMCAOutputDevice> OutputDevice;

	/** Install the output device to capture Python prints. */
	void InstallOutputCapture();

	/** Remove the output device. */
	void RemoveOutputCapture();

	/**
	 * Wrap code in a stdout redirect if needed.
	 *
	 * If the Phase 0 spike determined that ExecPythonCommand doesn't
	 * return print() output in a capturable way, this method wraps
	 * the code in a StringIO redirect pattern.
	 *
	 * @param Code The original code to potentially wrap.
	 * @return The (possibly wrapped) code string.
	 */
	FString WrapCodeIfNeeded(const FString& Code) const;
};
