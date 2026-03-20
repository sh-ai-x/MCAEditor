"""
Test: More aggressive HWND recreation approaches.
"""
import sys
import ctypes

sys.path.insert(0, r"E:\Projects\MCAEditor")
from mca_core.venv_manager import setup_venv
setup_venv()

from PySide6.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout
from PySide6.QtCore import Qt

user32 = ctypes.windll.user32
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000

app = QApplication.instance() or QApplication(sys.argv)

print("=" * 60)
print("HWND Recreation Test - Aggressive Methods")
print("=" * 60)

# Create widget, embed, destroy parent.
widget = QLabel("Test Widget Content")
widget.setWindowFlags(Qt.WindowType.FramelessWindowHint)
widget.resize(200, 100)
qt_hwnd = int(widget.winId())
print(f"Original HWND: {hex(qt_hwnd)}, IsWindow: {bool(user32.IsWindow(qt_hwnd))}")

parent = user32.CreateWindowExW(0, "Static", "Parent", WS_OVERLAPPEDWINDOW | WS_VISIBLE, 100, 100, 400, 300, 0, 0, 0, 0)
user32.SetParent(qt_hwnd, parent)
widget.show()
app.processEvents()

print(f"After SetParent: HWND: {hex(qt_hwnd)}, IsWindow: {bool(user32.IsWindow(qt_hwnd))}")

# Destroy parent — kills the child HWND.
user32.DestroyWindow(parent)
app.processEvents()
print(f"After parent destroyed: HWND: {hex(qt_hwnd)}, IsWindow: {bool(user32.IsWindow(qt_hwnd))}")

# --- Method E: destroy() + create() ---
print(f"\nMethod E: widget.destroy() + widget.create()")
try:
    widget.destroy()
    widget.create()
    new_hwnd = int(widget.winId())
    print(f"  HWND: {hex(new_hwnd)}, IsWindow: {bool(user32.IsWindow(new_hwnd))}")
except Exception as e:
    print(f"  Exception: {e}")

# --- Method F: Create a NEW wrapper widget ---
print(f"\nMethod F: Create new wrapper QWidget, reparent content into it")
try:
    wrapper = QWidget()
    wrapper.setWindowFlags(Qt.WindowType.FramelessWindowHint)
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)

    # Create a FRESH label (old widget is dead)
    new_content = QLabel("Recreated Content")
    layout.addWidget(new_content)

    wrapper_hwnd = int(wrapper.winId())
    print(f"  Wrapper HWND: {hex(wrapper_hwnd)}, IsWindow: {bool(user32.IsWindow(wrapper_hwnd))}")

    # Embed into a new parent
    parent2 = user32.CreateWindowExW(0, "Static", "Parent2", WS_OVERLAPPEDWINDOW | WS_VISIBLE, 200, 200, 400, 300, 0, 0, 0, 0)
    user32.SetParent(wrapper_hwnd, parent2)
    wrapper.show()
    user32.MoveWindow(wrapper_hwnd, 10, 10, 180, 80, True)
    app.processEvents()
    print(f"  After SetParent: IsWindow: {bool(user32.IsWindow(wrapper_hwnd))}")

    import time; time.sleep(1); app.processEvents()
    user32.DestroyWindow(parent2)
    print(f"  PASS: New wrapper widget works!")
except Exception as e:
    print(f"  Exception: {e}")

# --- Method G: Use QWindow instead of QWidget ---
print(f"\nMethod G: Check if old widget children are still alive")
try:
    print(f"  widget.isVisible(): {widget.isVisible()}")
    print(f"  widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created): {widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created)}")
    print(f"  widget.windowHandle(): {widget.windowHandle()}")
except Exception as e:
    print(f"  Exception: {e}")

# --- Method H: setAttribute WA_NativeWindow + winId ---
print(f"\nMethod H: Explicitly clear WA_WState_Created, then winId()")
try:
    widget.setAttribute(Qt.WidgetAttribute(1), False)  # WA_WState_Created = 1
    widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
    new_hwnd = int(widget.winId())
    print(f"  HWND: {hex(new_hwnd)}, IsWindow: {bool(user32.IsWindow(new_hwnd))}")
except Exception as e:
    print(f"  Exception: {e}")

print(f"\n{'=' * 60}")
