// MCA Editor Module — Plugin entry point and tab registration.
//
// Registers the MCA Editor nomad tab spawner, toolbar button, and
// Window menu entry. The tab content is an SMCANativeHost which
// embeds the full PySide6/Qt editor (same codebase as Maya version).

#include "MCAEditorModule.h"
#include "MCAEditorCommands.h"
#include "MCAEditorStyle.h"
#include "MCALicenseCheck.h"
#include "Widgets/SMCANativeHost.h"

#include "Framework/Docking/TabManager.h"
#include "Framework/MultiBox/MultiBoxBuilder.h"
#include "LevelEditor.h"
#include "ToolMenus.h"
#include "Widgets/Docking/SDockTab.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/Layout/SBox.h"

// Define our custom log category.
DEFINE_LOG_CATEGORY(LogMCAEditor);

#define LOCTEXT_NAMESPACE "FMCAEditorModule"

// Tab name constant — used for spawner registration and invocation.
const FName FMCAEditorModule::MCAEditorTabName(TEXT("MCAEditor"));


void FMCAEditorModule::StartupModule()
{
	// Initialize the Slate style set (dark theme colors, fonts, icons).
	FMCAEditorStyle::Initialize();
	FMCAEditorStyle::ReloadTextures();

	// Register the UI command set (Execute, Save, Open, etc.).
	FMCAEditorCommands::Register();

	// --- Nomad Tab Spawner ------------------------------------------------
	// Register a global (nomad) tab that can be docked anywhere in the
	// UE editor layout, just like Output Log or Content Browser.
	FGlobalTabmanager::Get()->RegisterNomadTabSpawner(
		MCAEditorTabName,
		FOnSpawnTab::CreateRaw(this, &FMCAEditorModule::SpawnMCAEditorTab)
	)
	.SetDisplayName(LOCTEXT("TabTitle", "MCA Editor"))
	.SetMenuType(ETabSpawnerMenuType::Enabled)
	.SetTooltipText(LOCTEXT("TabTooltip", "Open the MCA Python Code Editor"))
	.SetIcon(FSlateIcon(FMCAEditorStyle::GetStyleSetName(), "MCAEditor.TabIcon"));

	// Register toolbar and menu extensions once ToolMenus is ready.
	UToolMenus::RegisterStartupCallback(
		FSimpleMulticastDelegate::FDelegate::CreateRaw(this, &FMCAEditorModule::RegisterToolbarExtension)
	);
	RegisterMenuExtension();
}


void FMCAEditorModule::ShutdownModule()
{
	// Clean up in reverse order of registration.
	UToolMenus::UnRegisterStartupCallback(this);
	UToolMenus::UnregisterOwner(this);

	FMCAEditorCommands::Unregister();
	FMCAEditorStyle::Shutdown();

	FGlobalTabmanager::Get()->UnregisterNomadTabSpawner(MCAEditorTabName);
}


TSharedRef<SDockTab> FMCAEditorModule::SpawnMCAEditorTab(const FSpawnTabArgs& Args)
{
	// --- License check — gate editor access behind valid key or trial ---
	FMCALicenseStatus LicenseStatus = FMCALicenseCheck::CheckLicense();

	TSharedRef<SDockTab> Tab = SNew(SDockTab)
		.TabRole(NomadTab);

	if (LicenseStatus.bNeedsKey)
	{
		// Trial expired and no valid key — show license entry UI.
		Tab->SetContent(BuildLicensePanel(Tab));
	}
	else
	{
		// Licensed or trial active — show the Qt-embedded editor.
		// SMCANativeHost handles all the PySide6 embedding on first tick.
		Tab->SetContent(SNew(SMCANativeHost));

		UE_LOG(LogMCAEditor, Log, TEXT("MCAEditor: %s"), *LicenseStatus.Message);
	}

	return Tab;
}


