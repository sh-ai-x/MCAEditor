// MCA Editor Panel — Main container widget implementation.
//
// Arranges the toolbar, sidebar, tab bar, code editor, output panel,
// and tool stripe using nested SSplitters. This mirrors the layout
// from mca_qt/editor_panel.py.

#include "Widgets/SMCAEditorPanel.h"
#include "Widgets/SMCACodeEditor.h"
#include "Widgets/SMCAOutputPanel.h"
#include "Widgets/SMCASidebar.h"
#include "Widgets/SMCATabBar.h"
#include "Widgets/SMCAFindReplace.h"
#include "Widgets/SMCAToolStripe.h"
#include "PythonBridge.h"
#include "MCAEditorStyle.h"
#include "MCAEditorSettings.h"

#include "Widgets/SMCAQuickOpen.h"
#include "MCAEditorCommands.h"

#include "DesktopPlatformModule.h"
#include "Misc/FileHelper.h"
#include "Widgets/Layout/SSplitter.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/SOverlay.h"
#include "Framework/Application/SlateApplication.h"

#define LOCTEXT_NAMESPACE "SMCAEditorPanel"


void SMCAEditorPanel::Construct(const FArguments& InArgs)
{
	// Create the Python execution bridge.
	PythonBridge = MakeShared<FPythonBridge>();

	// Wire up Python output to the output panel.
	PythonBridge->OnPythonOutput.AddLambda([this](const FString& Output, const FString& Severity, bool bIsError)
	{
		if (OutputPanel.IsValid())
		{
			OutputPanel->AppendOutput(Output, Severity);
		}
	});

	// Build the full UI layout.
	ChildSlot
	[
		SNew(SVerticalBox)

		// --- Toolbar Row ---------------------------------------------------
		+ SVerticalBox::Slot()
		.AutoHeight()
		[
			BuildToolbar()
		]

		// --- Main Content Area (Sidebar | Editor + Output | ToolStripe) ----
		+ SVerticalBox::Slot()
		.FillHeight(1.0f)
		[
			SNew(SHorizontalBox)

			// Sidebar (file tree).
			+ SHorizontalBox::Slot()
			.AutoWidth()
			[
				SNew(SBox)
				.WidthOverride(250.0f)
				[
					SAssignNew(Sidebar, SMCASidebar)
					.OnFileSelected(FOnSidebarFileSelected::CreateSP(this, &SMCAEditorPanel::OnSidebarFileSelected))
				]
			]

			// Splitter between sidebar and editor area.
			+ SHorizontalBox::Slot()
			.FillWidth(1.0f)
			[
				SNew(SVerticalBox)

				// Tab bar.
				+ SVerticalBox::Slot()
				.AutoHeight()
				[
					SAssignNew(TabBar, SMCATabBar)
					.OnTabSelected(FOnTabSelected::CreateSP(this, &SMCAEditorPanel::OnTabSelected))
					.OnTabCloseRequested(FOnTabCloseRequested::CreateSP(this, &SMCAEditorPanel::OnTabClosed))
				]

				// Vertical splitter: code editor | output panel.
				+ SVerticalBox::Slot()
				.FillHeight(1.0f)
				[
					SNew(SOverlay)

					// Main splitter layer.
					+ SOverlay::Slot()
					[
						SNew(SSplitter)
						.Orientation(Orient_Vertical)

						// Code editor (top, 70%).
						+ SSplitter::Slot()
						.Value(0.7f)
						[
							SAssignNew(CodeEditor, SMCACodeEditor)
							.OnExecuteRequested(FSimpleDelegate::CreateSP(this, &SMCAEditorPanel::OnExecuteClicked))
							.OnCursorMoved(FOnCursorPositionChanged::CreateSP(this, &SMCAEditorPanel::OnCursorPositionChanged))
						]

						// Output panel (bottom, 30%).
						+ SSplitter::Slot()
						.Value(0.3f)
						[
							SAssignNew(OutputPanel, SMCAOutputPanel)
						]
					]

					// Find/replace overlay layer.
					+ SOverlay::Slot()
					.HAlign(HAlign_Right)
					.VAlign(VAlign_Top)
					.Padding(10.0f)
					[
						SAssignNew(FindReplaceBar, SMCAFindReplace)
						.CodeEditor(CodeEditor)
					]

					// Quick-open overlay (centered).
					+ SOverlay::Slot()
					.HAlign(HAlign_Center)
					.VAlign(VAlign_Top)
					.Padding(0.0f, 40.0f, 0.0f, 0.0f)
					[
						SAssignNew(QuickOpenPanel, SMCAQuickOpen)
						.RootDirectory(FPaths::ProjectDir())
						.OnFileSelected(FOnQuickOpenFileSelected::CreateSP(this, &SMCAEditorPanel::OnSidebarFileSelected))
					]
				]
			]

			// Tool stripe (right edge).
			+ SHorizontalBox::Slot()
			.AutoWidth()
			[
				SAssignNew(ToolStripe, SMCAToolStripe)
			]
		]

		// --- Status Bar ----------------------------------------------------
		+ SVerticalBox::Slot()
		.AutoHeight()
		[
			BuildStatusBar()
		]
	];

	// Add default tool stripe buttons.
	ToolStripe->AddButton(FName("Terminal"), TEXT("Term"), TEXT("Toggle Terminal"));
	ToolStripe->AddButton(FName("AIChat"), TEXT("AI"), TEXT("Toggle AI Chat"));

	// Create an initial empty tab.
	FMCATabInfo NewTab;
	NewTab.DisplayName = TEXT("untitled.py");
	NewTab.bIsModified = false;
	NewTab.CursorLine = 1;
	NewTab.CursorColumn = 1;
	TabBar->AddTab(NewTab);

	// Bind keyboard shortcuts to panel actions.
	BindCommands();
}


