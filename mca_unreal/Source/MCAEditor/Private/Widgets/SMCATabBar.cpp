// MCA Tab Bar — Multi-file tab system implementation.
//
// Custom tab bar for managing open file tabs with modified indicators.
// Equivalent to mca_qt/widgets/drag_tab_manager.py.

#include "Widgets/SMCATabBar.h"
#include "MCAEditorStyle.h"

#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SMenuAnchor.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/Layout/SBox.h"
#include "Framework/MultiBox/MultiBoxBuilder.h"
#include "HAL/PlatformApplicationMisc.h"

#define LOCTEXT_NAMESPACE "SMCATabBar"


void SMCATabBar::Construct(const FArguments& InArgs)
{
	ActiveTabIndex = -1;
	OnTabSelectedDelegate = InArgs._OnTabSelected;
	OnTabCloseRequestedDelegate = InArgs._OnTabCloseRequested;

	ChildSlot
	[
		SAssignNew(TabContainer, SHorizontalBox)
	];
}


int32 SMCATabBar::AddTab(const FMCATabInfo& TabInfo)
{
	int32 NewIndex = Tabs.Add(TabInfo);

	// Set as active if it's the first tab.
	if (ActiveTabIndex < 0)
	{
		ActiveTabIndex = NewIndex;
	}

	RebuildTabBar();
	return NewIndex;
}


void SMCATabBar::RemoveTab(int32 TabIndex)
{
	if (!Tabs.IsValidIndex(TabIndex))
	{
		return;
	}

	Tabs.RemoveAt(TabIndex);

	// Adjust active tab index.
	if (ActiveTabIndex >= Tabs.Num())
	{
		ActiveTabIndex = Tabs.Num() - 1;
	}

	RebuildTabBar();

	// Notify about the new active tab if any remain.
	if (ActiveTabIndex >= 0)
	{
		OnTabSelectedDelegate.ExecuteIfBound(ActiveTabIndex);
	}
}


void SMCATabBar::SetActiveTab(int32 TabIndex)
{
	if (Tabs.IsValidIndex(TabIndex) && TabIndex != ActiveTabIndex)
	{
		ActiveTabIndex = TabIndex;
		RebuildTabBar();
		OnTabSelectedDelegate.ExecuteIfBound(TabIndex);
	}
}


int32 SMCATabBar::GetActiveTab() const
{
	return ActiveTabIndex;
}


const FMCATabInfo* SMCATabBar::GetTabInfo(int32 TabIndex) const
{
	if (Tabs.IsValidIndex(TabIndex))
	{
		return &Tabs[TabIndex];
	}
	return nullptr;
}


void SMCATabBar::SetTabModified(int32 TabIndex, bool bModified)
{
	if (Tabs.IsValidIndex(TabIndex))
	{
		Tabs[TabIndex].bIsModified = bModified;
		RebuildTabBar();
	}
}


void SMCATabBar::SetTabContent(int32 TabIndex, const FText& Content, int32 CursorLine, int32 CursorCol)
{
	if (Tabs.IsValidIndex(TabIndex))
	{
		Tabs[TabIndex].Content = Content;
		Tabs[TabIndex].CursorLine = CursorLine;
		Tabs[TabIndex].CursorColumn = CursorCol;
	}
}


int32 SMCATabBar::GetTabCount() const
{
	return Tabs.Num();
}


int32 SMCATabBar::FindTabByPath(const FString& FilePath) const
{
	for (int32 i = 0; i < Tabs.Num(); ++i)
	{
		if (Tabs[i].FilePath == FilePath)
		{
			return i;
		}
	}
	return -1;
}


void SMCATabBar::RebuildTabBar()
{
	if (!TabContainer.IsValid())
	{
		return;
	}

	// Clear all existing tab buttons.
	TabContainer->ClearChildren();

	// Add a button for each tab.
	for (int32 i = 0; i < Tabs.Num(); ++i)
	{
		const FMCATabInfo& Tab = Tabs[i];
		const bool bIsActive = (i == ActiveTabIndex);

		// Build display name with modified indicator.
		FString DisplayText = Tab.DisplayName;
		if (Tab.bIsModified)
		{
			DisplayText += TEXT(" *");
		}

		// Tab button background color: active vs inactive.
		FLinearColor BgColor = bIsActive ? FMCAEditorStyle::ActiveColor : FMCAEditorStyle::PanelColor;

		// Capture index for lambda.
		int32 TabIndex = i;

		TabContainer->AddSlot()
		.AutoWidth()
		.Padding(1.0f, 0.0f)
		[
			SNew(SMenuAnchor)
			.OnGetMenuContent(FOnGetContent::CreateSP(this, &SMCATabBar::BuildTabContextMenu, TabIndex))
			.Method(EPopupMethod::UseCurrentWindow)
			[
				SNew(SHorizontalBox)

				// Tab name button.
				+ SHorizontalBox::Slot()
				.AutoWidth()
				[
					SNew(SButton)
					.Text(FText::FromString(DisplayText))
					.OnClicked(FOnClicked::CreateSP(this, &SMCATabBar::OnTabClicked, TabIndex))
					.ButtonColorAndOpacity(BgColor)
				]

				// Close button (x).
				+ SHorizontalBox::Slot()
				.AutoWidth()
				.Padding(0.0f)
				[
					SNew(SButton)
					.Text(LOCTEXT("CloseTabX", "x"))
					.OnClicked(FOnClicked::CreateSP(this, &SMCATabBar::OnTabCloseClicked, TabIndex))
					.ButtonColorAndOpacity(BgColor)
				]
			]
		];
	}

	// Add "+" button to create new tab.
	TabContainer->AddSlot()
	.AutoWidth()
	.Padding(4.0f, 0.0f)
	[
		SNew(SButton)
		.Text(LOCTEXT("NewTab", "+"))
		.OnClicked(FOnClicked::CreateSP(this, &SMCATabBar::OnNewTabClicked))
	];
}


