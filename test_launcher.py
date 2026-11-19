"""Open the actual standalone GUI, inspect its window, then close it normally."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import time

from PIL import Image
import psutil
from process_test_utils import stop_owned_process


def capture_window(hwnd, width, height, path):
    user32 = ctypes.WinDLL("user32")
    gdi32 = ctypes.WinDLL("gdi32")
    user32.GetWindowDC.argtypes = [wintypes.HWND]
    user32.GetWindowDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi32.SelectObject.restype = wintypes.HANDLE
    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    class Header(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("width", wintypes.LONG), ("height", wintypes.LONG),
                    ("planes", wintypes.WORD), ("bits", wintypes.WORD), ("compression", wintypes.DWORD),
                    ("image_size", wintypes.DWORD), ("x", wintypes.LONG), ("y", wintypes.LONG),
                    ("used", wintypes.DWORD), ("important", wintypes.DWORD)]
    dc = user32.GetWindowDC(hwnd)
    memory = gdi32.CreateCompatibleDC(dc)
    bitmap = gdi32.CreateCompatibleBitmap(dc, width, height)
    old = gdi32.SelectObject(memory, bitmap)
    try:
        assert user32.PrintWindow(hwnd, memory, 2), "Window capture failed"
        header = Header(ctypes.sizeof(Header), width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0)
        pixels = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                                  ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
        gdi32.SelectObject(memory, old)
        assert gdi32.GetDIBits(memory, bitmap, 0, height, pixels, ctypes.byref(header), 0)
        Image.frombytes("RGB", (width, height), pixels.raw, "raw", "BGRX").save(path)
    finally:
        gdi32.SelectObject(memory, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory)
        user32.ReleaseDC(hwnd, dc)


def main():
    root = Path(__file__).parent
    process = psutil.Popen([str(root / "dist/WiFiAudio.exe")])
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    try:
        window = None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not window:
            pids = {process.pid} | {child.pid for child in process.children(recursive=True)}
            found = []
            @callback_type
            def visit(hwnd, value):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                title = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, title, 256)
                if pid.value in pids and title.value == "WiFiAudio":
                    found.append(hwnd)
                return True
            user32.EnumWindows(visit, 0)
            window = found[0] if found else None
            time.sleep(.1)
        assert window, "Standalone GUI did not appear"
        time.sleep(1)
        rectangle = wintypes.RECT()
        assert user32.GetWindowRect(window, ctypes.byref(rectangle))
        assert rectangle.right - rectangle.left >= 640
        capture_window(window, rectangle.right - rectangle.left, rectangle.bottom - rectangle.top, root / "desktop-preview.png")
        user32.PostMessageW(window, 0x0010, 0, 0)  # WM_CLOSE: normal user close path
        assert process.wait(timeout=15) == 0
        print("PASS: standalone EXE opens the desktop UI and closes normally")
    finally:
        if process.is_running():
            stop_owned_process(process)


if __name__ == "__main__":
    main()
