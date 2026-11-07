"""Windows 11 / WinUI 3 设计令牌与主题管理。

颜色取自 WinUI 3 的 Light / Dark 资源字典（AccentFillColorDefault、LayerFillColorDefault
等），用 #AARRGGBB 形式存放，QColor 可直接解析。
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFont

import win_utils

# ---------------------------------------------------------------- 颜色令牌

LIGHT = {
    "window": "#FFF3F3F3",
    "window_stroke": "#24000000",
    "layer": "#F7FFFFFF",
    "layer_alt": "#0FFFFFFF",
    "layer_stroke": "#14000000",
    "control_fill": "#B3FFFFFF",
    "control_hover": "#E6FFFFFF",
    "control_pressed": "#99FFFFFF",
    "control_stroke": "#14000000",
    "stroke_strong": "#29000000",
    "text_primary": "#E4000000",
    "text_secondary": "#9E000000",
    "text_tertiary": "#73000000",
    "text_disabled": "#5C000000",
    # 语义状态色（取自 WinUI 3 SystemFillColorSuccess/Caution/Critical）
    "state_ok": "#FF0F7B0F",
    "state_warn": "#FF9D5D00",
    "state_error": "#FFC42B1C",
    "accent": "#FF005FB8",
    "on_accent": "#FFFFFFFF",
    "accent_subtle": "#24005FB8",
    "ghost_hover": "#0A000000",
    "ghost_pressed": "#05000000",
    "close_hover": "#FFC42B1C",
    "close_pressed": "#FFB01D14",
    "divider": "#12000000",
    "shadow": "#33000000",
    "editor_bg": "#FFFFFFFF",
}

DARK = {
    "window": "#FF202020",
    "window_stroke": "#0FFFFFFF",
    "layer": "#FF2B2B2B",
    "layer_alt": "#0CFFFFFF",
    "layer_stroke": "#12FFFFFF",
    "control_fill": "#0FFFFFFF",
    "control_hover": "#1AFFFFFF",
    "control_pressed": "#0AFFFFFF",
    "control_stroke": "#18FFFFFF",
    "stroke_strong": "#2EFFFFFF",
    "text_primary": "#FFFFFFFF",
    "text_secondary": "#C5FFFFFF",
    "text_tertiary": "#8AFFFFFF",
    "text_disabled": "#5CFFFFFF",
    # 深色下用更亮的语义状态色，保证在 #202020 上可读
    "state_ok": "#FF6CCB5F",
    "state_warn": "#FFFCE100",
    "state_error": "#FFFF99A4",
    "accent": "#FF4CC2FF",
    "on_accent": "#FF000000",
    "accent_subtle": "#264CC2FF",
    "ghost_hover": "#0FFFFFFF",
    "ghost_pressed": "#08FFFFFF",
    "close_hover": "#FFC42B1C",
    "close_pressed": "#FFB01D14",
    "divider": "#14FFFFFF",
    "shadow": "#66000000",
    "editor_bg": "#1AFFFFFF",
}


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    """在 a 与 b 之间线性插值，t=0 取 a，t=1 取 b。"""
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        a.alpha(),
    )


def _luminance(c: QColor) -> float:
    return (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) / 255


def _normalize_accent(raw: str | None, dark: bool) -> QColor:
    """把系统强调色收敛到 Win11 按钮可用的明度区间。"""
    default = QColor("#4CC2FF" if dark else "#005FB8")
    if not raw:
        return default
    c = QColor(raw)
    if not c.isValid():
        return default
    if c.saturation() < 40:  # 灰度 / 接近黑白，不是可用的强调色
        return default
    lum = _luminance(c)
    if dark and lum < 0.62:
        c = _mix(c, QColor("#FFFFFF"), (0.62 - lum) / (1 - lum))
    if not dark and lum > 0.34:
        c = _mix(c, QColor("#000000"), (lum - 0.34) / lum)
    return c


class Theme:
    """一套已解析好的颜色 + 排版令牌。"""

    def __init__(self, dark: bool, accent: str | None = None):
        self.is_dark = dark
        self._c = dict(DARK if dark else LIGHT)
        acc = _normalize_accent(accent, dark)
        self._c["accent"] = acc.name(QColor.HexArgb)
        self._c["accent_hover"] = _mix(
            acc, QColor("#FFFFFF" if dark else "#FFFFFF"), 0.12 if dark else 0.06
        ).name(QColor.HexArgb)
        self._c["accent_pressed"] = _mix(acc, QColor("#000000"), 0.18 if dark else 0.12).name(
            QColor.HexArgb
        )
        self._c["on_accent"] = "#FF000000" if _luminance(acc) > 0.62 else "#FFFFFFFF"
        # 强调色的低透明版本：HexArgb 是 "#AARRGGBB"，取后 6 位换成 2E 的 alpha
        self._c["accent_subtle"] = "#2E" + acc.name(QColor.HexArgb)[3:]

    # -- 取色 --------------------------------------------------------
    def c(self, key: str) -> QColor:
        return QColor(self._c[key])

    def qss(self, key: str, alpha: float | None = None) -> str:
        """返回 QSS 可用的 rgba() 字符串。"""
        col = self.c(key)
        a = col.alphaF() if alpha is None else alpha
        return f"rgba({col.red()},{col.green()},{col.blue()},{round(a, 3)})"

    def hex(self, key: str) -> str:
        col = self.c(key)
        return f"#{col.red():02X}{col.green():02X}{col.blue():02X}"


# ---------------------------------------------------------------- 排版令牌

RADIUS_WINDOW = 8
RADIUS_CARD = 8
RADIUS_CONTROL = 4
TITLEBAR_HEIGHT = 30
"""标题栏高度（逻辑像素）。

