// MCA Sidebar — File tree browser implementation.
//
// STreeView-based directory browser with filesystem watching.
// Equivalent to the sidebar in mca_qt/editor_panel.py.

#include "Widgets/SMCASidebar.h"
#include "MCAEditorStyle.h"

#include "DirectoryWatcherModule.h"
#include "IDirectoryWatcher.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformProcess.h"
#include "Misc/FileHelper.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/Images/SImage.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Text/STextBlock.h"
#include "Framework/MultiBox/MultiBoxBuilder.h"
#include "Framework/Application/SlateApplication.h"
#include "DesktopPlatformModule.h"
#include "HAL/PlatformApplicationMisc.h"

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
	// Get the currently selected item from the tree view.
	TArray<TSharedPtr<FMCAFileItem>> SelectedItems = TreeView->GetSelectedItems();
	TSharedPtr<FMCAFileItem> SelectedItem = SelectedItems.Num() > 0 ? SelectedItems[0] : nullptr;

	FMenuBuilder MenuBuilder(true, nullptr);

	// --- New File (always available) ---
	MenuBuilder.AddMenuEntry(
		LOCTEXT("NewFile", "New File"),
		LOCTEXT("NewFileTooltip", "Create a new file in this directory"),
		FSlateIcon(),
		FUIAction(FExecuteAction::CreateSP(this, &SMCASidebar::OnContextMenuNewFile, SelectedItem))
	);

	// --- New Folder (always available) ---
	MenuBuilder.AddMenuEntry(
		LOCTEXT("NewFolder", "New Folder"),
		LOCTEXT("NewFolderTooltip", "Create a new folder in this directory"),
		FSlateIcon(),
		FUIAction(FExecuteAction::CreateSP(this, &SMCASidebar::OnContextMenuNewFolder, SelectedItem))
	);

	if (SelectedItem.IsValid())
	{
		MenuBuilder.AddMenuSeparator();

		// --- Rename ---
		MenuBuilder.AddMenuEntry(
			LOCTEXT("Rename", "Rename"),
			LOCTEXT("RenameTooltip", "Rename this file or folder"),
			FSlateIcon(),
			FUIAction(FExecuteAction::CreateSP(this, &SMCASidebar::OnContextMenuRename, SelectedItem))
		);

		// --- Delete ---
		MenuBuilder.AddMenuEntry(
			LOCTEXT("Delete", "Delete"),
			LOCTEXT("DeleteTooltip", "Delete this file or folder"),
			FSlateIcon(),
			FUIAction(FExecuteAction::CreateSP(this, &SMCASidebar::OnContextMenuDelete, SelectedItem))
		);

		MenuBuilder.AddMenuSeparator();

		// --- Reveal in Explorer ---
		MenuBuilder.AddMenuEntry(
			LOCTEXT("RevealInExplorer", "Reveal in Explorer"),
			LOCTEXT("RevealInExplorerTooltip", "Open the containing folder in the file browser"),
			FSlateIcon(),
			FUIAction(FExecuteAction::CreateSP(this, &SMCASidebar::OnContextMenuRevealInExplorer, SelectedItem))
		);

		// --- Copy Path ---
		MenuBuilder.AddMenuEntry(
			LOCTEXT("CopyPath", "Copy Path"),
			LOCTEXT("CopyPathTooltip", "Copy the full path to the clipboard"),
			FSlateIcon(),
			FUIAction(FExecuteAction::CreateSP(this, &SMCASidebar::OnContextMenuCopyPath, SelectedItem))
		);
	}

	return MenuBuilder.MakeWidget();
}


