# Claude Code Task: License Check on Plugin Load + Licensing Dialog

## Overview

Wire the license activation system into the plugin startup sequence.
Every time MCA Editor loads in Maya, it validates the license before
opening the editor. Users in trial get a non-blocking banner. Users
with expired trials or invalid keys see a licensing dialog and the
editor does not open until they activate.

---

## Read These Files First (Do Not Skip)

Before writing any code, read these files in full:
- `mca_maya/plugin_main.py`
- `mca_maya/maya_window.py`
- `mca_qt/editor_panel.py`
- `mca_core/activation.py`
- `mca_core/config/settings.py`
- `mca_core/platform_utils.py`
- `mca_qt/widgets/` — scan all files to understand existing widget patterns

---

## Scope

Do:
- Wire license check into `plugin_main.py`
- Create `mca_qt/widgets/licensing_dialog.py`
- Add trial banner to the editor status bar
- Add **Help > Licensing** menu item

Do NOT:
- Modify any editor layout, tab, or output panel code
- Change any existing widget behavior
- Touch the activation server code
- Make any network calls directly — all network logic is in `activation.py`

---

## Part 1: License Check in `plugin_main.py`

### Logic

```
initializePlugin():
    if is_batch_mode():
        register commands only, return early

    ... existing init code (register plugin, commands, etc.) ...

    # Defer license check so Maya UI is fully ready
    maya.utils.executeDeferred(_run_license_check)


def _run_license_check():
    result = validate_on_launch(VERSION, product="maya")

    if result.success:
        # Licensed or within offline grace period
        _open_editor_window()
        if result.status == "offline":
            # Subtle warning — don't block, just inform
            _show_status_warning(result.message)
        return

    # Not licensed — check trial
    trial = get_trial_status()

    if trial["active"]:
        # Trial still running — open editor with banner
        _open_editor_window()
        _show_trial_banner(trial["days_remaining"])
        return

    # Trial expired and no valid license — show dialog, block editor
    _show_licensing_dialog(reason=result.status, message=result.message)
```

### Implementation details

- `_open_editor_window()` — calls whatever function currently opens the
  MCA Editor workspace control. Find this in the existing `plugin_main.py`
  and `maya_window.py` — do not recreate it, just call it.

- `_show_status_warning(message)` — writes a single line to Maya's status
  line using `maya.cmds.inViewMessage` or equivalent. Non-blocking.

- `_show_trial_banner(days_remaining)` — sets a message on the editor's
  status bar (see Part 3). Only show if days_remaining <= 7.

- `_show_licensing_dialog(reason, message)` — creates and shows the
  LicensingDialog (see Part 2). Does NOT open the editor.

### Imports to add to `plugin_main.py`

```python
from mca_core.platform_utils import is_batch_mode
from mca_core.activation import validate_on_launch, get_trial_status
from mca_core import VERSION
```

---

## Part 2: `mca_qt/widgets/licensing_dialog.py`

A QDialog with three tabs. Modal when shown at startup (trial expired),
non-modal when opened from Help > Licensing.

### Tab 1 — Activate

Shown first when the dialog opens.

**Layout:**
```
┌─────────────────────────────────────────────┐
│  MCA Editor                    [mca.png]    │
│  ─────────────────────────────────────────  │
│  Enter your license key to activate.        │
│                                             │
│  License Key: [MCA-XXXX-XXXX-XXXX-XXXX   ] │
│                                             │
│  [        Activate        ]                 │
│                                             │
│  Status: (shown after activate attempt)     │
│                                             │
│  Don't have a license?                      │
│  [Buy Now — mcaeditor.com/pricing]          │
└─────────────────────────────────────────────┘
```

**Behavior:**
- Key field: plain QLineEdit, auto-uppercases input, accepts
  MCA-XXXX-XXXX-XXXX-XXXX format
- Activate button: calls `activation.activate(key, VERSION, product="maya")`
  - On success: close dialog, open editor, show success notification
  - On `limit_reached`: show message + switch to Manage tab
  - On `invalid_key`: show "Key not found or already revoked" in red
  - On `offline`: show "Could not reach server. Check your connection." in orange