TSharedRef<SWidget> SMCAEditorPanel::BuildToolbar()
{
	return SNew(SHorizontalBox)

		// Execute button.
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.Padding(4.0f, 2.0f)
		[
			SNew(SButton)
			.Text(LOCTEXT("ExecuteButton", "Execute"))
			.ToolTipText(LOCTEXT("ExecuteTooltip", "Execute the current script (Shift+Enter)"))
			.OnClicked(this, &SMCAEditorPanel::OnExecuteClicked)
		]

		// Save button.
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.Padding(4.0f, 2.0f)
		[
			SNew(SButton)
			.Text(LOCTEXT("SaveButton", "Save"))
			.ToolTipText(LOCTEXT("SaveTooltip", "Save the current file (Ctrl+S)"))
			.OnClicked(this, &SMCAEditorPanel::OnSaveClicked)
		]

		// Open button.
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.Padding(4.0f, 2.0f)
		[
			SNew(SButton)
			.Text(LOCTEXT("OpenButton", "Open"))
			.ToolTipText(LOCTEXT("OpenTooltip", "Open a file (Ctrl+O)"))
			.OnClicked(this, &SMCAEditorPanel::OnOpenClicked)
		]

		// New file button.
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.Padding(4.0f, 2.0f)
		[
			SNew(SButton)
			.Text(LOCTEXT("NewFileButton", "New"))
			.ToolTipText(LOCTEXT("NewFileTooltip", "Create a new file (Ctrl+N)"))
			.OnClicked(this, &SMCAEditorPanel::OnNewFileClicked)
		]

		// Spacer pushes connection status to the right.
		+ SHorizontalBox::Slot()
		.FillWidth(1.0f)
		[
			SNullWidget::NullWidget
		]

		// Connection status indicator.
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.Padding(4.0f, 2.0f)
		[
			SAssignNew(ConnectionStatusText, STextBlock)
			.Text(LOCTEXT("Connected", "Python: In-Process"))
			.ColorAndOpacity(FMCAEditorStyle::ResultColor)
		];
}


TSharedRef<SWidget> SMCAEditorPanel::BuildStatusBar()
{
	return SNew(SHorizontalBox)

		// Cursor position.
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.Padding(8.0f, 2.0f)
		[
			SAssignNew(StatusBarText, STextBlock)
			.Text(LOCTEXT("DefaultStatus", "Ln 1, Col 1"))
			.ColorAndOpacity(FMCAEditorStyle::TextColor)
		]

		// Spacer.
		+ SHorizontalBox::Slot()
		.FillWidth(1.0f)
		[
			SNullWidget::NullWidget
		]

		// Language indicator.
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.Padding(8.0f, 2.0f)
		[
			SNew(STextBlock)
			.Text(LOCTEXT("Language", "Python"))
			.ColorAndOpacity(FMCAEditorStyle::TextColor)
		]

		// Encoding indicator.
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.Padding(8.0f, 2.0f)
		[
			SNew(STextBlock)
			.Text(LOCTEXT("Encoding", "UTF-8"))
			.ColorAndOpacity(FMCAEditorStyle::TextColor)
		];
}