void SMCASidebar::OnContextMenuNewFile(TSharedPtr<FMCAFileItem> ContextItem)
{
	// Determine the target directory.
	FString TargetDir = RootPath;
	if (ContextItem.IsValid())
	{
		TargetDir = ContextItem->bIsDirectory ? ContextItem->FullPath : FPaths::GetPath(ContextItem->FullPath);
	}

	// Create a new untitled file.
	FString NewFilePath = TargetDir / TEXT("untitled.py");
	int32 Counter = 1;
	while (IFileManager::Get().FileExists(*NewFilePath))
	{
		NewFilePath = TargetDir / FString::Printf(TEXT("untitled_%d.py"), Counter++);
	}

	FFileHelper::SaveStringToFile(TEXT(""), *NewFilePath);
	RefreshTree();

	// Open the new file.
	OnFileSelectedDelegate.ExecuteIfBound(NewFilePath);
}


void SMCASidebar::OnContextMenuNewFolder(TSharedPtr<FMCAFileItem> ContextItem)
{
	FString TargetDir = RootPath;
	if (ContextItem.IsValid())
	{
		TargetDir = ContextItem->bIsDirectory ? ContextItem->FullPath : FPaths::GetPath(ContextItem->FullPath);
	}

	FString NewFolderPath = TargetDir / TEXT("new_folder");
	int32 Counter = 1;
	while (IFileManager::Get().DirectoryExists(*NewFolderPath))
	{
		NewFolderPath = TargetDir / FString::Printf(TEXT("new_folder_%d"), Counter++);
	}

	IFileManager::Get().MakeDirectory(*NewFolderPath, true);
	RefreshTree();
}


void SMCASidebar::OnContextMenuRename(TSharedPtr<FMCAFileItem> ContextItem)
{
	if (!ContextItem.IsValid())
	{
		return;
	}

	// Open a small modal dialog for the new name.
	TSharedRef<SWindow> RenameWindow = SNew(SWindow)
		.Title(LOCTEXT("RenameTitle", "Rename"))
		.SizingRule(ESizingRule::Autosized)
		.SupportsMaximize(false)
		.SupportsMinimize(false);

	TSharedPtr<SEditableTextBox> NameInput;

	RenameWindow->SetContent(
		SNew(SBox)
		.Padding(16.0f)
		.WidthOverride(300.0f)
		[
			SAssignNew(NameInput, SEditableTextBox)
			.Text(FText::FromString(ContextItem->DisplayName))
			.OnTextCommitted_Lambda([this, ContextItem, &RenameWindow](const FText& Text, ETextCommit::Type CommitType)
			{
				if (CommitType == ETextCommit::OnEnter)
				{
					FString NewName = Text.ToString();
					if (!NewName.IsEmpty() && NewName != ContextItem->DisplayName)
					{
						FString ParentDir = FPaths::GetPath(ContextItem->FullPath);
						FString NewPath = ParentDir / NewName;
						IFileManager::Get().Move(*NewPath, *ContextItem->FullPath);
						RefreshTree();
					}
					RenameWindow->RequestDestroyWindow();
				}
			})
		]
	);

	FSlateApplication::Get().AddModalWindow(RenameWindow, AsShared());
}


void SMCASidebar::OnContextMenuDelete(TSharedPtr<FMCAFileItem> ContextItem)
{
	if (!ContextItem.IsValid())
	{
		return;
	}

	// Delete the file or directory.
	if (ContextItem->bIsDirectory)
	{
		IFileManager::Get().DeleteDirectory(*ContextItem->FullPath, false, true);
	}
	else
	{
		IFileManager::Get().Delete(*ContextItem->FullPath);
	}

	RefreshTree();
}


void SMCASidebar::OnContextMenuRevealInExplorer(TSharedPtr<FMCAFileItem> ContextItem)
{
	if (!ContextItem.IsValid())
	{
		return;
	}

	FPlatformProcess::ExploreFolder(*ContextItem->FullPath);
}


void SMCASidebar::OnContextMenuCopyPath(TSharedPtr<FMCAFileItem> ContextItem)
{
	if (!ContextItem.IsValid())
	{
		return;
	}

	FPlatformApplicationMisc::ClipboardCopy(*ContextItem->FullPath);
}


void SMCASidebar::OnDirectoryChanged(const TArray<FFileChangeData>& FileChanges)
{
	// Refresh the tree when the filesystem changes.
	RefreshTree();
}


#undef LOCTEXT_NAMESPACE
