// MCA Sidebar — File tree browser implementation.
//
// STreeView-based directory browser with filesystem watching.
// Equivalent to the sidebar in mca_qt/editor_panel.py.

#include "Widgets/SMCASidebar.h"
#include "MCAEditorStyle.h"

#include "DirectoryWatcherModule.h"
#include "IDirectoryWatcher.h"
#include "HAL/FileManager.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/Images/SImage.h"
#include "Widgets/Text/STextBlock.h"

#define LOCTEXT_NAMESPACE "SMCASidebar"


void SMCASidebar::Construct(const FArguments& InArgs)
{
	OnFileSelectedDelegate = InArgs._OnFileSelected;

	ChildSlot
	[
		SNew(SVerticalBox)

		// --- Header --------------------------------------------------------
		+ SVerticalBox::Slot()
		.AutoHeight()
		.Padding(8.0f, 4.0f)
		[
			SNew(STextBlock)
			.Text(LOCTEXT("SidebarHeader", "Files"))
			.ColorAndOpacity(FMCAEditorStyle::TextColor)
		]

		// --- Tree View -----------------------------------------------------
		+ SVerticalBox::Slot()
		.FillHeight(1.0f)
		[
			SNew(SScrollBox)
			+ SScrollBox::Slot()
			[
				SAssignNew(TreeView, STreeView<TSharedPtr<FMCAFileItem>>)
				.TreeItemsSource(&RootItems)
				.OnGenerateRow(this, &SMCASidebar::OnGenerateRow)
				.OnGetChildren(this, &SMCASidebar::OnGetChildren)
				.OnMouseButtonDoubleClick(this, &SMCASidebar::OnItemDoubleClicked)
				.OnContextMenuOpening(this, &SMCASidebar::OnContextMenuOpening)
			]
		]
	];
}


void SMCASidebar::SetRootDirectory(const FString& DirectoryPath)
{
	// Unwatch the previous directory if any.
	if (!RootPath.IsEmpty() && DirectoryWatcherHandle.IsValid())
	{
		IDirectoryWatcher* DirectoryWatcher = FModuleManager::LoadModuleChecked<FDirectoryWatcherModule>(TEXT("DirectoryWatcher")).Get();
		if (DirectoryWatcher)
		{
			DirectoryWatcher->UnregisterDirectoryChangedCallback_Handle(RootPath, DirectoryWatcherHandle);
		}
	}

	RootPath = DirectoryPath;
	RefreshTree();

	// Watch the new directory for changes.
	IDirectoryWatcher* DirectoryWatcher = FModuleManager::LoadModuleChecked<FDirectoryWatcherModule>(TEXT("DirectoryWatcher")).Get();
	if (DirectoryWatcher)
	{
		DirectoryWatcher->RegisterDirectoryChangedCallback_Handle(
			RootPath,
			IDirectoryWatcher::FDirectoryChanged::CreateSP(this, &SMCASidebar::OnDirectoryChanged),
			DirectoryWatcherHandle
		);
	}
}


void SMCASidebar::RefreshTree()
{
	RootItems.Empty();

	if (!RootPath.IsEmpty())
	{
		ScanDirectory(RootPath, RootItems);
	}

	if (TreeView.IsValid())
	{
		TreeView->RequestTreeRefresh();
	}
}


void SMCASidebar::ScanDirectory(const FString& DirectoryPath, TArray<TSharedPtr<FMCAFileItem>>& OutItems)
{
	// Collect directories first, then files (for sorted display).
	TArray<FString> FoundDirectories;
	TArray<FString> FoundFiles;

	IFileManager& FileManager = IFileManager::Get();

	// Find all items in this directory.
	FileManager.FindFiles(FoundDirectories, *(DirectoryPath / TEXT("*")), false, true);
	FileManager.FindFiles(FoundFiles, *(DirectoryPath / TEXT("*")), true, false);

	// Sort alphabetically.
	FoundDirectories.Sort();
	FoundFiles.Sort();

	// Add directories.
	for (const FString& DirName : FoundDirectories)
	{
		// Skip hidden directories and common junk.
		if (DirName.StartsWith(TEXT(".")) || DirName == TEXT("__pycache__"))
		{
			continue;
		}

		TSharedPtr<FMCAFileItem> Item = MakeShared<FMCAFileItem>();
		Item->DisplayName = DirName;
		Item->FullPath = DirectoryPath / DirName;
		Item->bIsDirectory = true;

		// Recursively scan subdirectories.
		ScanDirectory(Item->FullPath, Item->Children);

		OutItems.Add(Item);
	}

	// Add files.
	for (const FString& FileName : FoundFiles)
	{
		// Skip hidden files.
		if (FileName.StartsWith(TEXT(".")))
		{
			continue;
		}

		TSharedPtr<FMCAFileItem> Item = MakeShared<FMCAFileItem>();
		Item->DisplayName = FileName;
		Item->FullPath = DirectoryPath / FileName;
		Item->bIsDirectory = false;

		OutItems.Add(Item);
	}
}


TSharedRef<ITableRow> SMCASidebar::OnGenerateRow(TSharedPtr<FMCAFileItem> Item, const TSharedRef<STableViewBase>& OwnerTable)
{
	// Build a simple row: icon + filename.
	return SNew(STableRow<TSharedPtr<FMCAFileItem>>, OwnerTable)
		[
			SNew(SHorizontalBox)

			// File/folder icon indicator.
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(2.0f, 0.0f)
			[
				SNew(STextBlock)
				.Text(FText::FromString(Item->bIsDirectory ? TEXT("[D]") : TEXT("   ")))
				.ColorAndOpacity(FMCAEditorStyle::LineNumberColor)
			]

			// File name.
			+ SHorizontalBox::Slot()
			.FillWidth(1.0f)
			.Padding(4.0f, 0.0f)
			[
				SNew(STextBlock)
				.Text(FText::FromString(Item->DisplayName))
				.ColorAndOpacity(FMCAEditorStyle::TextColor)
			]
		];
}


void SMCASidebar::OnGetChildren(TSharedPtr<FMCAFileItem> Item, TArray<TSharedPtr<FMCAFileItem>>& OutChildren)
{
	if (Item.IsValid())
	{
		OutChildren = Item->Children;
	}
}


void SMCASidebar::OnItemDoubleClicked(TSharedPtr<FMCAFileItem> Item)
{
	if (Item.IsValid() && !Item->bIsDirectory)
	{
		OnFileSelectedDelegate.ExecuteIfBound(Item->FullPath);
	}
}


TSharedPtr<SWidget> SMCASidebar::OnContextMenuOpening()
{
	// TODO Phase 3: Build context menu (New File, Rename, Delete, Reveal in Explorer).
	return nullptr;
}


void SMCASidebar::OnDirectoryChanged(const TArray<FFileChangeData>& FileChanges)
{
	// Refresh the tree when the filesystem changes.
	RefreshTree();
}


#undef LOCTEXT_NAMESPACE
