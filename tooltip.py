"""窗口内自绘的工具提示（替代 Qt 的 QToolTip）。

为什么不用 Qt 自带的：在本程序这扇「自绘 + 原生框架」的主窗口里，QToolTip
弹出来之后底色一个像素都不画 —— 屏幕上只剩一块纯黑、文字也看不见（抓图实测
不透明像素只占 7%）。同一段样式在朴素窗口里正常，逐条改 QSS 属性也无效；
改成把样式直接写在 QTipLabel 自己身上又恢复 100%，说明是 QToolTip 顶层窗口
在这套窗口样式下画不出背景，而那是 Qt 内部细节，改不动。

所以这里彻底绕开 QToolTip：拦截 QEvent.ToolTip，在窗口里画一个气泡（圆角、
细边、软阴影、跟随光标），不抢焦点也不吃鼠标。观感与 Win11 的浅色气泡一致，
而且完全由本程序绘制，不会再出现黑块。
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QCursor, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

from theme import RADIUS_CONTROL, tm, ui_font


class TipBubble(QWidget):
    """提示气泡本体。要画阴影，所以卡片本体在 SHADOW 以内。"""

    SHADOW = 5
    PAD_X = 10
    PAD_Y = 7
    MAX_TEXT_WIDTH = 340
    """正文最大宽度（逻辑像素）。超了折行，跟 Win11 一样不会横到屏幕外。"""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAutoFillBackground(False)
        self._text = ""
        self._font = ui_font(13)
        self.hide()

    # -- 内容与尺寸 --------------------------------------------------
    def set_text(self, text: str) -> None:
        self._text = text
        fm = QFontMetricsF(self._font)
        limit = self.MAX_TEXT_WIDTH
        one_line = fm.horizontalAdvance(text)
        if one_line <= limit:
            w = one_line
            h = fm.lineSpacing()
        else:
            box = fm.boundingRect(
                QRectF(0, 0, limit, 1e6),
                int(Qt.TextWordWrap | Qt.AlignLeft),
                text,
            )
            w = min(limit, box.width())
            h = box.height()
        self.resize(
            int(w) + 2 * self.PAD_X + 2 * self.SHADOW,
            int(h) + 2 * self.PAD_Y + 2 * self.SHADOW,
        )
        self.update()

    def apply_theme(self) -> None:
        self._font = ui_font(13)
        self.update()

    # -- 绘制 --------------------------------------------------------
    def paintEvent(self, e) -> None:  # noqa: N802 (Qt 命名)
        th = tm().theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        body = QRectF(self.rect()).adjusted(
            self.SHADOW, self.SHADOW, -self.SHADOW, -self.SHADOW
        )

        # 软阴影：由外到内几层渐深的圆角（子控件没有 DWM 阴影，只能自己画）
        for i in range(4, 0, -1):
            col = th.c("shadow")
            col.setAlpha(int(24 * (5 - i) / 4))
            path = QPainterPath()
            path.addRoundedRect(
                body.adjusted(-i, -i, i, i),
                RADIUS_CONTROL + i + 1,
                RADIUS_CONTROL + i + 1,
            )
            p.fillPath(path, col)

        path = QPainterPath()
        path.addRoundedRect(body, RADIUS_CONTROL + 2, RADIUS_CONTROL + 2)
        p.fillPath(path, th.c("layer"))
        pen = QPen(th.c("layer_stroke"))
        pen.setWidth(1)
        p.setPen(pen)
        p.drawPath(path)

        p.setFont(self._font)
        p.setPen(QPen(th.c("text_primary")))
        p.drawText(
            body.adjusted(self.PAD_X, self.PAD_Y, -self.PAD_X, -self.PAD_Y),
            int(Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter),
            self._text,
        )
        p.end()


class TipController(QObject):
    """全局接管提示框：鼠标停在带 tooltip 的控件上时画出自己的气泡。"""

    def __init__(self, app: QApplication):
        super().__init__(app)
        self._bubble: TipBubble | None = None
        self._anchor: QWidget | None = None
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(120)
        self._hide_timer.timeout.connect(self._hide_if_left)
        app.installEventFilter(self)

    # -- 事件 --------------------------------------------------------
    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt 命名)
        kind = event.type()
        if kind == QEvent.ToolTip:
            text = obj.toolTip() if hasattr(obj, "toolTip") else ""
            self._hide_timer.stop()
            if text:
                pos = event.globalPos() if hasattr(event, "globalPos") else QCursor.pos()
                self._show(obj, text, pos)
                return True  # 吃掉事件：QToolTip 弹出来就是黑块，不能让它画
            return False

        if kind == QEvent.Show and "QTipLabel" in obj.metaObject().className():
            # 兜底：万一有哪条路径绕过了上面的拦截，也让那块黑框压根不显示
            obj.hide()
            return True

        if kind in (
            QEvent.Leave,
            QEvent.Hide,
            QEvent.WindowDeactivate,
            QEvent.MouseButtonPress,
            QEvent.Wheel,
            QEvent.KeyPress,
        ):
            # 移开时先等一拍：鼠标在组合控件内部换子控件也会发 Leave
            self._hide_timer.start()
        return False

    def _hide_if_left(self) -> None:
        if self._anchor is not None:
            w = QApplication.widgetAt(QCursor.pos())
            while w is not None:
                if w is self._anchor:
                    return
                w = w.parentWidget()
        self.hide()

    # -- 显示 --------------------------------------------------------
    def _parent_for(self, widget: QWidget) -> QWidget | None:
        win = widget.window()
        if win is not None and not win.isHidden() and not (win.windowFlags() & Qt.Popup):
            return win
        return QApplication.activeWindow()

    def _show(self, widget: QWidget, text: str, global_pos: QPoint) -> None:
        parent = self._parent_for(widget)
        if parent is None:
            return
        if self._bubble is None or self._bubble.parent() != parent:
            self._bubble = TipBubble(parent)
        b = self._bubble
        b.apply_theme()
        b.set_text(text)
        cursor = parent.mapFromGlobal(global_pos)
        x = cursor.x() + 12
        y = cursor.y() + 20
        # 贴窗口右下时翻到光标上方/左侧，别被窗口边裁掉
        if x + b.width() > parent.width() - 4:
            x = cursor.x() - b.width() - 8
        if y + b.height() > parent.height() - 4:
            y = cursor.y() - b.height() - 12
        x = max(4, min(x, parent.width() - b.width() - 4))
        y = max(4, min(y, parent.height() - b.height() - 4))
        b.move(QPoint(int(x), int(y)))
        b.show()
        b.raise_()
        self._anchor = widget

    def hide(self) -> None:
        self._hide_timer.stop()
        self._anchor = None
        if self._bubble is not None:
            self._bubble.hide()

    def restyle(self) -> None:
        if self._bubble is not None:
            self._bubble.apply_theme()


def install(app: QApplication) -> TipController:
    """装好提示框接管；主题切换时由调用方调 restyle 重新配色。"""
    return TipController(app)
