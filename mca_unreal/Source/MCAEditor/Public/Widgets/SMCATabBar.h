// MCA Tab Bar — Multi-file tab system.
//
// Custom tab bar for managing multiple open files with modified indicators,
// close buttons, and drag-to-reorder. Mirrors the tab system in
// mca_qt/widgets/drag_tab_manager.py.

#pragma once

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/DeclarativeSyntaxSupport.h"

/**
 * Represents a single open file tab.
 */
struct FMCATabInfo
{
	/** Display name (filename). */
	FString DisplayName;

	/** Full file path (empty for unsaved files). */
	FString FilePath;

	/** Whether the file has unsaved changes. */
	bool bIsModified;

	/** The text content (for switching between tabs without re-reading). */
	FText Content;

	/** Cursor line position to restore on tab switch. */
	int32 CursorLine;

	/** Cursor column position to restore on tab switch. */
	int32 CursorColumn;
};

/** Delegate fired when a tab is selected. */
DECLARE_DELEGATE_OneParam(FOnTabSelected, int32 /* TabIndex */);

/** Delegate fired when a tab close is requested. */
DECLARE_DELEGATE_OneParam(FOnTabCloseRequested, int32 /* TabIndex */);

/**
 * Multi-file tab bar widget.
 *
 * Features:
 *   - Tab buttons with file name display
 *   - Modified indicator (asterisk on unsaved files)
 *   - Close button per tab
 *   - Middle-click to close
 *   - Tab context menu (Close Others, Close All, Copy Path)
 *   - "+" button to create new tab
 */
class SMCATabBar : public SCompoundWidget
{
public:

	SLATE_BEGIN_ARGS(SMCATabBar) {}
		/** Called when a tab is clicked to select it. */
		SLATE_EVENT(FOnTabSelected, OnTabSelected)

		/** Called when a tab's close button is clicked. */
		SLATE_EVENT(FOnTabCloseRequested, OnTabCloseRequested)
	SLATE_END_ARGS()

	/** Construct the widget. */
	void Construct(const FArguments& InArgs);

	// --- Tab Management ----------------------------------------------------

	/** Add a new tab. Returns the tab index. */
	int32 AddTab(const FMCATabInfo& TabInfo);

	/** Remove a tab by index. */
	void RemoveTab(int32 TabIndex);

	/** Set the active (selected) tab. */
	void SetActiveTab(int32 TabIndex);

	/** Get the currently active tab index (-1 if none). */
	int32 GetActiveTab() const;

	/** Get tab info by index. */
	const FMCATabInfo* GetTabInfo(int32 TabIndex) const;

	/** Update the modified state of a tab. */
	void SetTabModified(int32 TabIndex, bool bModified);

	/** Update the content stored in a tab. */
	void SetTabContent(int32 TabIndex, const FText& Content, int32 CursorLine, int32 CursorCol);

	/** Get the number of open tabs. */
	int32 GetTabCount() const;

	/** Find a tab by file path. Returns index or -1 if not found. */
	int32 FindTabByPath(const FString& FilePath) const;

private:

	// --- Internal ----------------------------------------------------------

	/** Rebuild the tab bar UI after any tab changes. */
	void RebuildTabBar();

	/** Handle tab button click. */
	FReply OnTabClicked(int32 TabIndex);

	/** Handle tab close button click. */
	FReply OnTabCloseClicked(int32 TabIndex);

	/** Handle "+" new tab button. */
	FReply OnNewTabClicked();

	/** Build context menu for right-clicking a tab. */
	TSharedRef<SWidget> BuildTabContextMenu(int32 TabIndex);

	// --- Child Widgets -----------------------------------------------------

	/** Container for the tab buttons. */
	TSharedPtr<SHorizontalBox> TabContainer;

	// --- State -------------------------------------------------------------

	/** All open tabs. */
	TArray<FMCATabInfo> Tabs;

	/** Currently active tab index. */
	int32 ActiveTabIndex;

	// --- Delegates ---------------------------------------------------------

	FOnTabSelected OnTabSelectedDelegate;
	FOnTabCloseRequested OnTabCloseRequestedDelegate;
};