- Buy Now: opens `https://mcaeditor.com/pricing` in default browser
  using `QDesktopServices.openUrl()`
- While activating: disable button, show "Activating..." text

---

### Tab 2 — Trial Status

Only show this tab if the trial is still active. Hide it if trial expired.

**Layout:**
```
┌─────────────────────────────────────────────┐
│  Free Trial                                 │
│  ─────────────────────────────────────────  │
│  You have X days remaining in your          │
│  14-day free trial.                         │
│                                             │
│  MCA Editor is fully functional during      │
│  the trial. No features are restricted.     │
│                                             │
│  [  Buy Now — $99 Perpetual  ]              │
│  [  Buy Annual — $49/year    ]              │
└─────────────────────────────────────────────┘
```

**Behavior:**
- Days remaining shown as: "X days remaining" (green if >3, yellow if ≤3)
- Both buy buttons open `https://mcaeditor.com/pricing`

---

### Tab 3 — Manage Activations

Shows current machine activations for this license key.

**Layout:**
```
┌─────────────────────────────────────────────┐
│  Manage Activations             [Refresh]   │
│  ─────────────────────────────────────────  │
│  License: MCA-XXXX-XXXX-XXXX-XXXX          │
│  Activations: 2 of 3 machines              │
│                                             │
│  ┌──────────┬──────────┬────────┬────────┐  │
│  │ Platform │ Hostname │ Added  │        │  │
│  ├──────────┼──────────┼────────┼────────┤  │
│  │ Windows  │ DESKTOP  │Mar 13  │(this)  │  │
│  │ macOS    │ Nathan's │Mar 10  │Deact.  │  │
│  └──────────┴──────────┴────────┴────────┘  │
│                                             │
│  [  Deactivate This Machine  ]              │
└─────────────────────────────────────────────┘
```

**Behavior:**
- Populate by calling `activation.get_activations(product="maya")`
- Current machine shown with "(this machine)" label, no deactivate button
  in the row
- Other machines show a "Deactivate" button in the row
- "Deactivate This Machine" button at bottom calls
  `activation.deactivate(product="maya")`, clears cache, closes dialog
- Refresh button reloads the list
- If `get_activations()` returns None (offline): show
  "Could not load activation list. Check your connection."

---

### Dialog class structure

```python
class LicensingDialog(QDialog):

    def __init__(self, parent=None, modal=True, reason="", message=""):
        """
        reason: why the dialog is being shown
                ("not_activated", "expired", "limit_reached", or "" for manual open)
        modal: True when blocking editor open, False when opened from menu
        """

    @classmethod
    def show_if_needed(cls, result, trial):
        """
        Called from plugin_main after license check.
        Creates and shows the dialog with appropriate initial tab.
        """

    @classmethod
    def open_from_menu(cls, parent=None):
        """
        Called from Help > Licensing menu item.
        Non-modal, starts on Activate tab if no key stored,
        Manage tab if key is already activated.
        """

    def _on_activate_clicked(self):
        """Runs activation, handles all result states."""

    def _on_success(self, entitlements):
        """Called after successful activation. Closes dialog, opens editor."""
```

### Initial tab selection

| Reason | Starting tab |
|---|---|
| `"not_activated"` + trial active | Trial Status |
| `"not_activated"` + trial expired | Activate |
| `"expired"` | Activate |
| `"limit_reached"` | Manage Activations |
| `""` (menu open) + key cached | Manage Activations |
| `""` (menu open) + no key cached | Activate |

---

### Qt import pattern

Follow the existing pattern in the codebase — import from
`mca_qt.qt_compat` rather than directly from PySide6:

```python
from mca_qt.qt_compat import (
    QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QSizePolicy, QDesktopServices, QUrl, Qt,
    QPixmap, QIcon
)
```

---

## Part 3: Trial Banner in Status Bar

### Where it goes