FReply SMCAEditorPanel::OnExecuteClicked()
{
	if (!CodeEditor.IsValid() || !PythonBridge.IsValid())
	{
		return FReply::Handled();
	}

	// Get the text to execute (selection or all).
	FString Code = CodeEditor->GetExecutionText();
	if (Code.IsEmpty())
	{
		return FReply::Handled();
	}

	// Auto-save before execution if configured.
	const UMCAEditorSettings* Settings = UMCAEditorSettings::GetSettings();
	if (Settings && Settings->bAutoSaveOnExecute)
	{
		SaveCurrentFile();
	}

	// Execute the code and display output.
	OutputPanel->AppendOutput(TEXT(">>> Executing..."), TEXT("Info"));
	FString Result;
	bool bSuccess = PythonBridge->ExecuteCode(Code, Result);

	if (!bSuccess && !Result.IsEmpty())
	{
		OutputPanel->AppendOutput(Result, TEXT("Error"));
	}

	return FReply::Handled();
}


FReply SMCAEditorPanel::OnSaveClicked()
{
	SaveCurrentFile();
	return FReply::Handled();
}


FReply SMCAEditorPanel::OnOpenClicked()
{
	// Show a native file open dialog.
	IDesktopPlatform* DesktopPlatform = FDesktopPlatformModule::Get();
	if (!DesktopPlatform)
	{
		return FReply::Handled();
	}

	TArray<FString> OutFiles;
	bool bOpened = DesktopPlatform->OpenFileDialog(
		FSlateApplication::Get().FindBestParentWindowHandleForDialogs(nullptr),
		TEXT("Open Python File"),
		FPaths::ProjectDir(),
		TEXT(""),
		TEXT("Python Files (*.py)|*.py|All Files (*.*)|*.*"),
		EFileDialogFlags::None,
		OutFiles
	);

	if (bOpened && OutFiles.Num() > 0)
	{
		OpenFile(OutFiles[0]);
	}

	return FReply::Handled();
}


FReply SMCAEditorPanel::OnNewFileClicked()
{
	// Create a new untitled tab.
	FMCATabInfo NewTab;
	NewTab.DisplayName = TEXT("untitled.py");
	NewTab.bIsModified = false;
	NewTab.CursorLine = 1;
	NewTab.CursorColumn = 1;

	int32 TabIndex = TabBar->AddTab(NewTab);
	TabBar->SetActiveTab(TabIndex);

	// Clear the editor for the new tab.
	if (CodeEditor.IsValid())
	{
		CodeEditor->SetText(FText::GetEmpty());
		CodeEditor->ClearModified();
	}

	return FReply::Handled();
}


void SMCAEditorPanel::OpenFile(const FString& FilePath)
{
	// Check if the file is already open in a tab.
	int32 ExistingTab = TabBar->FindTabByPath(FilePath);
	if (ExistingTab >= 0)
	{
		TabBar->SetActiveTab(ExistingTab);
		return;
	}

	// Read the file content.
	FString FileContent;
	if (!FFileHelper::LoadFileToString(FileContent, *FilePath))
	{
		OutputPanel->AppendOutput(FString::Printf(TEXT("Error: Could not read file: %s"), *FilePath), TEXT("Error"));
		return;
	}

	// Create a new tab for this file.
	FMCATabInfo NewTab;
	NewTab.DisplayName = FPaths::GetCleanFilename(FilePath);
	NewTab.FilePath = FilePath;
	NewTab.bIsModified = false;
	NewTab.Content = FText::FromString(FileContent);
	NewTab.CursorLine = 1;
	NewTab.CursorColumn = 1;

	int32 TabIndex = TabBar->AddTab(NewTab);
	TabBar->SetActiveTab(TabIndex);

	// Load the content into the editor.
	if (CodeEditor.IsValid())
	{
		CodeEditor->SetText(FText::FromString(FileContent));
		CodeEditor->ClearModified();
	}
}