FReply SMCATabBar::OnTabClicked(int32 TabIndex)
{
	SetActiveTab(TabIndex);
	return FReply::Handled();
}


FReply SMCATabBar::OnTabCloseClicked(int32 TabIndex)
{
	OnTabCloseRequestedDelegate.ExecuteIfBound(TabIndex);
	return FReply::Handled();
}


FReply SMCATabBar::OnNewTabClicked()
{
	// Notify the parent panel to create a new file.
	FMCATabInfo NewTab;
	NewTab.DisplayName = TEXT("untitled.py");
	NewTab.bIsModified = false;
	NewTab.CursorLine = 1;
	NewTab.CursorColumn = 1;

	int32 NewIndex = AddTab(NewTab);
	SetActiveTab(NewIndex);

	return FReply::Handled();
}


TSharedRef<SWidget> SMCATabBar::BuildTabContextMenu(int32 TabIndex)
{
	FMenuBuilder MenuBuilder(true, nullptr);

	// Close this tab.
	MenuBuilder.AddMenuEntry(
		LOCTEXT("CloseTab", "Close"),
		LOCTEXT("CloseTabTooltip", "Close this tab"),
		FSlateIcon(),
		FUIAction(FExecuteAction::CreateSP(this, &SMCATabBar::OnContextMenuClose, TabIndex))
	);

	// Close Other Tabs.
	MenuBuilder.AddMenuEntry(
		LOCTEXT("CloseOtherTabs", "Close Others"),
		LOCTEXT("CloseOtherTabsTooltip", "Close all tabs except this one"),
		FSlateIcon(),
		FUIAction(FExecuteAction::CreateSP(this, &SMCATabBar::OnContextMenuCloseOthers, TabIndex))
	);

	// Close All Tabs.
	MenuBuilder.AddMenuEntry(
		LOCTEXT("CloseAllTabs", "Close All"),
		LOCTEXT("CloseAllTabsTooltip", "Close all open tabs"),
		FSlateIcon(),
		FUIAction(FExecuteAction::CreateSP(this, &SMCATabBar::OnContextMenuCloseAll))
	);

	MenuBuilder.AddMenuSeparator();

	// Copy File Path (only if file has been saved).
	if (Tabs.IsValidIndex(TabIndex) && !Tabs[TabIndex].FilePath.IsEmpty())
	{
		MenuBuilder.AddMenuEntry(
			LOCTEXT("CopyPath", "Copy Path"),
			LOCTEXT("CopyPathTooltip", "Copy the full file path to the clipboard"),
			FSlateIcon(),
			FUIAction(FExecuteAction::CreateSP(this, &SMCATabBar::OnContextMenuCopyPath, TabIndex))
		);
	}

	return MenuBuilder.MakeWidget();
}


void SMCATabBar::OnContextMenuClose(int32 TabIndex)
{
	OnTabCloseRequestedDelegate.ExecuteIfBound(TabIndex);
}


void SMCATabBar::OnContextMenuCloseOthers(int32 KeepTabIndex)
{
	// Close tabs from the end backwards to avoid index shifting.
	for (int32 i = Tabs.Num() - 1; i >= 0; --i)
	{
		if (i != KeepTabIndex)
		{
			OnTabCloseRequestedDelegate.ExecuteIfBound(i);
		}
	}
}


void SMCATabBar::OnContextMenuCloseAll()
{
	for (int32 i = Tabs.Num() - 1; i >= 0; --i)
	{
		OnTabCloseRequestedDelegate.ExecuteIfBound(i);
	}
}


void SMCATabBar::OnContextMenuCopyPath(int32 TabIndex)
{
	if (Tabs.IsValidIndex(TabIndex) && !Tabs[TabIndex].FilePath.IsEmpty())
	{
		FPlatformApplicationMisc::ClipboardCopy(*Tabs[TabIndex].FilePath);
	}
}


#undef LOCTEXT_NAMESPACE