TSharedRef<SWidget> FMCAEditorModule::BuildLicensePanel(TSharedRef<SDockTab> OwnerTab)
{
	// Build a centered license key entry panel shown when the trial has expired.
	TSharedPtr<SEditableTextBox> KeyInput;
	TSharedPtr<STextBlock> StatusText;

	return SNew(SBox)
		.HAlign(HAlign_Center)
		.VAlign(VAlign_Center)
		.Padding(40.0f)
		[
			SNew(SVerticalBox)

			// --- Title ---
			+ SVerticalBox::Slot()
			.AutoHeight()
			.Padding(0.0f, 0.0f, 0.0f, 8.0f)
			[
				SNew(STextBlock)
				.Text(LOCTEXT("LicenseTitle", "MCA Editor — License Required"))
				.Font(FCoreStyle::GetDefaultFontStyle("Bold", 16))
				.Justification(ETextJustify::Center)
			]

			// --- Message ---
			+ SVerticalBox::Slot()
			.AutoHeight()
			.Padding(0.0f, 0.0f, 0.0f, 16.0f)
			[
				SNew(STextBlock)
				.Text(LOCTEXT("LicenseMessage", "Your 14-day trial has expired. Please enter a license key to continue."))
				.Justification(ETextJustify::Center)
				.AutoWrapText(true)
			]

			// --- Key Input ---
			+ SVerticalBox::Slot()
			.AutoHeight()
			.Padding(0.0f, 0.0f, 0.0f, 8.0f)
			[
				SNew(SBox)
				.WidthOverride(400.0f)
				.HAlign(HAlign_Center)
				[
					SAssignNew(KeyInput, SEditableTextBox)
					.HintText(LOCTEXT("KeyHint", "MCA-XXXX-XXXX-XXXX-XXXX"))
				]
			]

			// --- Status label (shows validation result) ---
			+ SVerticalBox::Slot()
			.AutoHeight()
			.Padding(0.0f, 0.0f, 0.0f, 8.0f)
			[
				SAssignNew(StatusText, STextBlock)
				.Text(FText::GetEmpty())
				.Justification(ETextJustify::Center)
				.ColorAndOpacity(FLinearColor::Red)
			]

			// --- Activate Button ---
			+ SVerticalBox::Slot()
			.AutoHeight()
			.HAlign(HAlign_Center)
			[
				SNew(SButton)
				.Text(LOCTEXT("ActivateButton", "Activate"))
				.OnClicked_Lambda([KeyInput, StatusText, OwnerTab]() -> FReply
				{
					if (!KeyInput.IsValid())
					{
						return FReply::Handled();
					}

					FString Key = KeyInput->GetText().ToString();
					FMCALicenseResult Result = FMCALicenseCheck::StoreKey(Key);

					if (Result.bValid)
					{
						// Key accepted — replace the license panel with the Qt editor.
						OwnerTab->SetContent(SNew(SMCANativeHost));

						UE_LOG(LogMCAEditor, Log, TEXT("MCAEditor: License activated (expires: %s)"), *Result.ExpiryDate);
					}
					else
					{
						if (StatusText.IsValid())
						{
							StatusText->SetText(FText::FromString(Result.Error));
						}
					}

					return FReply::Handled();
				})
			]
		];
}


void FMCAEditorModule::RegisterToolbarExtension()
{
	// Add a toolbar button to the main editor toolbar.
	UToolMenu* ToolbarMenu = UToolMenus::Get()->ExtendMenu("LevelEditor.LevelEditorToolBar.PlayToolBar");
	if (ToolbarMenu)
	{
		FToolMenuSection& Section = ToolbarMenu->FindOrAddSection("MCAEditor");
		Section.AddEntry(FToolMenuEntry::InitToolBarButton(
			"OpenMCAEditor",
			FUIAction(FExecuteAction::CreateRaw(this, &FMCAEditorModule::OnToolbarButtonClicked)),
			LOCTEXT("ToolbarButton", "MCA Editor"),
			LOCTEXT("ToolbarButtonTooltip", "Open the MCA Python Code Editor"),
			FSlateIcon(FMCAEditorStyle::GetStyleSetName(), "MCAEditor.ToolbarIcon")
		));
	}
}


void FMCAEditorModule::RegisterMenuExtension()
{
	// Add "MCA Editor" entry under the Window menu.
	UToolMenu* WindowMenu = UToolMenus::Get()->ExtendMenu("LevelEditor.MainMenu.Window");
	if (WindowMenu)
	{
		FToolMenuSection& Section = WindowMenu->FindOrAddSection("MCAEditor");
		Section.AddMenuEntry(
			"OpenMCAEditor",
			LOCTEXT("MenuEntry", "MCA Editor"),
			LOCTEXT("MenuEntryTooltip", "Open the MCA Python Code Editor"),
			FSlateIcon(),
			FUIAction(FExecuteAction::CreateRaw(this, &FMCAEditorModule::OnToolbarButtonClicked))
		);
	}
}


void FMCAEditorModule::OnToolbarButtonClicked()
{
	FGlobalTabmanager::Get()->TryInvokeTab(MCAEditorTabName);
}


#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FMCAEditorModule, MCAEditor)