void SMCAEditorPanel::SaveCurrentFile()
{
	if (!CodeEditor.IsValid() || !TabBar.IsValid())
	{
		return;
	}

	int32 ActiveTab = TabBar->GetActiveTab();
	if (ActiveTab < 0)
	{
		return;
	}

	const FMCATabInfo* TabInfo = TabBar->GetTabInfo(ActiveTab);
	if (!TabInfo)
	{
		return;
	}

	FString FilePath = TabInfo->FilePath;

	// If no file path, prompt for save location.
	if (FilePath.IsEmpty())
	{
		IDesktopPlatform* DesktopPlatform = FDesktopPlatformModule::Get();
		if (!DesktopPlatform)
		{
			return;
		}

		TArray<FString> OutFiles;
		bool bSaved = DesktopPlatform->SaveFileDialog(
			FSlateApplication::Get().FindBestParentWindowHandleForDialogs(nullptr),
			TEXT("Save Python File"),
			FPaths::ProjectDir(),
			TEXT("untitled.py"),
			TEXT("Python Files (*.py)|*.py|All Files (*.*)|*.*"),
			EFileDialogFlags::None,
			OutFiles
		);

		if (!bSaved || OutFiles.Num() == 0)
		{
			return;
		}

		FilePath = OutFiles[0];
	}

	// Write the file.
	FString Content = CodeEditor->GetText().ToString();
	if (FFileHelper::SaveStringToFile(Content, *FilePath))
	{
		CodeEditor->ClearModified();
		TabBar->SetTabModified(ActiveTab, false);
		OutputPanel->AppendOutput(FString::Printf(TEXT("Saved: %s"), *FilePath), TEXT("Info"));
	}
	else
	{
		OutputPanel->AppendOutput(FString::Printf(TEXT("Error: Could not save file: %s"), *FilePath), TEXT("Error"));
	}
}


void SMCAEditorPanel::OnSidebarFileSelected(const FString& FilePath)
{
	OpenFile(FilePath);
}


void SMCAEditorPanel::OnTabSelected(int32 TabIndex)
{
	const FMCATabInfo* TabInfo = TabBar->GetTabInfo(TabIndex);
	if (TabInfo && CodeEditor.IsValid())
	{
		// Save current tab's content before switching.
		int32 PrevTab = TabBar->GetActiveTab();
		if (PrevTab >= 0 && PrevTab != TabIndex)
		{
			TabBar->SetTabContent(
				PrevTab,
				CodeEditor->GetText(),
				CodeEditor->GetCursorLine(),
				CodeEditor->GetCursorColumn()
			);
		}

		// Load the new tab's content.
		CodeEditor->SetText(TabInfo->Content);
		CodeEditor->GoToLine(TabInfo->CursorLine);
	}
}


void SMCAEditorPanel::OnTabClosed(int32 TabIndex)
{
	// TODO: Prompt to save if modified.
	TabBar->RemoveTab(TabIndex);

	// If no tabs remain, create a new empty one.
	if (TabBar->GetTabCount() == 0)
	{
		OnNewFileClicked();
	}
}


void SMCAEditorPanel::OnCursorPositionChanged(int32 Line, int32 Column)
{
	if (StatusBarText.IsValid())
	{
		FString StatusText = FString::Printf(TEXT("Ln %d, Col %d"), Line, Column);
		StatusBarText->SetText(FText::FromString(StatusText));
	}
}


void SMCAEditorPanel::UpdateStatusBar()
{
	if (StatusBarText.IsValid() && CodeEditor.IsValid())
	{
		FString StatusText = FString::Printf(
			TEXT("Ln %d, Col %d"),
			CodeEditor->GetCursorLine(),
			CodeEditor->GetCursorColumn()
		);
		StatusBarText->SetText(FText::FromString(StatusText));
	}
}


// --- Command Binding -------------------------------------------------------

void SMCAEditorPanel::BindCommands()
{
	CommandList = MakeShared<FUICommandList>();

	const FMCAEditorCommands& Commands = FMCAEditorCommands::Get();

	// Shift+Enter — Execute code.
	CommandList->MapAction(Commands.ExecuteCode,
		FExecuteAction::CreateLambda([this]() { OnExecuteClicked(); }),
		FCanExecuteAction());

	// Ctrl+S — Save file.
	CommandList->MapAction(Commands.SaveFile,
		FExecuteAction::CreateLambda([this]() { OnSaveClicked(); }),
		FCanExecuteAction());

	// Ctrl+O — Open file.
	CommandList->MapAction(Commands.OpenFile,
		FExecuteAction::CreateLambda([this]() { OnOpenClicked(); }),
		FCanExecuteAction());

	// Ctrl+N — New file.
	CommandList->MapAction(Commands.NewFile,
		FExecuteAction::CreateLambda([this]() { OnNewFileClicked(); }),
		FCanExecuteAction());

	// Ctrl+F — Toggle find bar.
	CommandList->MapAction(Commands.FindReplace,
		FExecuteAction::CreateSP(this, &SMCAEditorPanel::OnToggleFind),
		FCanExecuteAction());

	// Ctrl+P — Quick open.
	CommandList->MapAction(Commands.QuickOpen,
		FExecuteAction::CreateSP(this, &SMCAEditorPanel::OnQuickOpen),
		FCanExecuteAction());

	// Ctrl+G — Go to line.
	CommandList->MapAction(Commands.GoToLine,
		FExecuteAction::CreateSP(this, &SMCAEditorPanel::OnGoToLine),
		FCanExecuteAction());

	// Ctrl+/ — Toggle comment.
	CommandList->MapAction(Commands.ToggleComment,
		FExecuteAction::CreateSP(this, &SMCAEditorPanel::OnToggleComment),
		FCanExecuteAction());
}


