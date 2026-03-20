"""
Test: HWND recreation after parent window destruction.

Simulates what happens during UE dock/undock:
1. Create a PySide6 widget
2. SetParent it to a Win32 window (simulates embedding)
3. Destroy the parent window (simulates undocking)
4. Check if IsWindow returns False
5. Try to recreate the HWND
6. SetParent to a new window (simulates re-docking)
"""
import sys
import os
import ctypes
import ctypes.wintypes

# Add MCA source to path for venv_manager.
sys.path.insert(0, r"E:\Projects\MCAEditor")
from mca_core.venv_manager import setup_venv
setup_venv()

from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtCore import Qt

# Win32 functions.
user32 = ctypes.windll.user32
CreateWindowExW = user32.CreateWindowExW
DestroyWindow = user32.DestroyWindow
SetParent = user32.SetParent
IsWindow = user32.IsWindow
ShowWindow = user32.ShowWindow
MoveWindow = user32.MoveWindow

# Window class name for dummy windows.
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
SW_SHOW = 5

app = QApplication.instance() or QApplication(sys.argv)

print("=" * 60)
print("HWND Recreation Test")
print("=" * 60)

# --- Step 1: Create a Qt widget ---
widget = QLabel("Test Widget")
widget.setWindowFlags(Qt.WindowType.FramelessWindowHint)
widget.resize(200, 100)
qt_hwnd = int(widget.winId())
print(f"\n1. Created Qt widget. HWND = {hex(qt_hwnd)}")
print(f"   IsWindow: {bool(IsWindow(qt_hwnd))}")

# --- Step 2: Create a dummy parent Win32 window ---
parent_hwnd = CreateWindowExW(
    0, "Static", "Fake UE Window",
    WS_OVERLAPPEDWINDOW | WS_VISIBLE,
    100, 100, 400, 300,
    0, 0, 0, 0
)
print(f"\n2. Created parent window. HWND = {hex(parent_hwnd)}")
print(f"   IsWindow: {bool(IsWindow(parent_hwnd))}")

# --- Step 3: SetParent (embed Qt widget as child) ---
SetParent(qt_hwnd, parent_hwnd)
widget.show()
MoveWindow(qt_hwnd, 10, 10, 180, 80, True)
app.processEvents()
print(f"\n3. SetParent done. Qt is now child of parent window.")
print(f"   Qt HWND IsWindow: {bool(IsWindow(qt_hwnd))}")

# --- Step 4: Destroy the parent (simulates UE dock/undock) ---
print(f"\n4. Destroying parent window (simulates dock/undock)...")
DestroyWindow(parent_hwnd)
app.processEvents()
print(f"   Parent IsWindow: {bool(IsWindow(parent_hwnd))}")
print(f"   Qt HWND IsWindow: {bool(IsWindow(qt_hwnd))}")

# --- Step 5: Try to recreate the HWND ---
print(f"\n5. Attempting HWND recreation...")

# Method A: setWindowFlags (same flags)
print(f"   5a. Trying setWindowFlags(same flags)...")
flags = widget.windowFlags()
widget.setWindowFlags(flags)
new_hwnd_a = int(widget.winId())
print(f"       New HWND = {hex(new_hwnd_a)}, IsWindow: {bool(IsWindow(new_hwnd_a))}")

if not IsWindow(new_hwnd_a):
    # Method B: setWindowFlags (different flags then back)
    print(f"   5b. Trying setWindowFlags(Window then FramelessWindowHint)...")
    widget.setWindowFlags(Qt.WindowType.Window)
    widget.setWindowFlags(Qt.WindowType.FramelessWindowHint)
    new_hwnd_b = int(widget.winId())
    print(f"       New HWND = {hex(new_hwnd_b)}, IsWindow: {bool(IsWindow(new_hwnd_b))}")

if not IsWindow(new_hwnd_a):
    # Method C: setParent(None) + setWindowFlags
    print(f"   5c. Trying setParent(None) + setWindowFlags...")
    widget.setParent(None)
    widget.setWindowFlags(Qt.WindowType.FramelessWindowHint)
    widget.show()
    new_hwnd_c = int(widget.winId())
    print(f"       New HWND = {hex(new_hwnd_c)}, IsWindow: {bool(IsWindow(new_hwnd_c))}")

if not IsWindow(new_hwnd_a):
    # Method D: hide + show
    print(f"   5d. Trying hide() + show()...")
    widget.hide()
    widget.show()
    new_hwnd_d = int(widget.winId())
    print(f"       New HWND = {hex(new_hwnd_d)}, IsWindow: {bool(IsWindow(new_hwnd_d))}")

# Find the first valid HWND from the attempts.
final_hwnd = None
for h in [new_hwnd_a,
          locals().get('new_hwnd_b', 0),
          locals().get('new_hwnd_c', 0),
          locals().get('new_hwnd_d', 0)]:
    if h and IsWindow(h):
        final_hwnd = h
        break

# --- Step 6: Create a new parent and reparent ---
if final_hwnd:
    print(f"\n6. Success! Valid HWND = {hex(final_hwnd)}")
    parent2_hwnd = CreateWindowExW(
        0, "Static", "New Parent Window",
        WS_OVERLAPPEDWINDOW | WS_VISIBLE,
        200, 200, 400, 300,
        0, 0, 0, 0
    )
    SetParent(final_hwnd, parent2_hwnd)
    widget.show()
    MoveWindow(final_hwnd, 10, 10, 180, 80, True)
    app.processEvents()
    print(f"   Reparented to new window. Qt HWND IsWindow: {bool(IsWindow(final_hwnd))}")

    # Keep window visible briefly.
    import time
    time.sleep(1)
    app.processEvents()

    DestroyWindow(parent2_hwnd)
    print(f"\n   PASS: HWND recreation worked!")
else:
    print(f"\n6. FAIL: Could not recreate a valid HWND!")
    print(f"   All methods failed.")

print(f"\n{'=' * 60}")
