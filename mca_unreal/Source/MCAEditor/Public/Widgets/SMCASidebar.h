// MCA Sidebar — File tree browser.
//
// STreeView-based file browser with directory watching, file icons,
// and context menus. Mirrors the sidebar in mca_qt/editor_panel.py.

#pragma once

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/DeclarativeSyntaxSupport.h"
#include "Widgets/Views/STreeView.h"

/**
 * Represents a file or directory in the sidebar tree.
 */
struct FMCAFileItem
{
	/** Display name (filename or directory name). */
	FString DisplayName;

	/** Full absolute path. */
	FString FullPath;

	/** Whether this is a directory. */
	bool bIsDirectory;

	/** Child items (populated for directories). */
	TArray<TSharedPtr<FMCAFileItem>> Children;
};

/** Delegate fired when a file is selected in the sidebar. */
DECLARE_DELEGATE_OneParam(FOnSidebarFileSelected, const FString& /* FilePath */);

/**
 * File tree browser sidebar.
 *
 * Features:
 *   - Recursive directory tree view
 *   - File type icons (.py, .txt, .json, folders)
 *   - Directory watching (auto-refresh on filesystem changes)
 *   - Right-click context menu (New File, Rename, Delete, Reveal)
 *   - Single-click to preview, double-click to open in tab
 */
class SMCASidebar : public SCompoundWidget
{
public:

	SLATE_BEGIN_ARGS(SMCASidebar) {}
		/** Called when a file is double-clicked for opening. */
		SLATE_EVENT(FOnSidebarFileSelected, OnFileSelected)
	SLATE_END_ARGS()

	/** Construct the widget. */
	void Construct(const FArguments& InArgs);

	/** Set the root directory for the file tree. */
	void SetRootDirectory(const FString& DirectoryPath);

	/** Refresh the file tree from the filesystem. */
	void RefreshTree();

private:

	// --- Tree View Callbacks -----------------------------------------------

	/** Generate a row widget for a tree item. */
	TSharedRef<ITableRow> OnGenerateRow(TSharedPtr<FMCAFileItem> Item, const TSharedRef<STableViewBase>& OwnerTable);

	/** Get children for a tree item. */
	void OnGetChildren(TSharedPtr<FMCAFileItem> Item, TArray<TSharedPtr<FMCAFileItem>>& OutChildren);

	/** Handle double-click on a tree item (open file). */
	void OnItemDoubleClicked(TSharedPtr<FMCAFileItem> Item);

	/** Build right-click context menu. */
	TSharedPtr<SWidget> OnContextMenuOpening();

	// --- Context Menu Actions ----------------------------------------------

	/** Create a new file in the selected directory. */
	void OnContextMenuNewFile(TSharedPtr<FMCAFileItem> ContextItem);

	/** Create a new folder in the selected directory. */
	void OnContextMenuNewFolder(TSharedPtr<FMCAFileItem> ContextItem);

	/** Rename the selected item. */
	void OnContextMenuRename(TSharedPtr<FMCAFileItem> ContextItem);

	/** Delete the selected item. */
	void OnContextMenuDelete(TSharedPtr<FMCAFileItem> ContextItem);

	/** Open the containing folder in the system file browser. */
	void OnContextMenuRevealInExplorer(TSharedPtr<FMCAFileItem> ContextItem);

	/** Copy the full path to the clipboard. */
	void OnContextMenuCopyPath(TSharedPtr<FMCAFileItem> ContextItem);

	// --- File System -------------------------------------------------------

	/** Recursively scan a directory and populate the tree. */
	void ScanDirectory(const FString& DirectoryPath, TArray<TSharedPtr<FMCAFileItem>>& OutItems);

	/** Handle directory change notifications. */
	void OnDirectoryChanged(const TArray<struct FFileChangeData>& FileChanges);

	// --- Child Widgets -----------------------------------------------------

	/** The tree view widget. */
	TSharedPtr<STreeView<TSharedPtr<FMCAFileItem>>> TreeView;

	// --- State -------------------------------------------------------------

	/** Root directory being browsed. */
	FString RootPath;

	/** Root items in the tree. */
	TArray<TSharedPtr<FMCAFileItem>> RootItems;

	/** Directory watcher delegate handle. */
	FDelegateHandle DirectoryWatcherHandle;

	// --- Delegates ---------------------------------------------------------

	FOnSidebarFileSelected OnFileSelectedDelegate;
};