FReply SMCAEditorPanel::OnKeyDown(const FGeometry& MyGeometry, const FKeyEvent& InKeyEvent)
{
	// Let the command list try to process the shortcut first.
	if (CommandList.IsValid() && CommandList->ProcessCommandBindings(InKeyEvent))
	{
		return FReply::Handled();
	}

	// Tab / Shift+Tab — Indent / Dedent.
	if (InKeyEvent.GetKey() == EKeys::Tab && CodeEditor.IsValid())
	{
		if (InKeyEvent.IsShiftDown())
		{
			CodeEditor->DedentSelection();
		}
		else
		{
			CodeEditor->IndentSelection();
		}
		return FReply::Handled();
	}

	// Escape — Close find bar if open.
	if (InKeyEvent.GetKey() == EKeys::Escape && FindReplaceBar.IsValid() && FindReplaceBar->IsBarVisible())
	{
		FindReplaceBar->Hide();
		return FReply::Handled();
	}

	return SCompoundWidget::OnKeyDown(MyGeometry, InKeyEvent);
}


// --- Shortcut Actions ------------------------------------------------------

void SMCAEditorPanel::OnToggleFind()
{
	if (FindReplaceBar.IsValid())
	{
		if (FindReplaceBar->IsBarVisible())
		{
			FindReplaceBar->Hide();
		}
		else
		{
			FindReplaceBar->ShowFind();
		}
	}
}


void SMCAEditorPanel::OnToggleFindReplace()
{
	if (FindReplaceBar.IsValid())
	{
		if (FindReplaceBar->IsBarVisible())
		{
			FindReplaceBar->Hide();
		}
		else
		{
			FindReplaceBar->ShowFindReplace();
		}
	}
}


void SMCAEditorPanel::OnQuickOpen()
{
	if (QuickOpenPanel.IsValid())
	{
		QuickOpenPanel->Show();
	}
}


void SMCAEditorPanel::OnGoToLine()
{
	if (!CodeEditor.IsValid())
	{
		return;
	}

	// Create a simple inline input dialog for the line number.
	// Uses a modal popup window with a single text field.
	TSharedRef<SWindow> GoToWindow = SNew(SWindow)
		.Title(LOCTEXT("GoToLineTitle", "Go To Line"))
		.SizingRule(ESizingRule::Autosized)
		.SupportsMaximize(false)
		.SupportsMinimize(false)
		.HasCloseButton(true);

	TSharedPtr<SEditableTextBox> LineInput;

	GoToWindow->SetContent(
		SNew(SBox)
		.Padding(16.0f)
		.WidthOverride(250.0f)
		[
			SNew(SVerticalBox)

			+ SVerticalBox::Slot()
			.AutoHeight()
			.Padding(0.0f, 0.0f, 0.0f, 8.0f)
			[
				SNew(STextBlock)
				.Text(LOCTEXT("GoToLineLabel", "Line Number:"))
			]

			+ SVerticalBox::Slot()
			.AutoHeight()
			[
				SAssignNew(LineInput, SEditableTextBox)
				.HintText(LOCTEXT("GoToLineHint", "Enter line number..."))
				.OnTextCommitted_Lambda([this, &GoToWindow](const FText& Text, ETextCommit::Type CommitType)
				{
					if (CommitType == ETextCommit::OnEnter)
					{
						int32 LineNumber = FCString::Atoi(*Text.ToString());
						if (LineNumber > 0 && CodeEditor.IsValid())
						{
							CodeEditor->GoToLine(LineNumber);
						}
						GoToWindow->RequestDestroyWindow();
					}
				})
			]
		]
	);

	FSlateApplication::Get().AddModalWindow(GoToWindow, SharedThis(this));
}


void SMCAEditorPanel::OnToggleComment()
{
	if (CodeEditor.IsValid())
	{
		CodeEditor->ToggleComment();
	}
}


#undef LOCTEXT_NAMESPACE
