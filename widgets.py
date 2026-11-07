"""WinUI 3 风格的自绘控件。
全部控件在 paintEvent 里按 WinUI 3 的圆角、填充、描边、焦点框规则自绘。
尺寸与配色取自 theme.py 的设计令牌，因此换主题时只需重绘。
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPalette,
    QPen,
    QTextCharFormat,
    QTextCursor,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QLabel,
    QLineEdit,
    QListView,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTextEdit,
    QWidget,
)

import glyphs
import i18n
from theme import (
    CAPTION_BUTTON_WIDTH,
    RADIUS_CARD,
    RADIUS_CONTROL,
    RADIUS_WINDOW,
    TITLEBAR_HEIGHT,
    tm,
    ui_font,
)


def _theme():
    return tm().theme


def _fill(key: str) -> QColor:
    return _theme().c(key)




# ------------------------------------------------------------------ 按钮


class FluentButton(QPushButton):
    """WinUI 3 按钮：Accent / Standard / Subtle 三种变体。"""

    ACCENT = "accent"
    STANDARD = "standard"
    SUBTLE = "subtle"

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        *,
        variant: str = STANDARD,
        icon: str | None = None,
        icon_token: str | None = None,
        height: int = 36,
        min_width: int = 0,
    ):
        super().__init__(text, parent)
        self._variant = variant
        self._icon = icon
        self._icon_token = icon_token  # 图标单独取一个颜色 token（强调色图标用）
        self._hover = False
        self._down = False
        self._held = False   # 弹出菜单/弹层期间保持按下底（Win11 标题栏按钮的做法）
        self._kb_focus = False
        self._pad = 12
        self.setFixedHeight(height)
        self.setFont(ui_font(14))
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFocusPolicy(Qt.StrongFocus)
        if min_width:
            self.setMinimumWidth(min_width)

    def set_icon(self, name: str, token: str | None = None) -> None:
        """换图标，可选换它自己的颜色 token。"""
        self._icon = name
        self._icon_token = token
        self.update()

    def set_held(self, held: bool) -> None:
        """弹层展开期间把按钮画成按下态：菜单开着时按钮仍带底色，像 Win11。"""
        if held != self._held:
            self._held = held
            self.update()

    # -- 事件 --------------------------------------------------------
    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self._down = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        self._down = e.button() == Qt.LeftButton
        self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._down = False
        self.update()
        super().mouseReleaseEvent(e)

    # WinUI 只在键盘导航时才显示焦点框，鼠标点击不显示
    def focusInEvent(self, e):
        self._kb_focus = e.reason() not in (
            Qt.MouseFocusReason,
            Qt.PopupFocusReason,
            Qt.ActiveWindowFocusReason,
        )
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self._kb_focus = False
        self.update()
        super().focusOutEvent(e)
    def _content_size(self) -> QSize:
        fm = QFontMetrics(self.font())
        tw = fm.horizontalAdvance(self.text())
        iw = 16 if self._icon else 0
        gap = 8 if (iw and tw) else 0
        return QSize(tw + iw + gap, fm.height())

    def sizeHint(self) -> QSize:
        c = self._content_size()
        return QSize(max(c.width() + self._pad * 2, 48), self.height())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    # -- 绘制 --------------------------------------------------------
    def paintEvent(self, e):
        th = _theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        enabled = self.isEnabled()
        hovered = self._hover and enabled
        pressed = (self._down or self._held) and enabled
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        border = None
        if not enabled:
            bg = th.c("control_fill") if self._variant != self.SUBTLE else QColor(Qt.transparent)
            border = th.c("control_stroke")
        elif self._variant == self.ACCENT:
            bg = th.c(
                "accent_pressed" if pressed else ("accent_hover" if hovered else "accent")
            )
        elif self._variant == self.SUBTLE:
            bg = th.c("ghost_pressed" if pressed else ("ghost_hover" if hovered else "window"))
            bg.setAlpha(0) if not (pressed or hovered) else None
        else:
            bg = th.c("control_pressed" if pressed else ("control_hover" if hovered else "control_fill"))
            border = th.c("control_stroke")

        if bg.alpha() > 0:
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(r, RADIUS_CONTROL, RADIUS_CONTROL)

        if border is not None:
            p.setPen(QPen(border, 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, RADIUS_CONTROL, RADIUS_CONTROL)
        elif self._variant == self.STANDARD and enabled:
            p.setPen(QPen(th.c("control_stroke"), 1))
            p.drawRoundedRect(r, RADIUS_CONTROL, RADIUS_CONTROL)

        if self._variant == self.ACCENT:
            fg = th.c("on_accent") if enabled else th.c("text_disabled")
        else:
            fg = th.c("text_primary") if enabled else th.c("text_disabled")

        fm = QFontMetrics(self.font())
        tw = fm.horizontalAdvance(self.text())
        iw = 16 if self._icon else 0
        gap = 8 if (iw and tw) else 0
        total = tw + iw + gap
        x = (self.width() - total) / 2
        cy = self.height() / 2

        if self._icon:
            icon_col = th.c(self._icon_token) if self._icon_token and enabled else fg
            glyphs.paint(p, self._icon, QRectF(x, cy - 8, 16, 16), icon_col)
            x += iw + gap
        if tw:
            p.setFont(self.font())
            p.setPen(fg)
            p.drawText(
                QRectF(x, 0, tw + 2, self.height()),
                int(Qt.AlignVCenter | Qt.AlignLeft),
                self.text(),
            )

        if self.hasFocus() and self._kb_focus:
            ring = th.c("on_accent") if self._variant == self.ACCENT else th.c("text_primary")
            p.setPen(QPen(ring, 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1.5, 1.5, -1.5, -1.5), RADIUS_CONTROL - 1, RADIUS_CONTROL - 1)
        p.end()


class IconButton(FluentButton):
    """正方形纯图标按钮。"""

    def __init__(self, icon: str, parent: QWidget | None = None, *, size: int = 32,
                 variant: str = "subtle", tooltip: str = "", icon_token: str | None = None):
        super().__init__("", parent, variant=variant, icon=icon, icon_token=icon_token, height=size)
        self._pad = 0
        self.setFixedSize(size, size)
        if tooltip:
            self.setToolTip(tooltip)

    def sizeHint(self) -> QSize:
        return QSize(self.height(), self.height())


class CaptionButton(QPushButton):
    """标题栏系统按钮：46×30，关闭按钮悬停变红（Win11 规范）。"""

    MIN, MAX, CLOSE, RESTORE = "min", "max", "close", "restore"

    def __init__(self, kind: str, parent: QWidget | None = None):
        super().__init__("", parent)
        self._kind = kind
        self._hover = False
        self._down = False
        self.setFixedSize(CAPTION_BUTTON_WIDTH, TITLEBAR_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.retranslate()

    def retranslate(self) -> None:
        """切界面语言后重设提示文字。"""
        key = {
            "min": "bar.min", "max": "bar.max",
            "restore": "bar.restore", "close": "bar.close",
        }.get(self._kind)
        if key:
            self.setToolTip(i18n.t(key))

    def set_hover(self, hover: bool) -> None:
        """最大化按钮走 HTMAXBUTTON（为了贴靠布局），Qt 收不到 hover 事件，
        由主窗口的高亮轮询调用这里。"""
        if hover != self._hover:
            self._hover = hover
            self.update()

    def set_kind(self, kind: str) -> None:
        self._kind = kind
        self.retranslate()
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self._down = False
        self.update()

    def mousePressEvent(self, e):
        self._down = e.button() == Qt.LeftButton
        self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._down = False
        self.update()
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        th = _theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        is_close = self._kind == self.CLOSE
        if self._down and (self._hover or is_close):
            bg = th.c("close_pressed") if is_close else th.c("ghost_pressed")
        elif self._hover:
            bg = th.c("close_hover") if is_close else th.c("ghost_hover")
        else:
            bg = QColor(Qt.transparent)
        if bg.alpha() > 0:
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRect(self.rect())
        fg = QColor("#FFFFFFFF") if (is_close and self._hover) else th.c("text_secondary")
        glyphs.paint(p, self._kind, QRectF(0, 0, 10, 10).translated(
            (self.width() - 10) / 2, (self.height() - 10) / 2), fg, 1.0)
        p.end()


# ------------------------------------------------------------------ 容器


class Card(QFrame):
    """Fluent 卡片：LayerFill 底色 + 1px 描边 + 8px 圆角。"""

    def __init__(self, parent: QWidget | None = None, *, radius: int = RADIUS_CARD, alt: bool = False):
        super().__init__(parent)
        self._radius = radius
        self._alt = alt
        self.setAttribute(Qt.WA_StyledBackground, False)

    def paintEvent(self, e):
        th = _theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(th.c("layer_stroke"), 1))
        p.setBrush(th.c("layer_alt" if self._alt else "layer"))
        p.drawRoundedRect(r, self._radius, self._radius)
        p.end()


class Divider(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), _fill("divider"))
        p.end()


# ------------------------------------------------------------------ 文本编辑


class FluentTextEdit(QPlainTextEdit):
    """Win11 文本输入框：4px 圆角、ControlFill 底色、聚焦时强调色描边。

    另外承载「朗读跟随高亮」：播放时把正在读的那句铺一层强调色，并自动滚到
    可见区（不移动光标，用户的选择和光标位置都不受影响）。
    """

    # 右键菜单交给主窗口画：Qt 内置菜单的英文条目没法跟随本项目的语言设置，
    # 而 QPlainTextEdit 自带的菜单样式也和自绘的这套控件断层。
    menu_requested = Signal(QPoint)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFont(ui_font(14))
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTabChangesFocus(True)
        self._running_span: tuple[int, int] | None = None
        self.apply_theme()

    def contextMenuEvent(self, e):
        self.menu_requested.emit(e.globalPos())

    def apply_theme(self) -> None:
        th = _theme()
        pal = self.palette()
        pal.setColor(QPalette.PlaceholderText, th.c("text_tertiary"))
        pal.setColor(QPalette.Text, th.c("text_primary"))
        pal.setColor(QPalette.Base, QColor(Qt.transparent))
        self.setPalette(pal)
        self.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background: {th.qss('editor_bg')};
                border: 1px solid {th.qss('control_stroke')};
                border-radius: {RADIUS_CONTROL}px;
                padding: 6px 2px 6px 10px;
                color: {th.qss('text_primary')};
                selection-background-color: {th.qss('accent')};
                selection-color: {th.qss('on_accent')};
            }}
            QPlainTextEdit:focus {{
                border: 1px solid {th.qss('accent')};
            }}
            QScrollBar:vertical {{
                background: transparent; width: 10px; margin: 4px 2px 4px 0;
            }}
            QScrollBar::handle:vertical {{
                background: {th.qss('text_tertiary', 0.5)};
                border-radius: 2px; min-height: 28px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {th.qss('text_secondary', 0.7)};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
            """
        )
        # 主题切换后高亮底色要跟着换（强调色本身是随主题变的）
        self.set_running_highlight(self._running_span)

    # -- 朗读跟随 --------------------------------------------------------

    def set_running_highlight(self, span: tuple[int, int] | None) -> None:
        """给「正在朗读」的那一段铺底色；传 None 清掉。

        用 ExtraSelection 而不是直接改字符格式：正文内容一个字节都不会被改动，
        undo 栈、字数统计、用户自己的选择都不受影响。
        """
        self._running_span = span
        if not span:
            self.setExtraSelections([])
            return
        doc = self.document()
        doc_len = max(0, doc.characterCount() - 1)
        a = max(0, min(int(span[0]), doc_len))
        b = max(a, min(int(span[1]), doc_len))
        if a == b:
            self.setExtraSelections([])
            return
        cursor = QTextCursor(doc)
        cursor.setPosition(a)
        cursor.setPosition(b, QTextCursor.KeepAnchor)
        fmt = QTextCharFormat()
        # 比 accent_subtle 再浓一点：字幕式高亮要一眼能看出「读到这儿了」，
        # 而 18% 的强调色在白底上几乎看不出来（Edge 的「朗读」也偏浓）。
        bg = QColor(_theme().c("accent_subtle"))
        if bg.alpha() < 0x38:
            bg.setAlpha(0x38)
        fmt.setBackground(bg)
        sel = QTextEdit.ExtraSelection()
        sel.cursor = cursor
        sel.format = fmt
        self.setExtraSelections([sel])

    def reveal_position(self, pos: int, margin: int = 24) -> None:
        """把某个字符位置滚进可视区（不改光标、不改选择）。

        QPlainTextEdit 的竖向滚动条按像素计数，而 cursorRect 也给视口像素，
        两边可以直接相加；已经在可视区里就什么都不做，避免每句话都硬滚一下。
        """
        doc = self.document()
        limit = max(0, doc.characterCount() - 1)
        cursor = QTextCursor(doc)
        cursor.setPosition(max(0, min(int(pos), limit)))
        rect = self.cursorRect(cursor)
        vp = self.viewport().rect()
        bar = self.verticalScrollBar()
        if rect.top() - margin < vp.top():
            bar.setValue(bar.value() + (rect.top() - margin - vp.top()))
        elif rect.bottom() + margin > vp.bottom():
            bar.setValue(bar.value() + (rect.bottom() + margin - vp.bottom()))


