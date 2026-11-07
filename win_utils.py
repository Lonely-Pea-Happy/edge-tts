"""Windows 11 原生平台细节。

包含三类能力：
1. DWM 窗口属性（深色标题栏、Win11 圆角）
2. 系统主题 / 强调色读取
3. 无边框窗口的 WM_NCHITTEST 命中常量（用原生拖动、Aero Snap 与八向缩放）
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

IS_WIN = sys.platform == "win32"

# -- DWM 属性 ---------------------------------------------------------
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMSBT_MAINWINDOW = 2  # Mica

DWMWCP_DEFAULT = 0
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2

# -- 命中测试 --------------------------------------------------------
WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
WM_NCLBUTTONDOWN = 0x00A1
WM_NCLBUTTONUP = 0x00A2
WM_NCLBUTTONDBLCLK = 0x00A3

HTTRANSPARENT = -1
HTCLIENT = 1
HTCAPTION = 2
HTMAXBUTTON = 9   # 悬停时由 DWM 弹出 Win11 的「贴靠布局」，点一下走最大化
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17

# -- 窗口样式 --------------------------------------------------------
GWL_STYLE = -16
WS_POPUP = 0x80000000
WS_MAXIMIZE = 0x01000000
WS_OVERLAPPEDWINDOW = 0x00CF0000

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

SM_CXSIZEFRAME = 32
SM_CYSIZEFRAME = 33
SM_CXPADDEDBORDER = 92


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long), ("top", ctypes.c_long),
        ("right", ctypes.c_long), ("bottom", ctypes.c_long),
    ]


class NCCALCSIZE_PARAMS(ctypes.Structure):
    """WM_NCCALCSIZE 的 wParam=TRUE 时 lParam 指向这个结构。"""

    _fields_ = [("rgrc", RECT * 3), ("lppos", ctypes.c_void_p)]

if IS_WIN:
    _dwmapi = ctypes.WinDLL("dwmapi")
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    # 不显式声明 argtypes 时，ctypes 会把样式值当 int 传，WS_* 这种 32 位掩码
    # 容易抛 OverflowError（表现为样式静默改不掉）。
    _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetWindowLongW.restype = ctypes.c_long
    _user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    _user32.SetWindowLongW.restype = ctypes.c_long
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
    ]
    _user32.SetWindowPos.restype = ctypes.c_int
    # 逐显示器 DPI 相关（Win10 1607+）。老系统上取不到就退回到 GetSystemMetrics。
    try:
        _user32.GetDpiForWindow.argtypes = [wintypes.HWND]
        _user32.GetDpiForWindow.restype = ctypes.c_uint
    except AttributeError:
        pass
    try:
        _user32.GetDpiForSystem.restype = ctypes.c_uint
    except AttributeError:
        pass
    try:
        _user32.GetSystemMetricsForDpi.argtypes = [ctypes.c_int, ctypes.c_uint]
        _user32.GetSystemMetricsForDpi.restype = ctypes.c_int
    except AttributeError:
        pass
else:  # pragma: no cover - 本项目只针对 Windows
    _dwmapi = None
    _user32 = None


def _set_dword(hwnd: int, attribute: int, value: int) -> bool:
    if not IS_WIN or not hwnd:
        return False
    try:
        data = ctypes.c_int(int(value))
        res = _dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd), ctypes.c_uint(attribute),
            ctypes.byref(data), ctypes.sizeof(data),
        )
        return res == 0
    except Exception:
        return False


def apply_dark_frame(hwnd: int, dark: bool) -> None:
    """让 DWM 的窗口边框/标题栏跟随深色，避免边框处出现刺眼白边。"""
    _set_dword(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)


def apply_round_corners(hwnd: int) -> None:
    """Win11 22H2+ 的 DWM 自动圆角（本窗口为透明无边框，圆角由自绘负责，此调用作兜底）。"""
    _set_dword(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)


def try_mica(hwnd: int) -> bool:
    """尝试启用 Mica 背景。返回是否被系统接受。"""
    if not IS_WIN or not hwnd:
        return False
    ok = _set_dword(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_MAINWINDOW)
    if ok:
        apply_round_corners(hwnd)
    return ok


def make_native_frame(hwnd: int) -> bool:
    """把 Qt 的无边框窗口改造成「标准窗口框架 + 客户区铺满」。

    为什么必须这么做：Qt 的 FramelessWindowHint 在 Win32 层是 WS_POPUP，
    没有 WS_THICKFRAME / WS_MINIMIZEBOX / WS_MAXIMIZEBOX / WS_SYSMENU。
    这种窗口 Windows 不会给它最小化/最大化动画，也没有贴靠布局、Aero Snap
    和标题栏右键菜单。补回这些样式后，再用 WM_NCCALCSIZE 把标题栏区域让出来
    （客户区 = 整个窗口），外观仍然是自绘的，但行为回到原生。
    """
    if not IS_WIN or not hwnd:
        return False
    try:
        style = int(_user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE))
        new_style = (style & ~WS_POPUP) | WS_OVERLAPPEDWINDOW
        if new_style != style:
            _user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE, new_style)
        _user32.SetWindowPos(
            wintypes.HWND(hwnd), None, 0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
        return True
    except Exception:
        return False


def is_zoomed(hwnd: int) -> bool:
    """窗口此刻是不是最大化——直接问 Win32 的样式位，不信 Qt 的缓存状态。

    WM_NCCALCSIZE 是在窗口状态切换的**中途**发过来的：Qt 的 isMaximized()
    要等状态同步完才更新，而 WS_MAXIMIZE 位在发这条消息之前就已经改好了。
    用错的一方会导致还原后客户区被多缩一圈，露出系统的原生边框/标题栏。
    """
    if not IS_WIN or not hwnd:
        return False
    try:
        style = int(_user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE))
        return bool(style & WS_MAXIMIZE)
    except Exception:
        return False


VK_LBUTTON = 0x01
VK_RBUTTON = 0x02


def mouse_dragging() -> bool:
    """系统范围里左/右键此刻是否按着——用来判断一次拖拽到底结束了没有。

    拖拽结束时 Qt 不一定给我们 drop/leave（事件可能落在别的控件，甚至只在
    拖拽源那边收到结束），只看事件会把提示层永远留在窗口上。这里读真实按键
    状态，作为"拖拽还活着吗"的兜底判据。
    """
    if not IS_WIN:
        return False
    try:
        fn = _user32.GetAsyncKeyState
        fn.argtypes = [wintypes.INT]
        fn.restype = wintypes.SHORT
        return bool(fn(VK_LBUTTON) & 0x8000) or bool(fn(VK_RBUTTON) & 0x8000)
    except Exception:
        return False


def _dpi_for_window(hwnd: int) -> int:
    """取窗口所在显示器的 DPI；取不到就退回系统 DPI。"""
    if not IS_WIN:
        return 96
    try:
        if hwnd:
            dpi = int(_user32.GetDpiForWindow(wintypes.HWND(hwnd)))
            if dpi > 0:
                return dpi
    except Exception:
        pass
    try:
        dpi = int(_user32.GetDpiForSystem())
        if dpi > 0:
            return dpi
    except Exception:
        pass
    return 96


def frame_border(hwnd: int = 0) -> int:
    """窗口边框厚度（物理像素）。最大化时客户区要按这个内缩，否则会溢出屏幕。

    必须按**窗口所在显示器**的 DPI 算：不带 DPI 的 GetSystemMetrics 返回的是
    主屏缩放下的值，把窗口拖到另一块缩放比例不同的显示器上最大化时，内缩量
    会差几个像素（客户区被裁一点或留一条细边）。这里用 GetDpiForWindow +
    GetSystemMetricsForDpi，逐显示器都对；老系统取不到就退回旧接口。
    """
    if not IS_WIN:
        return 0
    dpi = _dpi_for_window(hwnd)
    try:
        frame = int(_user32.GetSystemMetricsForDpi(SM_CXSIZEFRAME, dpi))
        pad = int(_user32.GetSystemMetricsForDpi(SM_CXPADDEDBORDER, dpi))
        if frame or pad:
            return frame + pad
    except Exception:
        pass
    try:
        return int(_user32.GetSystemMetrics(SM_CXSIZEFRAME)) + int(
            _user32.GetSystemMetrics(SM_CXPADDEDBORDER)
        )
    except Exception:
        return 8


def read_app_light_theme() -> bool:
    """系统「应用模式」是否为浅色。"""
    if not IS_WIN:
        return True
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return bool(value)
    except Exception:
        return True


def read_accent_color() -> str | None:
    """读取系统强调色，返回 #RRGGBB；失败返回 None。"""
    if not IS_WIN:
        return None
    try:
        color = wintypes.DWORD(0)
        opaque = wintypes.BOOL(0)
        res = _dwmapi.DwmGetColorizationColor(
            ctypes.byref(color), ctypes.byref(opaque)
        )
        if res != 0 or not color.value:
            return None
        argb = int(color.value)
        # DwmGetColorizationColor 以 0xAARRGGBB 返回
        r = (argb >> 16) & 0xFF
        g = (argb >> 8) & 0xFF
        b = argb & 0xFF
        return f"#{r:02X}{g:02X}{b:02X}"
    except Exception:
        return None


def set_app_user_model_id(app_id: str) -> None:
    """让任务栏使用自定义图标而不是 python.exe 的图标。"""
    if not IS_WIN:
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


if __name__ == "__main__":  # 手工探测器
    print("light theme:", read_app_light_theme())
    print("accent:", read_accent_color())
