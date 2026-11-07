"""窗口内自绘菜单（右键菜单 / 界面语言菜单）。

不用 QMenu：Qt 的菜单在这扇「自绘 + 原生框架」窗口里会跟随系统调色板，样式和
其它控件断层；窗口内子控件还能沿用项目里已经调好的圆角、阴影与强调色。

菜单本身只负责排版与交互，具体条目由调用方给（含快捷键文字、勾选状态）。
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

from theme import RADIUS_CARD, tm, ui_font
from glyphs import pixmap as glyph_pixmap

PAD = 8               # 画阴影要留的边距
ITEM_H = 32
SEP_H = 9
TITLE_H = 30
MIN_W = 168
TEXT_PAD = 12
CHECK_W = 22
SHORTCUT_GAP = 28


class MenuItem:
    __slots__ = ("key", "text", "shortcut", "enabled", "checked", "kind")

    def __init__(self, key: str, text: str, *, shortcut: str = "",
                 enabled: bool = True, checked: bool = False,
                 kind: str = "item"):
        self.key = key
        self.text = text
        self.shortcut = shortcut
        self.enabled = enabled
        self.checked = checked
        self.kind = kind        # item / separator / title

    @classmethod
    def separator(cls) -> "MenuItem":
        return cls("", "", kind="separator")

    @classmethod
    def title(cls, text: str) -> "MenuItem":
        return cls("", text, kind="title")


class FluentMenu(QWidget):
    """贴在锚点（按钮/光标）旁边展开的菜单；点条目或点外面即关闭。"""

    triggered = Signal(str)
    closed = Signal()   # 菜单收起（点条目、Esc、点外面都算），宿主用来撤销按钮按下态

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.StrongFocus)
        self._items: list[MenuItem] = []
        self._hover = -1
        self._press = -1
        self._app_filter = False
        self._anchor: QWidget | None = None   # 哪个按钮把菜单开出来的（再点它 = 收起）
        self.hide()

    # -- 数据 --------------------------------------------------------
    def set_items(self, items: list[MenuItem]) -> None:
        self._items = list(items)
        self._hover = -1
        self._resize_to_fit()
        self.update()

    def _resize_to_fit(self) -> None:
        fm_text = QFontMetrics(ui_font(13))
        fm_meta = QFontMetrics(ui_font(11))
        width = MIN_W
        for it in self._items:
            if it.kind == "title":
                w = fm_meta.horizontalAdvance(it.text) + TEXT_PAD * 2
            elif it.kind == "item":
                left = TEXT_PAD + (CHECK_W if it.checked else 0)
                w = left + fm_text.horizontalAdvance(it.text) + TEXT_PAD
                if it.shortcut:
                    w += SHORTCUT_GAP + fm_meta.horizontalAdvance(it.shortcut)
            else:
                w = MIN_W
            width = max(width, w)
        width += PAD * 2   # 上面算的是卡片内容宽度，几何尺寸还要留出阴影的留白
        height = PAD * 2 + sum(
            ITEM_H if it.kind == "item" else (SEP_H if it.kind == "separator" else TITLE_H)
            for it in self._items
        )
        self.setFixedSize(width, height)

    # -- 布局 --------------------------------------------------------
    def _rows(self) -> list[tuple[MenuItem, int, int]]:
        """返回 [(条目, 顶部 y, 高度)]，y 相对窗口（含 PAD 偏移）。"""
        out = []
        y = PAD
        for it in self._items:
            h = ITEM_H if it.kind == "item" else (SEP_H if it.kind == "separator" else TITLE_H)
            out.append((it, y, h))
            y += h
        return out

    def _item_at(self, pos: QPoint) -> int:
        for i, (it, y, h) in enumerate(self._rows()):
            if it.kind != "item":
                continue
            if y <= pos.y() < y + h:
                return i
        return -1

    # -- 展开 --------------------------------------------------------
    def open_at_global(self, gpos: QPoint) -> None:
        """右键：可见卡片的左上角贴住光标（几何还含 PAD 的阴影留白）。"""
        parent = self.parentWidget()
        if parent is None:
            return
        local = parent.mapFromGlobal(gpos)
        w, h = self.width(), self.height()
        x, y = local.x() - PAD, local.y() - PAD
        if x + w > parent.width() - 8:
            x = local.x() - w + PAD
        if y + h > parent.height() - 8:
            y = local.y() - h + PAD
        x = max(8, min(x, parent.width() - w - 8))
        y = max(8, min(y, parent.height() - h - 8))
        self.move(x, y)
        self._show()

    def open_below(self, anchor: QWidget) -> None:
        """在控件下方展开、右边缘对齐；下面放不下就翻到上方。"""
        parent = self.parentWidget()
        if parent is None or anchor is None:
            return
        w, h = self.width(), self.height()
        br = anchor.mapTo(parent, QPoint(anchor.width(), anchor.height()))
        tl = anchor.mapTo(parent, QPoint(0, 0))
        # 可见卡片的右缘对齐按钮右缘、上缘离按钮 4px（PAD 是阴影留白）
        x = br.x() - w + PAD
        y = br.y() + 4 - PAD
        if y + h + 8 > parent.height():
            y = tl.y() - h + PAD - 4
        x = max(8, min(x, parent.width() - w - 8))
        y = max(8, min(y, parent.height() - h - 8))
        self.move(x, y)
        self._anchor = anchor
        self._show()

    def _show(self) -> None:
        self.show()
        self.raise_()
        self.setFocus(Qt.PopupFocusReason)
        if not self._app_filter:
            QApplication.instance().installEventFilter(self)
            self._app_filter = True

    def close_menu(self) -> None:
        if self._app_filter:
            QApplication.instance().removeEventFilter(self)
            self._app_filter = False
        self._anchor = None
        self.hide()

    # -- 交互 --------------------------------------------------------
    def eventFilter(self, obj, e) -> bool:
        if not self.isVisible():
            return False
        if e.type() == QEvent.MouseButtonPress:
            gpos = e.globalPosition().toPoint() if hasattr(e, "globalPosition") else None
            if gpos is not None and not self.rect().contains(self.mapFromGlobal(gpos)):
                # 落在「开菜单的那个按钮」上时不关：留给按钮自己 toggle，
                # 否则点一下会「关了又开」，看起来像按钮没反应。
                if self._anchor is not None:
                    r = QRect(self._anchor.mapToGlobal(QPoint(0, 0)), self._anchor.size())
                    if r.contains(gpos):
                        return False
                self.close_menu()
        elif e.type() == QEvent.KeyPress and e.key() == Qt.Key_Escape:
            self.close_menu()
        return False

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close_menu()
            return
        if e.key() in (Qt.Key_Up, Qt.Key_Down):
            step = -1 if e.key() == Qt.Key_Up else 1
            idxs = [i for i, (it, _y, _h) in enumerate(self._rows()) if it.kind == "item" and it.enabled]
            if idxs:
                if self._hover in idxs:
                    pos = idxs.index(self._hover)
                    self._hover = idxs[(pos + step) % len(idxs)]
                else:
                    self._hover = idxs[0]
                self.update()
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and self._hover >= 0:
            self._activate(self._hover)
            return
        super().keyPressEvent(e)

    def _activate(self, index: int) -> None:
        if not (0 <= index < len(self._items)):
            return
        it = self._items[index]
        if it.kind != "item" or not it.enabled:
            return
        self.close_menu()
        self.triggered.emit(it.key)

    def mouseMoveEvent(self, e):
        idx = self._item_at(e.position().toPoint())
        if idx != self._hover:
            self._hover = idx
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def mousePressEvent(self, e):
        self._press = self._item_at(e.position().toPoint())
        self.update()

    def mouseReleaseEvent(self, e):
        idx = self._item_at(e.position().toPoint())
        if idx == self._press and idx >= 0:
            self._activate(idx)
        self._press = -1

    def hideEvent(self, e):
        if self._app_filter:
            QApplication.instance().removeEventFilter(self)
            self._app_filter = False
        self._hover = -1
        super().hideEvent(e)
        self.closed.emit()

    # -- 绘制 --------------------------------------------------------
    def paintEvent(self, e):
        th = tm().theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        body = QRectF(self.rect()).adjusted(PAD, PAD, -PAD, -PAD)
        shadow = QColor(th.c("shadow"))
        for i in range(5, 0, -1):
            col = QColor(shadow)
            col.setAlpha(int(26 * (6 - i) / 5))
            path = QPainterPath()
            path.addRoundedRect(body.adjusted(-i, -i, i, i), RADIUS_CARD + i, RADIUS_CARD + i)
            p.fillPath(path, col)

        card = QPainterPath()
        card.addRoundedRect(body, RADIUS_CARD, RADIUS_CARD)
        p.fillPath(card, th.c("layer"))
        p.setPen(QPen(th.c("layer_stroke"), 1))
        p.drawPath(card)

        fm_text = QFontMetrics(ui_font(13))
        fm_meta = QFontMetrics(ui_font(11))
        for i, (it, y, h) in enumerate(self._rows()):
            if it.kind == "separator":
                p.setPen(QPen(th.c("divider"), 1))
                p.drawLine(
                    int(body.left() + 8), int(y + h / 2),
                    int(body.right() - 8), int(y + h / 2),
                )
                continue
            if it.kind == "title":
                p.setFont(ui_font(11))
                p.setPen(th.c("text_tertiary"))
                p.drawText(
                    QRectF(body.left() + TEXT_PAD, y, body.width() - TEXT_PAD * 2, h),
                    int(Qt.AlignVCenter | Qt.AlignLeft), it.text,
                )
                continue

            row = QRectF(body.left() + 4, y, body.width() - 8, h)
            if i == self._hover and it.enabled:
                fill = th.c("control_fill")
                p.setPen(Qt.NoPen)
                p.setBrush(fill)
                p.drawRoundedRect(row, 4, 4)

            left = body.left() + TEXT_PAD + (CHECK_W if it.checked else 0)
            p.setFont(ui_font(13))
            p.setPen(th.c("text_primary") if it.enabled else th.c("text_disabled"))
            p.drawText(
                QRectF(left, y, body.width() - TEXT_PAD * 2, h),
                int(Qt.AlignVCenter | Qt.AlignLeft), it.text,
            )
            if it.checked:
                px = glyph_pixmap("check", th.c("accent"), 16, 2.0)
                p.drawPixmap(int(body.left() + TEXT_PAD), int(y + (h - 16) / 2), px)

            if it.shortcut:
                p.setFont(ui_font(11))
                p.setPen(th.c("text_tertiary") if it.enabled else th.c("text_disabled"))
                p.drawText(
                    QRectF(body.left(), y, body.right() - TEXT_PAD - body.left(), h),
                    int(Qt.AlignVCenter | Qt.AlignRight), it.shortcut,
                )
        p.end()