Find the status bar in `mca_qt/editor_panel.py`. There should be an
existing status bar or status label at the bottom of the editor panel.
Add a trial warning label to the right side of that status bar.

### Behavior

```python
def show_trial_banner(self, days_remaining: int):
    """
    Show a trial countdown in the status bar.
    Only called when days_remaining <= 7.
    """
    if days_remaining <= 3:
        color = "#FFA500"   # Orange — urgent
        text = f"Trial: {days_remaining} days remaining — "
    else:
        color = "#888888"   # Subtle gray
        text = f"Trial: {days_remaining} days remaining — "

    self._trial_label.setText(text)
    self._trial_label.setStyleSheet(f"color: {color};")
    self._trial_label.setVisible(True)

    # Clickable "Buy Now" link next to the label
    self._trial_buy_link.setVisible(True)
```

- `_trial_label` — QLabel, hidden by default
- `_trial_buy_link` — QLabel with link style, clicking opens pricing page
- Both hidden at startup, shown only when `show_trial_banner()` is called
- Never show the banner if the user has a valid license

---

## Part 4: Help > Licensing Menu Item

In `mca_qt/editor_panel.py`, find where the Help menu is built.
Add a **Licensing** item:

```python
licensing_action = help_menu.addAction("Licensing")
licensing_action.triggered.connect(self._open_licensing_dialog)

def _open_licensing_dialog(self):
    from mca_qt.widgets.licensing_dialog import LicensingDialog
    LicensingDialog.open_from_menu(parent=self)
```

---

## Part 5: Post-Activation Editor Open

When the user successfully activates from the dialog, the editor should
open without requiring a Maya restart.

In `LicensingDialog._on_success()`:

```python
def _on_success(self, entitlements):
    self.accept()  # Close dialog
    # Open the editor window — call the same function plugin_main uses
    from mca_maya.plugin_main import _open_editor_window
    _open_editor_window()
```

Make sure `_open_editor_window()` in `plugin_main.py` is a standalone
callable function (not inlined) so it can be called from both the
startup sequence and the dialog.

---

## Error Handling Notes

- All `activation.*` calls can fail with network errors — always wrap
  in try/except inside the dialog and show a user-friendly message
- Never let an exception in the license check crash Maya
- If `activation.py` is not yet compiled/available (development mode),
  catch `ImportError` and skip the license check entirely:

```python
try:
    from mca_core.activation import validate_on_launch, get_trial_status
    HAS_ACTIVATION = True
except ImportError:
    HAS_ACTIVATION = False

def _run_license_check():
    if not HAS_ACTIVATION:
        # Dev mode — no activation module, open freely
        _open_editor_window()
        return
    # ... normal check ...
```

---

## Testing Checklist

After implementation, verify these scenarios manually:

| Scenario | Expected result |
|---|---|
| First launch, no cache | Trial starts, editor opens with banner after day 7 |
| Valid cached token (fresh) | Editor opens instantly, no network call |
| Valid cached token (near expiry) | Editor opens, token refreshes in background |
| Offline, within grace period | Editor opens, status bar shows offline warning |
| Offline, grace period expired | Dialog shown, editor blocked |
| Trial expired, no key | Dialog shown on Activate tab, editor blocked |
| Enter valid key | Editor opens, dialog closes |
| Enter invalid key | Red error message, dialog stays open |
| Limit reached | Dialog switches to Manage tab |
| Deactivate this machine | Cache cleared, dialog closes, editor closes |
| Help > Licensing | Dialog opens non-modal on correct tab |
| Batch mode (Maya headless) | License check skipped entirely |

---

## Files to Create or Modify

| Action | File | Notes |
|---|---|---|
| MODIFY | `mca_maya/plugin_main.py` | Add license check, `_open_editor_window()` fn |
| CREATE | `mca_qt/widgets/licensing_dialog.py` | Full dialog with 3 tabs |
| MODIFY | `mca_qt/editor_panel.py` | Trial banner in status bar, Help > Licensing |

Show a complete diff summary of every change before finishing.
Do not modify any other files.
