// MCA Editor Settings — UDeveloperSettings implementation.
//
// Default values mirror the Maya version's settings.py defaults.

#include "MCAEditorSettings.h"


UMCAEditorSettings::UMCAEditorSettings()
	: FontFamily(TEXT("Consolas"))
	, FontSize(12)
	, TabSize(4)
	, bUseSpaces(true)
	, bShowLineNumbers(true)
	, bWordWrap(false)
	, bAutoSaveOnExecute(false)
	, RemoteExecutionPort(0)  // 0 = in-process execution (no TCP)
{
}


const UMCAEditorSettings* UMCAEditorSettings::GetSettings()
{
	return GetDefault<UMCAEditorSettings>();
}
