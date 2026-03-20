// Python Bridge — UE Python interpreter interface implementation.
//
// Provides in-process Python execution via IPythonScriptPlugin and
// synchronous output capture via ExecPythonCommandEx. The LogOutput
// array in FPythonCommandEx captures all print/warning/error output
// inline, avoiding the async timing issues of GEngine->Exec("py ...").

#include "PythonBridge.h"
#include "IPythonScriptPlugin.h"


// --- FPythonBridge Implementation --------------------------------------

FPythonBridge::FPythonBridge()
{
}


FPythonBridge::~FPythonBridge()
{
}


bool FPythonBridge::ExecuteCode(const FString& Code, FString& OutResult)
{
	if (!IsPythonAvailable())
	{
		OutResult = TEXT("Error: Python Script Plugin is not available. Enable it in Edit > Plugins.");
		OnPythonOutput.Broadcast(OutResult, TEXT("Error"), true);
		return false;
	}

	IPythonScriptPlugin* PythonPlugin = IPythonScriptPlugin::Get();
	if (!PythonPlugin)
	{
		OutResult = TEXT("Error: Could not get IPythonScriptPlugin instance.");
		OnPythonOutput.Broadcast(OutResult, TEXT("Error"), true);
		return false;
	}

	// Build the extended command struct for synchronous execution + output capture.
	FPythonCommandEx PythonCommand;
	PythonCommand.Command = Code;
	PythonCommand.ExecutionMode = EPythonCommandExecutionMode::ExecuteFile;
	PythonCommand.FileExecutionScope = EPythonFileExecutionScope::Public;

	// Execute synchronously — LogOutput is populated inline, no async delay.
	bool bSuccess = PythonPlugin->ExecPythonCommandEx(PythonCommand);

	// Route captured log output to the output panel via delegate.
	for (const FPythonLogOutputEntry& Entry : PythonCommand.LogOutput)
	{
		FString Severity;
		bool bIsError = false;

		switch (Entry.Type)
		{
		case EPythonLogOutputType::Error:
			Severity = TEXT("Error");
			bIsError = true;
			break;
		case EPythonLogOutputType::Warning:
			Severity = TEXT("Warning");
			break;
		default:
			Severity = TEXT("Info");
			break;
		}

		OnPythonOutput.Broadcast(Entry.Output, Severity, bIsError);
	}

	// If execution failed, the error (traceback) is in CommandResult, not LogOutput.
	// Broadcast it as an error so it appears in the output panel.
	if (!bSuccess && !PythonCommand.CommandResult.IsEmpty())
	{
		OnPythonOutput.Broadcast(PythonCommand.CommandResult, TEXT("Error"), true);
	}

	// Store the command result for callers that need it.
	OutResult = PythonCommand.CommandResult;

	return bSuccess;
}


bool FPythonBridge::ExecuteRemote(const FString& Code, const FString& Host, int32 Port, FString& OutResult)
{
	// TODO: Phase 1+ — Implement TCP Remote Execution protocol.
	// For now, fall back to in-process execution.
	return ExecuteCode(Code, OutResult);
}


bool FPythonBridge::IsPythonAvailable() const
{
	return FModuleManager::Get().IsModuleLoaded("PythonScriptPlugin");
}


FString FPythonBridge::GetPythonVersion() const
{
	if (!IsPythonAvailable())
	{
		return TEXT("N/A");
	}

	IPythonScriptPlugin* PythonPlugin = IPythonScriptPlugin::Get();
	if (!PythonPlugin)
	{
		return TEXT("N/A");
	}

	// Use ExecPythonCommandEx to capture the version output synchronously.
	FPythonCommandEx VersionCmd;
	VersionCmd.Command = TEXT("import sys; print(sys.version.split()[0])");
	VersionCmd.ExecutionMode = EPythonCommandExecutionMode::ExecuteFile;
	VersionCmd.FileExecutionScope = EPythonFileExecutionScope::Public;

	if (PythonPlugin->ExecPythonCommandEx(VersionCmd) && VersionCmd.LogOutput.Num() > 0)
	{
		return VersionCmd.LogOutput[0].Output;
	}

	return TEXT("3.11+");
}