# ------------------------------------------------------------------ 单行输入


class FluentInput(QLineEdit):
    """Win11 单行输入：32px 高、ControlFill 底色、聚焦时强调色描边。

    和下拉框同一套观感，左右内边距 10px（不用 QLineEdit 的 action，
    免得像以前的搜索框那样硬留 30px 图标位）。
    """

    def __init__(self, placeholder: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self.setFont(ui_font(13))
        self.setPlaceholderText(placeholder)
        self.setTextMargins(10, 0, 10, 0)
        self.apply_theme()

    def apply_theme(self) -> None:
        th = _theme()
        pal = self.palette()
        pal.setColor(QPalette.PlaceholderText, th.c("text_tertiary"))
        pal.setColor(QPalette.Text, th.c("text_primary"))
        pal.setColor(QPalette.Base, QColor(Qt.transparent))
        self.setPalette(pal)
        self.setStyleSheet(
            f"""
            QLineEdit {{
                background: {th.qss('control_fill')};
                border: 1px solid {th.qss('control_stroke')};
                border-radius: {RADIUS_CONTROL}px;
                padding: 0;
                color: {th.qss('text_primary')};
                selection-background-color: {th.qss('accent')};
                selection-color: {th.qss('on_accent')};
            }}
            QLineEdit:hover {{
                background: {th.qss('control_hover')};
            }}
            QLineEdit:focus {{
                background: {th.qss('control_fill')};
                border: 1px solid {th.qss('accent')};
            }}
            QLineEdit:disabled {{
                color: {th.qss('text_disabled')};
            }}
            """
        )
        self.update()


# ------------------------------------------------------------------ 下拉框


class _ComboDelegate(QStyledItemDelegate):
    """下拉列表条目代理：自己画悬停底色与文字，不跟随系统调色板。"""

    PAD_X = 12

    def sizeHint(self, option, index) -> QSize:
        fm = QFontMetrics(option.font)
        text = str(index.data(Qt.DisplayRole) or "")
        return QSize(fm.horizontalAdvance(text) + 2 * self.PAD_X, 32)

    def paint(self, painter, option, index):
        p = painter
        th = _theme()
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(option.rect).adjusted(2.0, 1.0, -2.0, -1.0)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hovered:
            p.setPen(Qt.NoPen)
            p.setBrush(th.c("accent_subtle") if selected else th.c("ghost_hover"))
            p.drawRoundedRect(r, RADIUS_CONTROL, RADIUS_CONTROL)

        text = str(index.data(Qt.DisplayRole) or "")
        x = r.x() + self.PAD_X
        avail = max(1, int(r.width()) - 2 * self.PAD_X)
        f = option.font
        p.setFont(f)
        fm = QFontMetrics(f)
        p.setPen(th.c("text_primary"))
        p.drawText(
            QRectF(x, r.y(), avail, r.height()),
            int(Qt.AlignVCenter | Qt.AlignLeft),
            fm.elidedText(text, Qt.ElideRight, avail),
        )
        p.restore()


class FluentComboBox(QComboBox):
    """自绘 Win11 下拉框，弹出列表样式由 QSS 控制。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._hover = False
        self._down = False
        self._popup_filtered = None
        self.setFixedHeight(32)
        self.setFont(ui_font(14))
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        view = QListView()
        view.setFrameShape(QFrame.NoFrame)
        view.setUniformItemSizes(True)
        view.setTextElideMode(Qt.ElideRight)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        view.setMouseTracking(True)  # 自绘代理要靠 State_MouseOver 画悬停底色
        self.setView(view)
        self.setItemDelegate(_ComboDelegate(self))
        view.setItemDelegate(_ComboDelegate(view))
        self.setMaxVisibleItems(16)
        self.apply_theme()

    # -- 事件 --------------------------------------------------------
    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        self._down = True
        self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._down = False
        self.update()
        super().mouseReleaseEvent(e)

    def hidePopup(self):
        super().hidePopup()
        self._down = False
        self.update()

    def showPopup(self) -> None:
        super().showPopup()
        self._style_popup()  # 弹层容器此刻才创建，补一次样式
        self.view().window().update()

    def eventFilter(self, obj, ev):
        """自己画弹层底：半透明窗口里 QSS background 不生效，只能手绘圆角底色。"""
        if obj is self.view().window() and ev.type() == QEvent.Type.Paint:
            th = _theme()
            p = QPainter(obj)
            p.setRenderHint(QPainter.Antialiasing, True)
            r = QRectF(obj.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            p.setPen(QPen(th.c("layer_stroke"), 1))
            p.setBrush(th.c("layer"))
            p.drawRoundedRect(r, RADIUS_WINDOW, RADIUS_WINDOW)
            p.end()
            return False  # 继续正常绘制，子控件（列表）随后画在上面
        return super().eventFilter(obj, ev)

    # -- 样式 --------------------------------------------------------
    def apply_theme(self) -> None:
        th = _theme()
        pal = self.palette()
        pal.setColor(QPalette.Text, th.c("text_primary"))
        self.setPalette(pal)
        self.setFont(self.font())
        self._style_popup()

    def _style_popup(self) -> None:
        """弹层是自己的顶层窗口，必须显式给不透明底色 + 圆角，否则跟随系统调色板。"""
        th = _theme()
        pop = self.view().window()
        if pop is self.view():
            return  # 弹层容器还没创建，等 showPopup 时再补
        pop.setObjectName("comboPopup")
        pop.setAttribute(Qt.WA_TranslucentBackground, True)
        pop.setStyleSheet("#comboPopup { background: transparent; border: none; }")
        if self._popup_filtered is not pop:
            pop.installEventFilter(self)
            self._popup_filtered = pop
        # 弹层视图的调色板也跟上主题，避免 Qt 默认样式在选区/焦点上插入杂色
        view = self.view()
        vpal = view.palette()
        vpal.setColor(QPalette.Base, th.c("layer"))
        vpal.setColor(QPalette.Text, th.c("text_primary"))
        vpal.setColor(QPalette.Highlight, th.c("accent_subtle"))
        vpal.setColor(QPalette.HighlightedText, th.c("text_primary"))
        view.setPalette(vpal)
        view.setStyleSheet(
            f"""
            QListView {{
                background: transparent;
                border: none;
                padding: 4px;
                outline: none;
            }}
            QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
            QScrollBar::handle:vertical {{
                background: {th.qss('text_tertiary', 0.5)};
                border-radius: 2px; min-height: 24px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
            """
        )
        view.viewport().setStyleSheet("background: transparent;")

    # -- 绘制 --------------------------------------------------------
    def paintEvent(self, e):
        th = _theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        enabled = self.isEnabled()
        active = self._hover or self._down or self.hasFocus()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        fill_key = "control_pressed" if self._down else ("control_hover" if (self._hover and enabled) else "control_fill")
        p.setPen(QPen(th.c("accent") if self.hasFocus() else th.c("control_stroke"), 1))
        p.setBrush(th.c(fill_key) if enabled else th.c("control_fill"))
        p.drawRoundedRect(r, RADIUS_CONTROL, RADIUS_CONTROL)

        glyphs.paint(
            p, "chevron_down",
            QRectF(self.width() - 28, (self.height() - 14) / 2, 14, 14),
            th.c("text_secondary") if active else th.c("text_tertiary"),
            1.2,
        )

        fm = QFontMetrics(self.font())
        left = 12
        text = fm.elidedText(self.currentText(), Qt.ElideRight, self.width() - left - 32)
        p.setFont(self.font())
        p.setPen(th.c("text_primary") if enabled else th.c("text_disabled"))
        p.drawText(QRectF(left, 0, self.width() - left - 32, self.height()), int(Qt.AlignVCenter | Qt.AlignLeft), text)
        p.end()


# ------------------------------------------------------------------ 滑块


class FluentSlider(QWidget):
    """WinUI 3 滑块：细轨道 + 圆环式拇指，悬停放大。"""

    valueChanged = Signal(int)
    committed = Signal(int)

    def __init__(self, minimum: int = 0, maximum: int = 100, value: int = 0, parent: QWidget | None = None):
        super().__init__(parent)
        self._min = minimum
        self._max = max(maximum, minimum + 1)
        self._v = max(minimum, min(value, self._max))
        self._hover = False
        self._dragging = False
        self.setFixedHeight(30)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)

    # -- 值 ----------------------------------------------------------
    def value(self) -> int:
        return self._v

    def setValue(self, value: int) -> None:
        v = int(max(self._min, min(value, self._max)))
        if v == self._v:
            return
        self._v = v
        self.update()
        self.valueChanged.emit(v)

    def minimum(self) -> int:
        return self._min

    def maximum(self) -> int:
        return self._max

    def setRange(self, minimum: int, maximum: int) -> None:
        self._min = minimum
        self._max = max(maximum, minimum + 1)
        self.setValue(self._v)
        self.update()

    # -- 几何 --------------------------------------------------------
    def _thumb_d(self) -> float:
        return 14.0

    def _track(self) -> QRectF:
        d = self._thumb_d()
        return QRectF(d / 2 + 2, self.height() / 2 - 2, self.width() - d - 4, 4)

    def _thumb_center(self) -> QPointF:
        t = self._track()
        ratio = (self._v - self._min) / (self._max - self._min)
        return QPointF(t.left() + t.width() * ratio, self.height() / 2)

    def _set_from_x(self, x: float) -> None:
        t = self._track()
        ratio = (x - t.left()) / max(t.width(), 1)
        ratio = max(0.0, min(1.0, ratio))
        self.setValue(round(self._min + ratio * (self._max - self._min)))

    # -- 事件 --------------------------------------------------------
    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self._dragging = True
            self.setFocus(Qt.MouseFocusReason)
            self._set_from_x(e.position().x())
            self.update()

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._dragging:
            self._set_from_x(e.position().x())

    def mouseReleaseEvent(self, e: QMouseEvent):
        if self._dragging:
            self._dragging = False
            self.update()
            self.committed.emit(self._v)

    def wheelEvent(self, e: QWheelEvent):
        step = 5 if e.modifiers() & Qt.ShiftModifier else 1
        self.setValue(self._v + (step if e.angleDelta().y() > 0 else -step))
        self.committed.emit(self._v)
        e.accept()

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Home, Qt.Key_End):
            if e.key() == Qt.Key_Home:
                self.setValue(self._min)
            elif e.key() == Qt.Key_End:
                self.setValue(self._max)
            else:
                self.setValue(self._v + (-1 if e.key() == Qt.Key_Left else 1))
            self.committed.emit(self._v)
            e.accept()
            return
        super().keyPressEvent(e)

    # -- 绘制 --------------------------------------------------------
    def paintEvent(self, e):
        th = _theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        enabled = self.isEnabled()
        track = self._track()
        groove = th.c("text_tertiary")
        groove.setAlphaF(0.42 if enabled else 0.2)
        p.setPen(Qt.NoPen)
        p.setBrush(groove)
        p.drawRoundedRect(track, 2, 2)

        c = self._thumb_center()
        filled = QRectF(track.left(), track.top(), c.x() - track.left(), track.height())
        if filled.width() > 0:
            p.setBrush(th.c("accent") if enabled else th.c("text_disabled"))
            p.drawRoundedRect(filled, 2, 2)

        d = self._thumb_d() + (2.0 if (self._hover or self._dragging) else 0.0)
        outer = QRectF(c.x() - d / 2, c.y() - d / 2, d, d)
        p.setBrush(th.c("control_fill") if enabled else th.c("window"))
        p.setPen(QPen(th.c("stroke_strong") if enabled else th.c("control_stroke"), 1))
        p.drawEllipse(outer)
        inner = 4.0 if (self._hover or self._dragging) else 3.2
        p.setPen(Qt.NoPen)
        p.setBrush(th.c("accent") if enabled else th.c("text_tertiary"))
        p.drawEllipse(c, inner, inner)
        p.end()


# ------------------------------------------------------------------ 进度条

class FluentProgressBar(QWidget):
    """4px 细进度条，支持确定与不确定（脉冲）两种模式。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._value = 0
        self._indeterminate = False
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self.setFixedHeight(4)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def setValue(self, value: float) -> None:
        v = max(0.0, min(100.0, float(value)))
        if abs(v - self._value) < 0.01:
            return
        self._value = v
        self.update()

    def value(self) -> float:
        return self._value

    def setIndeterminate(self, on: bool) -> None:
        if on == self._indeterminate:
            return
        self._indeterminate = on
        self._phase = 0.0
        if on:
            self._timer.start()
        else:
            self._timer.stop()
        if not on:
            self._value = 0.0
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.022) % 1.0
        self.update()

    def paintEvent(self, e):
        th = _theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        bg = th.c("text_tertiary")
        bg.setAlphaF(0.35)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(self.rect()), 2, 2)
        p.setBrush(th.c("accent"))
        if self._indeterminate:
            w = self.width()
            pill = max(w * 0.32, 40)
            # 用 cos 缓动让脉冲两端减速，接近 WinUI 不确定进度条手感
            eased = 0.5 - 0.5 * __import__("math").cos(self._phase * 6.283185)
            x = eased * (w - pill)
            p.drawRoundedRect(QRectF(x, 0, pill, self.height()), 2, 2)
        else:
            w = self.width() * self._value / 100.0
            if w > 0:
                p.drawRoundedRect(QRectF(0, 0, w, self.height()), 2, 2)
        p.end()

    @property
    def indeterminate(self) -> bool:
        return self._indeterminate


# ------------------------------------------------------------------ 复选框


class FluentCheckBox(QWidget):
    """WinUI 3 复选框：18px 圆角方框，勾选时强调色填充 + 白色对勾。"""

    toggled = Signal(bool)

    def __init__(self, text: str = "", parent: QWidget | None = None, *, checked: bool = False):
        super().__init__(parent)
        self._checked = bool(checked)
        self._hover = False
        self._kb_focus = False
        self._text = text
        self.setFont(ui_font(13))
        self.setFixedHeight(26)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    # -- 状态 ---------------------------------------------------------
    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = text
        self.updateGeometry()
        self.update()

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, *, emit: bool = False) -> None:
        if bool(checked) == self._checked:
            return
        self._checked = bool(checked)
        self.update()
        if emit:
            self.toggled.emit(self._checked)

    def toggle(self) -> None:
        self.setChecked(not self._checked, emit=True)

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        return QSize(18 + 8 + fm.horizontalAdvance(self._text) + 6, self.height())

    # -- 事件 --------------------------------------------------------
    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.setFocus(Qt.MouseFocusReason)
            self.toggle()

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.toggle()
            e.accept()
            return
        super().keyPressEvent(e)

    def focusInEvent(self, e):
        self._kb_focus = e.reason() not in (
            Qt.MouseFocusReason,
            Qt.PopupFocusReason,
            Qt.ActiveWindowFocusReason,
        )
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self._kb_focus = False
        self.update()
        super().focusOutEvent(e)

    # -- 绘制 --------------------------------------------------------
    def paintEvent(self, e):
        th = _theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        enabled = self.isEnabled()
        box = QRectF(0.5, (self.height() - 18) / 2, 17, 17)

        if self._checked:
            p.setPen(Qt.NoPen)
            p.setBrush(th.c("accent") if enabled else th.c("text_tertiary"))
        else:
            p.setPen(QPen(th.c("control_stroke"), 1))
            p.setBrush(th.c("control_hover") if (self._hover and enabled) else th.c("control_fill"))
        p.drawRoundedRect(box, 4, 4)

        if self._checked:
            glyphs.paint(p, "check", box, th.c("on_accent") if enabled else th.c("window"), 1.9)

        p.setFont(self.font())
        p.setPen(th.c("text_primary") if enabled else th.c("text_disabled"))
        p.drawText(
            QRectF(26, 0, self.width() - 26, self.height()),
            int(Qt.AlignVCenter | Qt.AlignLeft),
            self._text,
        )

        if self.hasFocus() and self._kb_focus:
            p.setPen(QPen(th.c("text_primary"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 4, 4)
        p.end()


# ------------------------------------------------------------------ 状态栏


class ScrollableStatus(QScrollArea):
    """单行状态栏。

    长错误不再被窗口边缘直接截断：内容超出时可横向滚动，把鼠标滚轮上下滚
    也能左右拖动，文字还能选中复制。
    """

    HEIGHT = 26
    WHEEL_STEP = 48

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setWidgetResizable(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedHeight(self.HEIGHT)

        self._text = ""
        self._color = _theme().qss("text_secondary")

        self._label = QLabel("", self)
        self._label.setFont(ui_font(12))
        self._label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setWidget(self._label)
        self.apply_theme()

    # -- 内容 --------------------------------------------------------
    def text(self) -> str:
        return self._text

    def set_message(self, text: str, color: str | None = None) -> None:
        self._text = text
        if color:
            self._color = color
        self._label.setText(text)
        self._label.setStyleSheet(f"color: {self._color}; background: transparent;")
        fm = QFontMetrics(self._label.font())
        width = max(1, fm.horizontalAdvance(text) + 10)
        self._label.setFixedSize(width, self.HEIGHT - 6)
        self._label.move(0, 0)
        self.setToolTip(text)
        self.horizontalScrollBar().setValue(0)  # 让开头先露出来
    # -- 样式 --------------------------------------------------------
    def apply_theme(self) -> None:
        th = _theme()
        self.setStyleSheet(
            f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:horizontal {{ background: transparent; height: 6px; margin: 0; }}
            QScrollBar::handle:horizontal {{
                background: {th.qss('text_tertiary', 0.55)};
                border-radius: 3px; min-width: 28px;
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
            """
        )
        self._label.setStyleSheet(f"color: {self._color}; background: transparent;")

    # -- 事件 --------------------------------------------------------
    def wheelEvent(self, e: QWheelEvent):
        bar = self.horizontalScrollBar()
        if bar.maximum() > 0:
            delta = e.angleDelta().y() or e.angleDelta().x()
            bar.setValue(bar.value() - int(delta / 120 * self.WHEEL_STEP))
            e.accept()
            return
        e.ignore()
