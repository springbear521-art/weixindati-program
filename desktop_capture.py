"""Capture a visible Windows desktop window as PNG without third-party packages."""

from __future__ import annotations

import ctypes
import struct
import tempfile
import time
import zlib
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path


user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
gdi32.SelectObject.restype = wintypes.HANDLE
gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.BitBlt.restype = wintypes.BOOL
gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
gdi32.DeleteDC.argtypes = [wintypes.HDC]


@dataclass(frozen=True)
class WindowChoice:
    hwnd: int
    title: str


@dataclass(frozen=True)
class WindowFrame:
    pixels: bytes
    width: int
    height: int
    signature: bytes


def set_dpi_awareness() -> None:
    """Keep Tk and Win32 window coordinates in the same physical-pixel space."""
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def list_windows() -> list[WindowChoice]:
    found: list[WindowChoice] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def collect(hwnd: int, _param: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length < 2:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        rect = wintypes.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)) and rect.right - rect.left >= 150 and rect.bottom - rect.top >= 150:
            found.append(WindowChoice(int(hwnd), buffer.value))
        return True

    if not user32.EnumWindows(collect, 0) and ctypes.get_last_error():
        raise OSError("无法枚举桌面窗口。")
    return found


def f8_pressed() -> bool:
    return bool(user32.GetAsyncKeyState(0x77) & 0x8000)


def activate_window(hwnd: int) -> None:
    if not user32.IsWindow(hwnd):
        raise RuntimeError("所选小程序窗口已关闭，请刷新窗口列表。")
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.12)


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    if not user32.IsWindow(hwnd):
        raise RuntimeError("所选小程序窗口已关闭，请刷新窗口列表。")
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise OSError("无法获取窗口位置。")
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def signature_difference(first: bytes, second: bytes) -> float:
    """Share of sampled question pixels that changed visibly."""
    if len(first) != len(second) or not first:
        return 1.0
    return sum(abs(a - b) >= 28 for a, b in zip(first, second)) / len(first)


def _signature(raw: bytes, width: int, height: int) -> bytes:
    # The upper 45% holds the question; answer selection animations are lower down.
    question_height = max(1, int(height * 0.45))
    sample_width, sample_height = min(width, 128), min(question_height, 64)
    result = bytearray()
    for y_index in range(sample_height):
        y = min(question_height - 1, (y_index * question_height + question_height // 2) // sample_height)
        for x_index in range(sample_width):
            x = min(width - 1, (x_index * width + width // 2) // sample_width)
            offset = (y * width + x) * 4
            b, g, r = raw[offset], raw[offset + 1], raw[offset + 2]
            result.append((r * 30 + g * 59 + b * 11) // 100)
    return bytes(result)


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _png_from_bgra(raw: bytes, width: int, height: int) -> bytes:
    pixels = bytearray(raw)
    for offset in range(0, len(pixels), 4):
        pixels[offset], pixels[offset + 2] = pixels[offset + 2], pixels[offset]
        pixels[offset + 3] = 255
    stride = width * 4
    scanlines = b"".join(b"\x00" + pixels[y * stride:(y + 1) * stride] for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(scanlines, 1)) + _chunk(b"IEND", b"")


def read_window_frame(hwnd: int, region: tuple[int, int, int, int] | None = None) -> WindowFrame:
    left, top, width, height = window_rect(hwnd)
    if not (150 <= width <= 6000 and 150 <= height <= 6000):
        raise ValueError("窗口尺寸异常；请恢复窗口并重试。")
    x, y, crop_width, crop_height = region or (0, 0, width, height)
    if min(x, y) < 0 or crop_width < 80 or crop_height < 80 or x + crop_width > width or y + crop_height > height:
        raise ValueError("框选区域已超出窗口；请重新框选题目。")
    screen_dc = user32.GetDC(None)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(screen_dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
    if not screen_dc or not memory_dc or not bitmap or not bits.value:
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory_dc:
            gdi32.DeleteDC(memory_dc)
        if screen_dc:
            user32.ReleaseDC(None, screen_dc)
        raise OSError("无法创建截图缓冲区。")
    old = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not gdi32.BitBlt(memory_dc, 0, 0, width, height, screen_dc, left, top, 0x00CC0020 | 0x40000000):
            screen_error = ctypes.get_last_error()
            if not user32.PrintWindow(hwnd, memory_dc, 2):
                raise OSError(f"桌面截图失败（Windows 错误 {screen_error}）；请确保小程序窗口可见。")
        pixels = ctypes.string_at(bits, width * height * 4)
    finally:
        gdi32.SelectObject(memory_dc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(None, screen_dc)
    row_bytes = crop_width * 4
    cropped = b"".join(pixels[((y + row) * width + x) * 4:((y + row) * width + x) * 4 + row_bytes]
                       for row in range(crop_height))
    return WindowFrame(cropped, crop_width, crop_height,
                       _signature(cropped, crop_width, crop_height))


def save_frame(frame: WindowFrame) -> Path:
    with tempfile.NamedTemporaryFile(prefix="weread_desktop_", suffix=".png", delete=False) as output:
        output.write(_png_from_bgra(frame.pixels, frame.width, frame.height))
        return Path(output.name)


def capture_window(hwnd: int, region: tuple[int, int, int, int] | None = None) -> Path:
    return save_frame(read_window_frame(hwnd, region))