本机原生带标题栏窗口实测：非客户区 56 物理 px @150%（≈37 逻辑），其中含
DWM 边框；原生标题栏本身没有这么高。这里取 30 是为了对齐 Win11 记事本一类
应用的观感（32 逻辑高度减去 1px 边框），比「等于非客户区」矮，属于判断而非
像素级复刻。
"""

CAPTION_BUTTON_WIDTH = 46
SHADOW_MARGIN = 0
"""窗口四周留给自绘阴影的留白。

恢复原生窗口框架后，阴影和圆角都由 DWM 负责（窗口不再用 WS_EX_LAYERED），
自绘阴影会和系统阴影叠成两层，因此这里归零。
"""

_TYPE_RAMP = {
    "caption": 12,
    "body": 14,
    "body_strong": 14,
    "subtitle": 20,
    "title": 28,
}

_FONT_FAMILIES: list[str] = []


def _families() -> list[str]:
    global _FONT_FAMILIES
    if not _FONT_FAMILIES:
        from PySide6.QtGui import QFontDatabase

        available = set(QFontDatabase.families())
        for fam in (
            "Segoe UI Variable Display",
            "Segoe UI Variable Text",
            "Segoe UI Variable",
            "Segoe UI",
            "Microsoft YaHei UI",
            "Microsoft YaHei",
        ):
            if fam in available:
                _FONT_FAMILIES.append(fam)
        if not _FONT_FAMILIES:
            _FONT_FAMILIES = ["Segoe UI", "Arial"]
    return _FONT_FAMILIES


def ui_font(size: int = 14, weight: QFont.Weight = QFont.Weight.Normal, *,
            display: bool = False, family: str | None = None) -> QFont:
    """生成一个带 CJK 回退链的 Fluent 字体。"""
    f = QFont()
    if family:
        f.setFamilies([family] + _families())
    elif display:
        fams = _families()
        order = ["Segoe UI Variable Display", "Segoe UI Variable Text"]
        f.setFamilies(order + [x for x in fams if x not in order])
    else:
        fams = _families()
        order = ["Segoe UI Variable Text", "Segoe UI"]
        f.setFamilies(order + [x for x in fams if x not in order])
    f.setPixelSize(size)
    f.setWeight(weight)
    return f


def ramp(key: str) -> int:
    return _TYPE_RAMP[key]


def mono_font(size: int = 12) -> QFont:
    f = QFont()
    f.setFamilies(["Cascadia Mono", "Consolas", "Microsoft YaHei UI"])
    f.setPixelSize(size)
    return f


# ---------------------------------------------------------------- 主题管理


class ThemeManager(QObject):
    """全局主题单例：跟随系统 / 浅色 / 深色。"""

    changed = Signal()

    MODES = ("system", "light", "dark")

    @property
    def MODE_LABELS(self) -> dict[str, str]:
        """主题档位的人话名字，跟随界面语言。"""
        import i18n

        return {m: i18n.t(f"theme.{m}") for m in self.MODES}

    def __init__(self):
        super().__init__()
        self._mode = "system"
        self._theme = Theme(self._system_dark(), win_utils.read_accent_color())

    # -- 状态 --------------------------------------------------------
    @property
    def mode(self) -> str:
        return self._mode

    @property
    def theme(self) -> Theme:
        return self._theme

    def _system_dark(self) -> bool:
        if not win_utils.IS_WIN:
            return True
        return not win_utils.read_app_light_theme()

    def set_mode(self, mode: str) -> None:
        if mode not in self.MODES:
            return
        self._mode = mode
        self.refresh()

    def cycle(self) -> str:
        idx = self.MODES.index(self._mode)
        self.set_mode(self.MODES[(idx + 1) % len(self.MODES)])
        return self._mode

    def refresh(self) -> None:
        dark = self._system_dark() if self._mode == "system" else self._mode == "dark"
        self._theme = Theme(dark, win_utils.read_accent_color())
        self.changed.emit()

    def follow_system_change(self) -> None:
        """系统主题切换时调用（仅当处于跟随系统模式）。"""
        if self._mode != "system":
            return
        if self._theme.is_dark == self._system_dark():
            return
        self.refresh()


_tm: ThemeManager | None = None


def tm() -> ThemeManager:
    global _tm
    if _tm is None:
        _tm = ThemeManager()
    return _tm
