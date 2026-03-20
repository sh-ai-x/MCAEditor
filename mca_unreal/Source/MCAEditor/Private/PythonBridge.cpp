// Python Bridge — UE Python interpreter interface implementation.
//
// Provides in-process Python execution via IPythonScriptPlugin and
// output capture via a custom FOutputDevice. The output capture
// strategy was informed by the Phase 0 spike (tools/ue_remote_exec_spike.py).

#include "PythonBridge.h"
#include "Misc/OutputDeviceRedirector.h"
#include "HAL/PlatformProcess.h"

// --- Custom Output Device for Capturing Python Output ------------------

/**
 * Custom FOutputDevice that intercepts log messages from Python execution.
 *
 * UE's Python plugin writes print() output through the log system.
 * We intercept it here and route it to the output panel via delegate.
 * This is the C++ equivalent of Maya's _StdoutTee / _StderrTee.
 */
class FMCAOutputDevice : public FOutputDevice
{
public:

	/** Delegate to broadcast captured output. */
	FOnPythonOutput* OutputDelegate;

	/** Whether we're currently capturing (prevents recursive capture). */
	bool bCapturing;

	FMCAOutputDevice()
		: OutputDelegate(nullptr)
		, bCapturing(false)
	{
	}

	virtual void Serialize(const TCHAR* V, ELogVerbosity::Type Verbosity, const FName& Category) override
	{
		// Only capture Python-related log messages.
		if (!bCapturing || !OutputDelegate)
		{
			return;
		}

		// Determine severity string for color coding in the output panel.
		FString Severity;
		bool bIsError = false;

		if (Verbosity == ELogVerbosity::Error || Verbosity == ELogVerbosity::Fatal)
		{
			Severity = TEXT("Error");
			bIsError = true;
		}
		else if (Verbosity == ELogVerbosity::Warning)
		{
			Severity = TEXT("Warning");
		}
		else
		{
			Severity = TEXT("Info");
		}

		// Broadcast the captured output.
		OutputDelegate->Broadcast(FString(V), Severity, bIsError);
	}
};


// --- FPythonBridge Implementation --------------------------------------

FPythonBridge::FPythonBridge()
{
	OutputDevice = MakeUnique<FMCAOutputDevice>();
	InstallOutputCapture();
}


FPythonBridge::~FPythonBridge()
{
	RemoveOutputCapture();
}


bool FPythonBridge::ExecuteCode(const FString& Code, FString& OutResult)
{
	if (!IsPythonAvailable())
	{
		OutResult = TEXT("Error: Python Script Plugin is not available. Enable it in Edit > Plugins.");
		OnPythonOutput.Broadcast(OutResult, TEXT("Error"), true);
		return false;
	}

	// Optionally wrap the code in a stdout redirect if the Phase 0 spike
	// determined that ExecPythonCommand doesn't return print() output.
	FString ExecutableCode = WrapCodeIfNeeded(Code);

	// Enable output capture before execution.
	OutputDevice->bCapturing = true;

	// Execute via UE's Python plugin.
	// IPythonScriptPlugin::Get()->ExecPythonCommand(*ExecutableCode) is the
	// primary execution path — equivalent to InternalMayaAdapter.execute().
	bool bSuccess = GEngine->Exec(nullptr, *FString::Printf(TEXT("py %s"), *ExecutableCode));

	// Disable capture after execution.
	OutputDevice->bCapturing = false;

	return bSuccess;
}


bool FPythonBridge::ExecuteRemote(const FString& Code, const FString& Host, int32 Port, FString& OutResult)
{
	// TODO: Phase 1+ — Implement TCP Remote Execution protocol.
	// This mirrors MayaAdapter's TCP socket communication.
	// The protocol is validated by tools/ue_remote_exec_spike.py.
	// For now, fall back to in-process execution.
	return ExecuteCode(Code, OutResult);
}


bool FPythonBridge::IsPythonAvailable() const
{
	// Check if the PythonScriptPlugin module is loaded.
	return FModuleManager::Get().IsModuleLoaded("PythonScriptPlugin");
}


FString FPythonBridge::GetPythonVersion() const
{
	if (!IsPythonAvailable())
	{
		return TEXT("N/A");
	}

	// Query the Python version via the interpreter.
	FString VersionResult;
	GEngine->Exec(nullptr, TEXT("py import sys; print(sys.version)"));

	// TODO: Capture the output from the above command.
	return TEXT("3.11+");
}


void FPythonBridge::InstallOutputCapture()
{
	// Wire up the output delegate so captured messages route to our panel.
	OutputDevice->OutputDelegate = &OnPythonOutput;

	// Register with the global output device redirector.
	GLog->AddOutputDevice(OutputDevice.Get());
}


void FPythonBridge::RemoveOutputCapture()
{
	if (OutputDevice.IsValid())
	{
		GLog->RemoveOutputDevice(OutputDevice.Get());
		OutputDevice->OutputDelegate = nullptr;
	}
}


FString FPythonBridge::WrapCodeIfNeeded(const FString& Code) const
{
	// TODO: Based on Phase 0 spike findings, determine if we need to wrap
	// the code in a stdout redirect pattern (like Maya's StringIO trick).
	//
	// If ExecPythonCommand returns print() output via GLog, we don't need
	// wrapping — our FMCAOutputDevice captures it directly.
	//
	// If it doesn't, wrap the code like this:
	//   import sys, io
	//   _buf = io.StringIO()
	//   sys.stdout = _buf
	//   exec(user_code)
	//   sys.stdout = sys.__stdout__
	//   print(_buf.getvalue())  # This goes through GLog
	//
	// For now, pass through unchanged — UE's Python plugin typically
	// routes print() through GLog, so direct capture should work.
	return Code;
}
