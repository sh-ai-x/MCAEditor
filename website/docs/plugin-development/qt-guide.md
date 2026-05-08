# Using Qt in Plugins

MCA Editor runs on PySide6 (Qt6) inside Maya 2025+. Plugins can build full Qt UIs
using the `mca_qt.qt_compat` compatibility layer, which abstracts away version
differences.

---

## Importing Qt

Always import Qt inside `activate()`, not at module level. The plugin discovery
system imports your module before Qt is guaranteed to be available.

```python
def activate(self, api):
    self._api = api

    # Safe — Qt is available by the time activate() is called.
    from mca_qt.qt_compat import (
        QWidget, QLabel, QVBoxLayout, QHBoxLayout,
        QPushButton, QLineEdit, QTextEdit, QCheckBox,
        QComboBox, QSpinBox, QTimer, QIcon
    )
```

---

## Available Classes

These classes are safe to import from `mca_qt.qt_compat`:

| Class | Notes |
|---|---|
| `QWidget` | Base class for all panels |
| `QLabel` | Static text |
| `QVBoxLayout`, `QHBoxLayout`, `QGridLayout` | Layout managers |
| `QPushButton` | Clickable button |
| `QLineEdit` | Single-line text input |
| `QTextEdit` | Multi-line text area |
| `QCheckBox` | Boolean toggle |
| `QComboBox` | Dropdown selector |
| `QSpinBox`, `QDoubleSpinBox` | Numeric inputs |
| `QTimer` | Periodic callbacks |
| `QIcon` | Icons for panels and actions |
| `QSizePolicy` | Widget sizing hints |
| `Qt` | Namespace for flags (e.g., `Qt.AlignTop`) |

For anything not in this list, import directly from `PySide6.QtWidgets` or
`PySide6.QtCore` — MCA Editor targets Maya 2025+ which ships PySide6.

---

## Building a Panel

Panels are registered with `api.add_panel()` and displayed in the right sidebar.
They must be `QWidget` instances.

```python
from mca_qt.qt_compat import QWidget, QVBoxLayout, QLabel, QPushButton

panel = QWidget()
layout = QVBoxLayout(panel)
layout.setContentsMargins(8, 8, 8, 8)
layout.setSpacing(6)

layout.addWidget(QLabel("My Plugin"))
layout.addWidget(QPushButton("Run"))
layout.addStretch()  # Push widgets to the top

api.add_panel("my-plugin", "My Plugin", panel)
```

---

## Custom Panel Icons

By default, plugin panels get a blue puzzle piece icon in the sidebar stripe. You
can replace it by passing a `QIcon` to `add_panel()`.

**Load an image from your plugin folder:**

```python
import os
from mca_qt.qt_compat import QIcon

# Build the path relative to your plugin's __init__.py
plugin_dir = os.path.dirname(__file__)
icon = QIcon(os.path.join(plugin_dir, "my_icon.png"))

api.add_panel("my-plugin", "My Plugin", panel, icon=icon)
```

Recommended icon size is **16x16** or **20x20** pixels. PNG with transparency works
best against the dark sidebar.

**Use a built-in editor icon:**

```python
from mca_qt.icons import settings_icon, maya_logo

api.add_panel("my-plugin", "My Plugin", panel, icon=maya_logo())
```

Available built-in icons: `folder_closed()`, `folder_open()`, `python_logo()`,
`maya_logo()`, `text_icon()`, `settings_icon()`, `mca_logo()`,
`plugin_icon()`.

**Paint one programmatically:**

```python
from mca_qt.qt_compat import QIcon, QPixmap, QPainter, QColor, Qt

pixmap = QPixmap(16, 16)
pixmap.fill(Qt.GlobalColor.transparent)
painter = QPainter(pixmap)
painter.setBrush(QColor("#E8922A"))
painter.setPen(Qt.PenStyle.NoPen)
painter.drawEllipse(1, 1, 14, 14)
painter.end()

icon = QIcon(pixmap)
api.add_panel("my-plugin", "My Plugin", panel, icon=icon)
```

---

## Timer-Based Updates

Use `QTimer` for periodic refreshes. Always stop timers in `deactivate()`.

```python
from mca_qt.qt_compat import QTimer

def activate(self, api):
    self._api = api
    # ... build UI ...

    self._timer = QTimer()
    self._timer.timeout.connect(self._refresh)
    self._timer.start(5000)  # Refresh every 5 seconds

def deactivate(self):
    self._timer.stop()
    self._timer = None
    self._api.remove_panel("my-plugin")
    self._api = None
```

---

## Maya Version Notes

| Maya Version | Qt Version | Import |
|---|---|---|
| Maya 2024 | Qt5 / PySide2 | Not supported by plugin API |
| Maya 2025 | Qt6 / PySide6 | Fully supported |
| Maya 2026 | Qt6 / PySide6 | Fully supported |

MCA Editor's plugin system requires **Maya 2025 or later**. PySide2 is not supported.
