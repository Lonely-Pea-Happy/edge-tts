"""主窗口。

界面骨架（WinUI 3 的 NavigationView 味道，但单页面）：
    标题栏（自绘，46×32 系统按钮）
    ├─ 标题 + 副标题
    ├─ 左：文本卡片（多行编辑 + 字数/时长）
    └─ 右：语音卡片（语言 / 发音人 / 语速 / 音调 / 音量 / 输出目录）
    底栏：播放条 + 进度条 + 状态 + 主操作按钮

无边框窗口的原生感来自 WM_NCHITTEST：标题栏返回 HTCAPTION，
Windows 自己负责拖动、双击最大化与 Aero Snap；八条边返回对应 HT 值实现原生缩放。
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QProcess, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QCursor,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QShortcut,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import ai_writer
import batch
import config
import follow
import glyphs
import i18n
import importer
import player as player_mod
import tts_engine
from menu import FluentMenu, MenuItem
from theme import (
    RADIUS_CARD,
    RADIUS_WINDOW,
    SHADOW_MARGIN,
    TITLEBAR_HEIGHT,
    tm,
    ui_font,
)
from widgets import (
    Card,
    CaptionButton,
    Divider,
    FluentButton,
    FluentCheckBox,
    FluentComboBox,
    FluentInput,
    FluentProgressBar,
    FluentSlider,
    FluentTextEdit,
    IconButton,
    ScrollableStatus,
)
import win_utils
import messages

F = QFont.Weight


class ElidedLabel(QLabel):
    """按宽度中间省略的文本标签（用于长路径）。"""

    def __init__(self, text: str = "", parent: QWidget | None = None, size: int = 12):
        super().__init__(text, parent)
        self._full = text
        self._color = QColor("#808080")
        self.setFont(ui_font(size))
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setFixedHeight(20)
        self.setToolTip(text)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self.update()

    def set_color(self, color: QColor) -> None:
        self._color = color
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        fm = QFontMetrics(self.font())
        text = fm.elidedText(self._full, Qt.ElideMiddle, max(self.width() - 2, 10))
        p.setPen(self._color)
        p.setFont(self.font())
        p.drawText(self.rect(), int(Qt.AlignVCenter | Qt.AlignLeft), text)
        p.end()


class _Surface(QWidget):
    """窗口的可视表面：圆角 + 底色 + 1px 描边。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.radius = RADIUS_WINDOW

    def paintEvent(self, e):
        th = tm().theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(th.c("window"))
        p.setPen(QPen(th.c("window_stroke"), 1))
        p.drawRoundedRect(r, self.radius, self.radius)
        p.end()


class _QueueRow(QWidget):
    """队列里的一行：播放按钮 + 序号 + 文本摘要 + 状态 + 移除按钮。

    播放按钮只在「这一段已经生成成功」时出现，位置固定在行首；没有按钮的行
    序号照样占同一列，避免列表看着参差不齐。
    """

    remove_clicked = Signal(int)
    play_clicked = Signal(int)

    PLAY_LEFT = 4
    PLAY_SIZE = 22
    IDX_RIGHT = 52      # 序号的右边缘
    IDX_WIDTH = 22
    TEXT_LEFT = 60

    def __init__(self, index: int, text: str, status: str = "waiting",
                 parent: QWidget | None = None, *, playable: bool = False,
                 current: bool = False, playing: bool = False):
        super().__init__(parent)
        self._index = index
        self._text = text
        self._status = status
        self._playable = playable
        self._current = current      # 播放条里放的就是这一段（铺淡底色）
        self._playing = playing      # 这一段正在出声（按钮显示暂停）
        self._hover = False
        self.setFixedHeight(30)
        self.setAttribute(Qt.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._play = IconButton("play", self, size=self.PLAY_SIZE, variant="subtle")
        self._play.clicked.connect(lambda: self.play_clicked.emit(self._index))
        self._remove = IconButton("close", self, size=22, variant="subtle",
                                  tooltip=i18n.t("queue.remove_tip"))
        self._remove.clicked.connect(lambda: self.remove_clicked.emit(self._index))
        self._sync_play()
        self._sync_remove()
        self.retranslate()

    def set_status(self, status: str) -> None:
        self._status = status
        self._sync_remove()
        self.update()

    def set_playback(self, current: bool, playing: bool) -> None:
        if (current, playing) != (self._current, self._playing):
            self._current = current
            self._playing = playing
            self._sync_play()
            self.update()

    def retranslate(self) -> None:
        self._remove.setToolTip(i18n.t("queue.remove_tip"))
        self._play.setToolTip(
            i18n.t("queue.pause_tip") if self._playing else i18n.t("queue.play_tip")
        )

    def _sync_play(self) -> None:
        self._play.setVisible(self._playable)
        self._play.set_icon("pause" if self._playing else "play",
                            "accent" if self._current else None)
        self._play.move(self.PLAY_LEFT, (self.height() - self.PLAY_SIZE) // 2)
        self._play.setToolTip(
            i18n.t("queue.pause_tip") if self._playing else i18n.t("queue.play_tip")
        )

    def _sync_remove(self) -> None:
        # 只在还没开始合成的段上允许移除，避免删掉正在跑的条目
        self._remove.setVisible(self._status == "waiting")
        self._remove.move(self.width() - 26, (self.height() - 22) // 2)

    def resizeEvent(self, e):
        self._sync_remove()
        super().resizeEvent(e)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(320, 30)

    def paintEvent(self, e):
        th = tm().theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        enabled = self.isEnabled()

        if self._current:
            # 正在播放的那一段铺一层很淡的强调色：和播放条联动时一眼能对上
            bg = QColor(th.c("accent_subtle"))
            bg.setAlpha(max(bg.alpha(), 0x24))
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0, 1, 0, -1), 4, 4)
        elif self._hover and enabled and self._status == "waiting":
            p.setPen(Qt.NoPen)
            p.setBrush(th.c("control_fill"))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0, 1, 0, -1), 4, 4)

        idx_rect = QRectF(self.IDX_RIGHT - self.IDX_WIDTH, 0, self.IDX_WIDTH, self.height())
        p.setFont(ui_font(11))
        p.setPen(th.c("text_tertiary") if enabled else th.c("text_disabled"))
        p.drawText(idx_rect, int(Qt.AlignVCenter | Qt.AlignRight), f"{self._index + 1}")

        fm = QFontMetrics(ui_font(12))
        text_rect = QRectF(
            self.TEXT_LEFT, 0, max(self.width() - self.TEXT_LEFT - 104, 20), self.height()
        )
        title = fm.elidedText(self._text, Qt.ElideRight, int(text_rect.width()))
        p.setFont(ui_font(12))
        p.setPen(th.c("text_primary") if enabled else th.c("text_disabled"))
        p.drawText(text_rect, int(Qt.AlignVCenter | Qt.AlignLeft), title)

        token = {
            "waiting": "text_tertiary",
            "running": "accent",
            "done": "text_secondary",
            "failed": "close_hover",
        }.get(self._status, "text_tertiary")
        label = i18n.t(f"queue.{self._status}") if self._status in (
            "waiting", "running", "done", "failed"
        ) else ""
        p.setFont(ui_font(11))
        p.setPen(th.c(token))
        p.drawText(
            QRectF(self.width() - 100, 0, 70, self.height()),
            int(Qt.AlignVCenter | Qt.AlignRight),
            label,
        )
        p.end()


class _QueuePanel(QWidget):
    """队列面板：标题统计 + 可滚动的行列表 + 清空。"""

    remove_requested = Signal(int)
    clear_requested = Signal()
    play_requested = Signal(int)

    MAX_LIST_HEIGHT = 150

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._items: list[dict] = []
        self._playing_index: int | None = None

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(6)
        self._head = QLabel(i18n.t("queue.title"), self)
        self._head.setFont(ui_font(12))
        head.addWidget(self._head)
        head.addStretch(1)
        self._clear_btn = FluentButton(i18n.t("queue.clear"), self, variant="subtle", height=26)
        self._clear_btn.setFont(ui_font(12))
        self._clear_btn.clicked.connect(self.clear_requested)
        head.addWidget(self._clear_btn)
        v.addLayout(head)

        self._scroll = QScrollArea(self)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._holder = QWidget()
        self._holder.setObjectName("queueHolder")
        self._rows_layout = QVBoxLayout(self._holder)
        self._rows_layout.setContentsMargins(0, 0, 4, 0)
        self._rows_layout.setSpacing(1)
        self._rows_layout.addStretch(1)
        self._scroll.setWidget(self._holder)
        v.addWidget(self._scroll)
        self.apply_theme()

    # -- 数据 --------------------------------------------------------
    def set_items(self, items: list[dict], playing_index: int | None = None,
                  playing: bool = False) -> None:
        self._items = items
        self._playing_index = playing_index
        self._playing_now = playing
        while self._rows_layout.count():
            it = self._rows_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                # deleteLater 只在下一轮事件循环生效，这期间旧行仍会画在原地，
                # 重建一次就多一层叠字（切语言最明显），所以先立刻摘出去、隐藏。
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self._rows = []
        for i, item in enumerate(items):
            path = str(item.get("path") or "")
            playable = item.get("status") == "done" and bool(path) and os.path.exists(path)
            row = _QueueRow(
                i, item["text"], item.get("status", "waiting"), self._holder,
                playable=playable,
                current=(i == playing_index),
                playing=(i == playing_index and playing),
            )
            row.remove_clicked.connect(self.remove_requested)
            row.play_clicked.connect(self.play_requested)
            self._rows.append(row)
            self._rows_layout.addWidget(row)
        self._rows_layout.addStretch(1)

        total_chars = sum(len(it["text"]) for it in items)
        est = tts_engine.estimate_seconds("".join(it["text"] for it in items)) if items else 0
        self._head.setText(
            i18n.t("queue.head", n=len(items), chars=total_chars, span=_fmt_span(est))
        )
        visible_rows = min(len(items), 4)
        self._scroll.setFixedHeight(max(32, visible_rows * 31))
        self.apply_theme()

    def set_playing_index(self, index: int | None, playing: bool | None = None) -> None:
        """只改「哪一行在播 / 是否在响」，不重建整张列表（避免播放时列表闪烁）。"""
        if playing is None:
            playing = getattr(self, "_playing_now", False)
        if index == self._playing_index and playing == getattr(self, "_playing_now", False):
            return
        self._playing_index = index
        self._playing_now = playing
        for i, row in enumerate(getattr(self, "_rows", [])):
            row.set_playback(i == index, i == index and playing)

    def retranslate(self) -> None:
        self._clear_btn.setText(i18n.t("queue.clear"))
        for row in getattr(self, "_rows", []):
            row.retranslate()
        self.set_items(self._items, self._playing_index, getattr(self, "_playing_now", False))

    def apply_theme(self) -> None:
        th = tm().theme
        self._head.setStyleSheet(f"color: {th.qss('text_secondary')};")
        self._scroll.setStyleSheet(
            f"""
            QScrollArea {{ background: transparent; border: none; }}
            QWidget#queueHolder {{ background: transparent; }}
            QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
            QScrollBar::handle:vertical {{
                background: {th.qss('text_tertiary', 0.5)};
                border-radius: 2px; min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {th.qss('text_secondary', 0.7)};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
            """
        )


class _DropHint(QWidget):
    """拖文件悬停在窗口上时的提示层。

    窗口现在是实心的，直接改窗口底色会把整窗闪一下；这里用一层半透明遮罩 +
    强调色虚线框，既说明"可以松手了"，也让底下的内容退到后面看得清字。
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._text = ""
        self._sub = ""
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)

    def set_text(self, main: str, sub: str = "") -> None:
        self._text = main
        self._sub = sub
        self.update()

    def texts(self) -> tuple[str, str]:
        return self._text, self._sub

    # 浮层铺满整个窗口，拖动时它可能成为拖拽事件的目标。这里全部转发给主窗口，
    # 免得"事件被浮层吃掉 → 主窗口收到离开 → 提示层收起"造成只闪一下。
    def dragEnterEvent(self, e):
        parent = self.parentWidget()
        if parent is not None:
            parent.dragEnterEvent(e)
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        parent = self.parentWidget()
        if parent is not None:
            parent.dragMoveEvent(e)
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        parent = self.parentWidget()
        if parent is not None:
            parent.dragLeaveEvent(e)
        else:
            e.ignore()

    def dropEvent(self, e):
        parent = self.parentWidget()
        if parent is not None:
            parent.dropEvent(e)
        else:
            e.ignore()

    def paintEvent(self, e):
        th = tm().theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        # 裁成窗口圆角再铺底，否则会把窗口四个圆角画成直角
        clip = QPainterPath()
        clip.addRoundedRect(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), RADIUS_WINDOW, RADIUS_WINDOW
        )
        p.setClipPath(clip)

        # 这里必须用不透明的窗体色打底：子控件如果不铺满，未初始化的缓冲会露出
        # 黑色（实测半透明遮罩在真实截屏里整块发黑、字也看不见）。
        # 取色要用 th.c()（QColor）：th.qss() 返回的是 "rgba(...)" 字符串，
        # QColor 解析不了，直接传进去会得到无效颜色 → 整块画成黑色。
        p.fillRect(self.rect(), th.c("window"))

        box = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        path = QPainterPath()
        path.addRoundedRect(box, RADIUS_WINDOW, RADIUS_WINDOW)
        tint = th.c("accent")
        tint.setAlpha(22)  # 约 8%，只染一层淡底，别把整窗盖成蓝色
        p.fillPath(path, tint)

        pen = QPen(th.c("accent"))
        pen.setWidth(2)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.drawPath(path)

        p.setPen(QPen(th.c("text_primary")))
        p.setFont(ui_font(16, F.DemiBold))
        main_rect = QRect(self.rect())
        main_rect.translate(0, -12 if self._sub else 0)
        p.drawText(main_rect, Qt.AlignCenter, self._text)

        if self._sub:
            p.setPen(QPen(th.c("text_secondary")))
            p.setFont(ui_font(12))
            sub_rect = QRect(self.rect())
            sub_rect.translate(0, 20)
            p.drawText(sub_rect, Qt.AlignCenter, self._sub)
        p.end()


class _ConfirmPopover(QWidget):
    """贴在触发按钮下方的小确认卡片。

    刻意不用 QMessageBox：系统对话框自带标题栏、会抢焦点、按钮是系统样式，跟自绘
    的 Win11 观感完全断层。这里就是窗口内的一层浮层，画一张带阴影的圆角卡片，点
    卡片外面或按 Esc 即取消（轻量关闭），确认动作本身仍然要点按钮。
    """

    confirmed = Signal()
    cancelled = Signal()

    # 画阴影要留出的内边距；卡片本体画在 PAD 以内
    PAD = 10

    def __init__(
        self,
        parent: QWidget,
        title: str,
        body: str,
        ok_text: str,
        cancel_text: str | None = None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setFixedWidth(312)

        self._title = QLabel(title, self)
        self._body = QLabel(body, self)
        self._body.setWordWrap(True)

        self._cancel = FluentButton(cancel_text or i18n.t("confirm.cancel"), self,
                                    variant=FluentButton.SUBTLE, height=28)
        self._ok = FluentButton(ok_text, self, variant=FluentButton.ACCENT, height=28)
        self._cancel.clicked.connect(self._on_cancel)
        self._ok.clicked.connect(self._on_ok)

        v = QVBoxLayout(self)
        v.setContentsMargins(self.PAD + 14, self.PAD + 12, self.PAD + 14, self.PAD + 12)
        v.setSpacing(6)
        v.addWidget(self._title)
        v.addWidget(self._body)
        v.addSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        row.addWidget(self._cancel)
        row.addWidget(self._ok)
        v.addLayout(row)

        self.apply_theme()
        self.setFocusPolicy(Qt.StrongFocus)
        self.hide()

    # -- 外观 --------------------------------------------------------
    def apply_theme(self) -> None:
        th = tm().theme
        self._title.setFont(ui_font(14, F.DemiBold))
        self._title.setStyleSheet(f"color: {th.qss('text_primary')};")
        self._body.setFont(ui_font(12))
        self._body.setStyleSheet(f"color: {th.qss('text_secondary')};")
        self.update()

    def paintEvent(self, e):
        th = tm().theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        body = QRectF(self.rect()).adjusted(self.PAD, self.PAD, -self.PAD, -self.PAD)

        # 软阴影：几层由外到内逐渐加深的圆角，模拟 Win11 弹层（子控件拿不到 DWM 阴影）
        shadow = th.c("shadow")
        for i in range(6, 0, -1):
            col = QColor(shadow)
            col.setAlpha(int(30 * (7 - i) / 6))
            path = QPainterPath()
            path.addRoundedRect(
                body.adjusted(-i, -i, i, i), RADIUS_CARD + i, RADIUS_CARD + i
            )
            p.fillPath(path, col)

        path = QPainterPath()
        path.addRoundedRect(body, RADIUS_CARD, RADIUS_CARD)
        p.fillPath(path, th.c("layer"))
        pen = QPen(th.c("layer_stroke"))
        pen.setWidth(1)
        p.setPen(pen)
        p.drawPath(path)
        p.end()

    # -- 交互 --------------------------------------------------------
    def set_texts(self, title: str, body: str, ok_text: str) -> None:
        """切界面语言时换文案（按钮宽度会按新文案重算）。"""
        self._title.setText(title)
        self._body.setText(body)
        self._ok.setText(ok_text)
        self._cancel.setText(i18n.t("confirm.cancel"))
        self._ok.adjustSize()
        self._cancel.adjustSize()
        self.adjustSize()

    def _on_cancel(self) -> None:
        self.hide()
        self.cancelled.emit()

    def _on_ok(self) -> None:
        self.hide()
        self.confirmed.emit()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._on_cancel()
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._on_ok()
            return
        super().keyPressEvent(e)

    def open_at(self, anchor: QWidget, title: str | None = None, body: str | None = None) -> None:
        """在触发按钮下方展开；下面放不下就翻到按钮上方。"""
        if title is not None:
            self._title.setText(title)
        if body is not None:
            self._body.setText(body)
        self.adjustSize()
        parent = self.parentWidget()
        if parent is None:
            return
        w, h = self.width(), self.height()
        br = anchor.mapTo(parent, QPoint(anchor.width(), anchor.height()))
        bl = anchor.mapTo(parent, QPoint(0, 0))
        x = br.x() - w
        y = br.y() + 8
        if y + h + 12 > parent.height():
            y = bl.y() - h - 8
        x = max(12, min(x, parent.width() - w - 12))
        y = max(12, max(min(y, parent.height() - h - 12), 12))
        self.move(x, y)
        self.show()
        self.raise_()
        # 焦点给卡片本身而不是某个按钮：Win11 只在键盘操作时才画焦点框，
        # 一弹出来就框住「取消」会很突兀。焦点在卡片上时 Esc / Enter 走
        # keyPressEvent，Tab 才进到按钮里。
        self.setFocus(Qt.PopupFocusReason)


class _AIPanel(QWidget):
    """AI 自动编写：一句短话 → 豆包扩写成可朗读文案 → 预览 → 替换/追加。

    平时收在语音卡片里的一条按钮后面（音量滑杆与输出目录之间那块空档），
    点开才铺开面板；面板里的模型配置默认折叠，不填 Key 时点生成会给出填写指引。
    """

    # (文案, 是否替换正文)；追加时由主窗口负责补换行
    insert_requested = Signal(str, bool)

    def __init__(self, settings: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self._settings = settings        # 直接改主窗口那份 dict，关窗时一起落盘
        self._job: ai_writer.WriterJob | None = None
        self._labels: list[tuple[QLabel, str, str, int]] = []   # (控件, i18n 键, token, 字号)
        self._result_text = ""

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        self._hint = self._caption(i18n.t("ai.hint"), "text_tertiary", 12, wrap=True)
        v.addWidget(self._hint)

        self._input = FluentInput(i18n.t("ai.sentence_ph"), self)
        self._input.returnPressed.connect(self._generate)
        v.addWidget(self._input)

        # 风格 / 长度 并排，省一半高度
        row = QHBoxLayout()
        row.setSpacing(8)
        col_style = QVBoxLayout()
        col_style.setSpacing(4)
        self._style_cap = self._caption(i18n.t("ai.style"), "text_secondary", 12)
        col_style.addWidget(self._style_cap)
        self._style_combo = FluentComboBox(self)
        self._style_combo.setFixedHeight(32)
        self._style_combo.setFont(ui_font(13))
        col_style.addWidget(self._style_combo)
        col_len = QVBoxLayout()
        col_len.setSpacing(4)
        self._len_cap = self._caption(i18n.t("ai.length"), "text_secondary", 12)
        col_len.addWidget(self._len_cap)
        self._len_combo = FluentComboBox(self)
        self._len_combo.setFixedHeight(32)
        self._len_combo.setFont(ui_font(13))
        col_len.addWidget(self._len_combo)
        row.addLayout(col_style, 1)
        row.addLayout(col_len, 1)
        v.addLayout(row)

        self._gen_btn = FluentButton(
            i18n.t("ai.generate"), self, variant=FluentButton.ACCENT,
            icon="sparkle", height=36,
        )
        self._gen_btn.clicked.connect(self._generate)
        v.addWidget(self._gen_btn)

        self._state = self._caption("", "text_tertiary", 12, wrap=True)
        self._state.setVisible(False)
        v.addWidget(self._state)

        # 结果区：先看再决定，不直接改正文
        self._result_caption = self._caption(i18n.t("ai.result"), "text_secondary", 12, wrap=True)
        self._result_caption.setVisible(False)
        v.addWidget(self._result_caption)
        self._result = FluentTextEdit(self)
        self._result.setReadOnly(True)
        self._result.setFixedHeight(150)
        self._result.setFont(ui_font(13))
        self._result.setVisible(False)
        self._result.menu_requested.connect(self._show_result_menu)
        self._result_menu: FluentMenu | None = None
        v.addWidget(self._result)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self._replace_btn = FluentButton(i18n.t("ai.replace"), self,
                                        variant=FluentButton.ACCENT, height=32)
        self._append_btn = FluentButton(i18n.t("ai.append"), self, height=32)
        self._discard_btn = FluentButton(i18n.t("ai.discard"), self,
                                         variant=FluentButton.SUBTLE, height=32)
        self._replace_btn.clicked.connect(lambda: self._insert(True))
        self._append_btn.clicked.connect(lambda: self._insert(False))
        self._discard_btn.clicked.connect(self._discard)
        for b in (self._replace_btn, self._append_btn, self._discard_btn):
            b.setVisible(False)
            actions.addWidget(b, 1)
        v.addLayout(actions)

        # 模型配置：默认折叠，避免一打开面板就是三个输入框
        self._cfg_btn = FluentButton(i18n.t("ai.settings"), self,
                                     variant=FluentButton.SUBTLE, height=28)
        self._cfg_btn.setFont(ui_font(12))
        self._cfg_btn.clicked.connect(self._toggle_config)
        cfg_row = QHBoxLayout()
        cfg_row.addStretch(1)
        cfg_row.addWidget(self._cfg_btn)
        v.addLayout(cfg_row)

        self._cfg_box = QWidget(self)
        cf = QVBoxLayout(self._cfg_box)
        cf.setContentsMargins(0, 0, 0, 0)
        cf.setSpacing(6)

        # 服务切换：方舟（要 Key）与本机 Ollama（要本机模型名）
        self._provider_cap = self._caption(i18n.t("ai.provider"), "text_secondary", 12)
        cf.addWidget(self._provider_cap)
        self._provider_combo = FluentComboBox(self._cfg_box)
        self._provider_combo.setFixedHeight(32)
        self._provider_combo.setFont(ui_font(13))
        cf.addWidget(self._provider_combo)

        # 方舟那组
        self._ark_box = QWidget(self._cfg_box)
        ab = QVBoxLayout(self._ark_box)
        ab.setContentsMargins(0, 0, 0, 0)
        ab.setSpacing(6)
        self._base_input = FluentInput(i18n.t("ai.base"), self._ark_box)
        self._base_input.setText(str(settings.get("ai_base", ai_writer.DEFAULT_BASE)))
        self._key_input = FluentInput(i18n.t("ai.key"), self._ark_box)
        self._key_input.setText(str(settings.get("ai_key", "")))
        self._key_input.setEchoMode(QLineEdit.Password)
        self._model_input = FluentInput(i18n.t("ai.model"), self._ark_box)
        self._model_input.setText(str(settings.get("ai_model", "")))
        for w in (self._base_input, self._key_input, self._model_input):
            ab.addWidget(w)
        cf.addWidget(self._ark_box)

        # 本机 Ollama 那组：地址 + 模型名 + 提示 + 检测连接
        self._ollama_box = QWidget(self._cfg_box)
        ob = QVBoxLayout(self._ollama_box)
        ob.setContentsMargins(0, 0, 0, 0)
        ob.setSpacing(6)
        self._ollama_base_input = FluentInput(i18n.t("ai.ollama_base"), self._ollama_box)
        self._ollama_base_input.setText(
            str(settings.get("ai_ollama_base", ai_writer.DEFAULT_OLLAMA_BASE)))
        self._ollama_model_input = FluentInput(i18n.t("ai.ollama_model"), self._ollama_box)
        self._ollama_model_input.setText(str(settings.get("ai_ollama_model", "")))
        ob.addWidget(self._ollama_base_input)
        ob.addWidget(self._ollama_model_input)
        self._ollama_hint = self._caption(i18n.t("ai.ollama_hint"), "text_tertiary", 11, wrap=True)
        ob.addWidget(self._ollama_hint)
        self._detect_btn = FluentButton(i18n.t("ai.detect"), self._ollama_box,
                                        variant=FluentButton.SUBTLE, height=28)
        self._detect_btn.setFont(ui_font(12))
        self._detect_btn.clicked.connect(self._detect)
        self._install_btn = FluentButton(i18n.t("ai.install"), self._ollama_box,
                                         variant=FluentButton.SUBTLE, height=28)
        self._install_btn.setFont(ui_font(12))
        self._install_btn.setToolTip(i18n.t("ai.install_tip"))
        self._install_btn.clicked.connect(self._on_install_click)
        self._install_btn.setVisible(not ai_writer.ollama_installed())
        self._page_btn = FluentButton(i18n.t("ai.page"), self._ollama_box,
                                      variant=FluentButton.SUBTLE, height=28)
        self._page_btn.setFont(ui_font(12))
        self._page_btn.setToolTip(i18n.t("ai.page_tip"))
        self._page_btn.clicked.connect(self._open_download_page)
        self._page_btn.setVisible(False)
        self._install_job = None
        det_row = QHBoxLayout()
        det_row.setContentsMargins(0, 0, 0, 0)
        det_row.setSpacing(4)
        det_row.addStretch(1)
        det_row.addWidget(self._page_btn)
        det_row.addWidget(self._install_btn)
        det_row.addWidget(self._detect_btn)
        ob.addLayout(det_row)
        self._ollama_state = self._caption("", "text_tertiary", 11, wrap=True)
        self._ollama_state.setVisible(False)
        ob.addWidget(self._ollama_state)
        cf.addWidget(self._ollama_box)
        self._detect_job = None

        self._save_btn = FluentButton(i18n.t("ai.save"), self._cfg_box, height=32)
        self._save_btn.clicked.connect(self._save_config)
        cf.addWidget(self._save_btn)
        self._cfg_box.setVisible(False)
        v.addWidget(self._cfg_box)

        self.setVisible(False)
        self._restyle()
        self._fill_combos()
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self._fill_providers()

        # 记住上次用的风格/长度
        self._select_by_data(self._style_combo, str(settings.get("ai_style", "natural")))
        self._select_by_data(self._len_combo, str(settings.get("ai_chars", 200)))

        self._cfg_expanded = False

    # -- 杂项 ------------------------------------------------------------

    def _caption(self, text: str, token: str, size: int, *, wrap: bool = False) -> QLabel:
        lab = QLabel(text, self)
        lab.setFont(ui_font(size))
        lab.setWordWrap(wrap)
        if wrap:
            lab.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self._labels.append((lab, text, token, size))
        return lab

    @staticmethod
    def _select_by_data(combo: QComboBox, data) -> None:
        idx = combo.findData(data)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _fill_combos(self) -> None:
        style_cur = self._style_combo.currentData()
        len_cur = self._len_combo.currentData()
        self._style_combo.blockSignals(True)
        self._style_combo.clear()
        for key in ai_writer.STYLES:
            self._style_combo.addItem(ai_writer.style_label(key), key)
        self._style_combo.blockSignals(False)
        self._len_combo.blockSignals(True)
        self._len_combo.clear()
        for n in ai_writer.LENGTHS:
            self._len_combo.addItem(ai_writer.length_label(n), n)
        self._len_combo.blockSignals(False)
        if style_cur is not None:
            self._select_by_data(self._style_combo, style_cur)
        if len_cur is not None:
            self._select_by_data(self._len_combo, len_cur)

    def _fill_providers(self) -> None:
        """服务下拉：方舟 / 本机 Ollama，切了只换输入框组，不动正文已有内容。"""
        cur = self._provider_combo.currentData()
        if cur is None:
            cur = str(self._settings.get("ai_provider", "ark"))
        self._provider_combo.blockSignals(True)
        self._provider_combo.clear()
        self._provider_combo.addItem(i18n.t("ai.provider_ark"), "ark")
        self._provider_combo.addItem(i18n.t("ai.provider_ollama"), "ollama")
        self._select_by_data(self._provider_combo, cur)
        self._provider_combo.blockSignals(False)
        self._apply_provider(str(self._provider_combo.currentData() or "ark"), clear_states=False)

    def _apply_provider(self, prov: str, clear_states: bool = True) -> None:
        is_ollama = prov == "ollama"
        self._ark_box.setVisible(not is_ollama)
        self._ollama_box.setVisible(is_ollama)
        self._settings["ai_provider"] = "ollama" if is_ollama else "ark"
        if clear_states:
            # 换服务后旧提示会互相打架（例如「设置已保存」和检测失败同时挂着）
            self._show_state("", "info")
            self._show_ollama_state("", "info")
        self.updateGeometry()

    def _on_provider_changed(self, _index: int) -> None:
        self._apply_provider(str(self._provider_combo.currentData() or "ark"))

    def _detect(self) -> None:
        """读本机 /api/tags：既验证服务起没起，也把已装模型名回显出来。"""
        if self._detect_job is not None and self._detect_job.isRunning():
            return
        base = self._ollama_base_input.text().strip() or ai_writer.DEFAULT_OLLAMA_BASE
        self._set_detecting(True)
        job = ai_writer.DetectJob(base, self)
        self._detect_job = job
        job.succeeded.connect(self._on_detected)
        job.failed.connect(self._on_detect_failed)
        job.finished.connect(self._on_detect_finished)
        job.start()

    def _set_detecting(self, on: bool) -> None:
        self._detect_btn.setEnabled(not on)
        self._detect_btn.setText(i18n.t("ai.detecting") if on else i18n.t("ai.detect"))
        if on:
            # 顶部那条「设置已保存」和这里的检测结果会互相打架，先清掉
            self._show_state("", "info")
            self._show_ollama_state("", "info")

    def _on_detected(self, names: list) -> None:
        names = [str(n) for n in names]
        if names and not self._ollama_model_input.text().strip():
            # 只有空着才帮填，别覆盖用户已经写好的名字
            self._ollama_model_input.setText(names[0])
        self._show_ollama_state(messages.ai_ollama_ok(names), "ok" if names else "warn")
        # 连上了就说明装好了，安装入口收起来
        if ai_writer.ollama_installed():
            self._install_btn.setVisible(False)
            self._page_btn.setVisible(False)

    def _on_detect_failed(self, text: str) -> None:
        self._show_ollama_state(text, "error")
        installed = ai_writer.ollama_installed()
        self._install_btn.setVisible(not installed)
        if installed:
            self._page_btn.setVisible(False)

    def _on_detect_finished(self) -> None:
        job = self.sender()
        self._detect_job = None
        self._set_detecting(False)
        if job is not None:
            job.deleteLater()

    # -- 一键安装 ---------------------------------------------------------

    def _on_install_click(self) -> None:
        """没装就下载官方安装包；正在下载时这个按钮变成「取消下载」。"""
        job = self._install_job
        if job is not None and job.isRunning():
            job.cancel()
            self._install_btn.setEnabled(False)
            self._install_btn.setText(i18n.t("ai.install_cancel"))
            return
        self._show_state("", "info")
        self._install_last_key = None
        self._page_btn.setVisible(False)
        self._show_ollama_state(messages.ollama_downloading(0, 0), "info")
        self._install_btn.setText(i18n.t("ai.install_cancel"))
        job = ai_writer.InstallJob(ai_writer.INSTALLER_PATH, self)
        self._install_job = job
        job.progress.connect(self._on_install_progress)
        job.done.connect(self._on_install_done)
        job.failed.connect(self._on_install_failed)
        job.finished.connect(self._on_install_finished)
        job.start()

    def _on_install_progress(self, done: int, total: int) -> None:
        # 每 64KB 报一次会把布局刷爆，这里按「百分比变了才重排」
        key = min(100, int(done * 100 / total)) if total > 0 else int(done / (512 * 1024))
        if key == getattr(self, "_install_last_key", None):
            return
        self._install_last_key = key
        self._show_ollama_state(messages.ollama_downloading(done, total), "info")

    def _on_install_done(self, path: str) -> None:
        self._install_btn.setText(i18n.t("ai.install"))
        self._install_btn.setEnabled(True)
        opened = self._launch_installer(path)
        if opened:
            self._show_ollama_state(messages.ollama_installer_opened(), "ok")
        else:
            self._show_ollama_state(messages.ollama_launch_failed(path), "warn")

    def _on_install_failed(self, text: str) -> None:
        self._install_btn.setText(i18n.t("ai.install"))
        self._install_btn.setEnabled(True)
        cancelled = "已取消" in text or "cancelled" in text.lower()
        # 不是用户主动取消，就说明是下载没成功，顺手把「打开下载页」露出来
        self._page_btn.setVisible(not cancelled and not ai_writer.ollama_installed())
        self._show_ollama_state(text, "error" if not cancelled else "warn")
        self.updateGeometry()

    def _open_download_page(self) -> None:
        QDesktopServices.openUrl(QUrl(ai_writer.DOWNLOAD_PAGE))

    def _on_install_finished(self) -> None:
        job = self.sender()
        self._install_job = None
        self._install_btn.setEnabled(True)
        if self._install_btn.text() == i18n.t("ai.install_cancel"):
            self._install_btn.setText(i18n.t("ai.install"))
        if job is not None:
            job.deleteLater()

    @staticmethod
    def _launch_installer(path: str) -> bool:
        """拉起安装向导（用户还要点几下）；失败时把路径留给用户手动双击。"""
        try:
            ok, _pid = QProcess.startDetached(path, [])
            return bool(ok)
        except Exception:  # noqa: BLE001
            return False

    def _on_detect_finished(self) -> None:
        job = self.sender()
        self._detect_job = None
        self._set_detecting(False)
        if job is not None:
            job.deleteLater()

    def _show_ollama_state(self, text: str, kind: str) -> None:
        self._ollama_state_kind = kind
        self._ollama_state.setText(text)
        self._ollama_state.setVisible(bool(text))
        self._restyle()
        self.updateGeometry()

    # -- 展开 / 收起 ------------------------------------------------------

    def is_open(self) -> bool:
        return self.isVisible()

    def set_open(self, opened: bool) -> None:
        if opened:
            self.setVisible(True)
            self._input.setFocus()
        else:
            self.setVisible(False)
            self._cfg_box.setVisible(False)
            self._cfg_expanded = False
            self._cfg_btn.setText(i18n.t("ai.settings"))
        self.updateGeometry()

    # -- 生成 ------------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self._job is not None and self._job.isRunning()

    @property
    def detecting(self) -> bool:
        return self._detect_job is not None and self._detect_job.isRunning()

    @property
    def installing(self) -> bool:
        return self._install_job is not None and self._install_job.isRunning()

    def _generate(self) -> None:
        if self.busy:
            return
        sentence = self._input.text().strip()
        if not sentence:
            self._show_state(messages.ai_need_sentence(), "error")
            self._input.setFocus()
            return
        chars = int(self._len_combo.currentData() or 200)
        style = str(self._style_combo.currentData() or "natural")
        self.sync_settings()
        if (self._settings["ai_provider"] == "ollama"
                and not self._settings["ai_ollama_model"]):
            # 本机模型没填时先去设置里补，别把请求发出去再报错
            self._show_state(i18n.t("ai.ollama_need_model"), "error")
            self._open_config()
            self._ollama_model_input.setFocus()
            return
        self._settings["ai_style"] = style
        self._settings["ai_chars"] = chars
        self._set_generating(True)
        self._show_state(messages.ai_generating(chars), "info")
        job = ai_writer.WriterJob(sentence, self._settings, style, chars, self)
        self._job = job
        job.succeeded.connect(self._on_wrote)
        job.failed.connect(self._on_failed)
        job.finished.connect(self._on_job_finished)
        job.start()

    def _on_wrote(self, text: str) -> None:
        self._result_text = text
        self._result.setPlainText(text)
        self._result_caption.setVisible(True)
        self._result.setVisible(True)
        for b in (self._replace_btn, self._append_btn, self._discard_btn):
            b.setVisible(True)
        self._show_state(messages.ai_done(len(text)), "ok")
        self.updateGeometry()

    def _on_failed(self, text: str) -> None:
        self._show_state(text, "error")
        self.updateGeometry()

    def _on_job_finished(self) -> None:
        self._set_generating(False)
        job = self.sender()
        self._job = None
        if job is not None:
            job.deleteLater()

    def _set_generating(self, on: bool) -> None:
        self._gen_btn.setEnabled(not on)
        self._gen_btn.setText(i18n.t("ai.writing") if on else i18n.t("ai.generate"))
        self._input.setEnabled(not on)
        self._style_combo.setEnabled(not on)
        self._len_combo.setEnabled(not on)
        self._cfg_btn.setEnabled(not on)
        for w in (self._provider_combo, self._base_input, self._key_input,
                  self._model_input, self._ollama_base_input, self._ollama_model_input,
                  self._detect_btn, self._save_btn):
            w.setEnabled(not on)

    def _show_state(self, text: str, kind: str) -> None:
        self._state_kind = kind
        self._state.setText(text)
        self._state.setVisible(bool(text))
        self._restyle_state()

    def _discard(self) -> None:
        self._result_text = ""
        self._result.clear()
        self._result.setVisible(False)
        self._result_caption.setVisible(False)
        for b in (self._replace_btn, self._append_btn, self._discard_btn):
            b.setVisible(False)
        self._show_state("", "info")
        self.updateGeometry()

    def _insert(self, replace: bool) -> None:
        if not self._result_text:
            return
        self.insert_requested.emit(self._result_text, replace)
        self._discard()
        self.set_open(False)

    def _toggle_config(self) -> None:
        self._cfg_expanded = not self._cfg_expanded
        self._cfg_box.setVisible(self._cfg_expanded)
        self._cfg_btn.setText(i18n.t("ai.fold") if self._cfg_expanded else i18n.t("ai.settings"))
        self.updateGeometry()

    def _open_config(self) -> None:
        """需要用户补配置时替他展开设置区，并滚到看得见的位置。"""
        if not self._cfg_expanded:
            self._cfg_expanded = True
            self._cfg_box.setVisible(True)
            self._cfg_btn.setText(i18n.t("ai.fold"))
            self.updateGeometry()
        win = self.window()
        scroll = getattr(win, "_voice_scroll", None)
        if scroll is not None:
            QTimer.singleShot(0, lambda: scroll.ensureWidgetVisible(self._cfg_box))

    def _show_result_menu(self, gpos: QPoint) -> None:
        """结果框的右键菜单：只给「复制 / 全选」，条目跟随界面语言。"""
        if self._result_menu is None:
            self._result_menu = FluentMenu(self.window())
            self._result_menu.triggered.connect(self._on_result_menu)
        has_sel = self._result.textCursor().hasSelection()
        items = [
            MenuItem("copy", i18n.t("menu.copy"), shortcut="Ctrl+C", enabled=has_sel),
            MenuItem.separator(),
            MenuItem("select_all", i18n.t("menu.select_all"), shortcut="Ctrl+A",
                     enabled=bool(self._result_text)),
        ]
        self._result_menu.set_items(items)
        self._result_menu.open_at_global(gpos)

    def _on_result_menu(self, key: str) -> None:
        if key == "copy":
            self._result.copy()
        elif key == "select_all":
            self._result.selectAll()
        self._result.setFocus(Qt.PopupFocusReason)

    def hide_menu(self) -> bool:
        """Esc / 点别处时收起结果框的右键菜单。"""
        if self._result_menu is not None and self._result_menu.isVisible():
            self._result_menu.close_menu()
            return True
        return False

    def sync_settings(self) -> None:
        """关窗前把模型配置输入框里的内容同步进设置（免得填了没点保存就丢了）。"""
        self._settings["ai_provider"] = str(self._provider_combo.currentData() or "ark")
        self._settings["ai_base"] = self._base_input.text().strip() or ai_writer.DEFAULT_BASE
        self._settings["ai_key"] = self._key_input.text().strip()
        self._settings["ai_model"] = self._model_input.text().strip()
        self._settings["ai_ollama_base"] = (
            self._ollama_base_input.text().strip() or ai_writer.DEFAULT_OLLAMA_BASE)
        self._settings["ai_ollama_model"] = self._ollama_model_input.text().strip()

    def _save_config(self) -> None:
        self.sync_settings()
        config.save_settings(self._settings)
        self._show_ollama_state("", "info")
        self._show_state(i18n.t("ai.saved"), "ok")

    # -- 语言 / 主题 ------------------------------------------------------

    def retranslate(self) -> None:
        keys = {
            "ai.hint": self._hint,
            "ai.style": self._style_cap,
            "ai.length": self._len_cap,
            "ai.result": self._result_caption,
            "ai.generate": self._gen_btn,
            "ai.replace": self._replace_btn,
            "ai.append": self._append_btn,
            "ai.discard": self._discard_btn,
            "ai.save": self._save_btn,
        }
        for key, w in keys.items():
            w.setText(i18n.t(key))
        self._cfg_btn.setText(i18n.t("ai.fold") if self._cfg_expanded else i18n.t("ai.settings"))
        self._input.setPlaceholderText(i18n.t("ai.sentence_ph"))
        self._input.update()
        self._provider_cap.setText(i18n.t("ai.provider"))
        self._fill_providers()
        self._detect_btn.setText(
            i18n.t("ai.detecting") if self._detect_job is not None else i18n.t("ai.detect"))
        self._install_btn.setText(
            i18n.t("ai.install_cancel") if self.installing else i18n.t("ai.install"))
        self._install_btn.setToolTip(i18n.t("ai.install_tip"))
        self._page_btn.setText(i18n.t("ai.page"))
        self._page_btn.setToolTip(i18n.t("ai.page_tip"))
        self._ollama_hint.setText(i18n.t("ai.ollama_hint"))
        for w, key in ((self._base_input, "ai.base"),
                       (self._key_input, "ai.key"),
                       (self._model_input, "ai.model"),
                       (self._ollama_base_input, "ai.ollama_base"),
                       (self._ollama_model_input, "ai.ollama_model")):
            w.setPlaceholderText(i18n.t(key))
            w.update()
        # 组合框里的风格名 / 长度名也要跟着换（先记下当前选的是哪个再重建）
        self._fill_combos()

    def _restyle_state(self) -> None:
        th = tm().theme
        token = {"ok": "state_ok", "error": "state_error"}.get(
            getattr(self, "_state_kind", "info"), "text_tertiary"
        )
        self._state.setStyleSheet(f"color: {th.qss(token)};")
        token2 = {"ok": "state_ok", "error": "state_error", "warn": "state_warn"}.get(
            getattr(self, "_ollama_state_kind", "info"), "text_tertiary"
        )
        self._ollama_state.setStyleSheet(f"color: {th.qss(token2)};")

    def _restyle(self) -> None:
        th = tm().theme
        for lab, _text, token, size in self._labels:
            lab.setFont(ui_font(size))
            lab.setStyleSheet(f"color: {th.qss(token)};")
        self._restyle_state()

    def apply_theme(self) -> None:
        """跟随主题重上色：输入框 / 下拉 / 结果框各自有一套 QSS。"""
        self._restyle()
        for w in (self._input, self._base_input, self._key_input, self._model_input,
                  self._ollama_base_input, self._ollama_model_input,
                  self._result, self._style_combo, self._len_combo, self._provider_combo):
            if hasattr(w, "apply_theme"):
                w.apply_theme()
        for w in (self._gen_btn, self._replace_btn, self._append_btn,
                  self._discard_btn, self._cfg_btn, self._save_btn, self._detect_btn,
                  self._install_btn, self._page_btn, self._provider_cap, self._ollama_hint,
                  self._ollama_state, self._result_caption, self._hint, self._state):
            w.update()

    def terminate_job(self) -> None:
        """关窗时把还在等接口的线程收掉：请求没法优雅取消，只能等一会儿再强停。"""
        for job in (self._job, self._detect_job, self._install_job):
            if job is None:
                continue
            if isinstance(job, ai_writer.InstallJob):
                job.cancel()
            job.quit()
            if not job.wait(1500):
                job.terminate()
                job.wait(500)


class MainWindow(QWidget):
    def __init__(self, settings: dict | None = None):
        super().__init__()
        self._settings = dict(settings or config.load_settings())
        # 语言要在建界面之前定下来：标签、按钮、提示的初始文案都按它取
        i18n.set_lang(str(self._settings.get("lang") or i18n.DEFAULT))
        self._margin = SHADOW_MARGIN
        self._hwnd = 0  # 原生窗口句柄，缓存下来供消息回调使用（回调里不能调 winId()）
        self._voices: list[dict] = tts_engine.load_cached_voices()
        self._job: tts_engine.SynthJob | None = None
        self._job_kind = ""
        self._preview_spoken = 0  # 试听实际朗读的字数（0=全文）
        self._status_text = ""  # 状态栏当前文案，用于判断「是不是还停在初始状态」
        self._status_kind = "info"
        # 语音库后台刷新时会重建列表并触发选中项变化；那段时间不要改状态栏，
        # 否则会把已经在显示的结果（比如「试听中」）冲成「准备就绪」。
        self._suppress_voice_status = False
        self._screen_name = ""  # 当前所在显示器，用于换屏时重算最小尺寸
        self._last_file = ""
        self._last_srt = ""
        # 朗读跟随：cues 是这次合成的句级时间轴，_follow_span 是当前高亮的正文区间
        self._follow_cues: list[tuple[float, float, str]] = []
        self._follow_span: tuple[int, int] | None = None
        self._follow_index: int | None = None
        self._follow_map_text = ""   # 建映射时用的正文，正文一变映射就得重算
        self._follow_map_cues: list | None = None  # 映射对应的时间轴（换时间轴也要重算）
        self._follow_ranges: list[tuple[int, int] | None] = []
        self._queue: list[dict] = []
        self._queue_running = False
        self._queue_abort = False
        self._queue_cursor = 0
        self._queue_started_at = 0.0
        # 队列里正在播放的那一段（None = 播放条放的是试听/正式生成的文件）
        self._queue_playing_index: int | None = None
        # 界面语言重排用的登记表：控件 -> 文案键
        self._tr_texts: list[tuple[QWidget, str]] = []
        self._tr_tips: list[tuple[QWidget, str]] = []
        self._tr_placeholders: list[tuple[QWidget, str]] = []
        self._status_is_ready = True
        self._labels: list[tuple[QLabel, str, int, QFont.Weight]] = []
        self._loading_voice_list = False

        self.setWindowTitle(config.APP_NAME)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        # 不再用 WA_TranslucentBackground：半透明窗口是 WS_EX_LAYERED，DWM 不会给它
        # 阴影，而且最大化时 Qt 的分层缓冲不会跟着放大，窗口只画出左上角一块。
        # 现在窗口样式已换成原生框架，阴影 / 圆角 / 动画都交给系统。
        self.setMinimumSize(1000, 680)
        # 语音卡片多了搜索行，默认高度给足，正常打开时卡片内不出现滚动条
        self.resize(1180, 840)
        self._clamp_min_size()
        self.setMouseTracking(True)

        self._player = player_mod.AudioPlayer(self)
        self._player.positionChanged.connect(self._on_player_position)
        self._player.durationChanged.connect(self._on_player_duration)
        self._player.playingChanged.connect(self._on_player_playing)
        self._player.finished.connect(self._on_player_finished)
        self._player.failed.connect(self._on_player_failed)

        # 菜单（右键菜单 / 语言菜单）是窗口内浮层，先建好再铺界面，保证层级在控件之上
        self._editor_menu = FluentMenu(self)
        self._editor_menu.triggered.connect(self._on_editor_menu)
        self._lang_menu = FluentMenu(self)
        self._lang_menu.triggered.connect(self._on_lang_menu)
        self._lang_menu.closed.connect(lambda: self._lang_btn.set_held(False))

        self._build_ui()
        self._edit.menu_requested.connect(self._show_editor_menu)
        i18n.on_change(self._retranslate)
        self._populate_locale_list()
        self._restore_settings()
        self._update_count()
        tm().changed.connect(self._apply_theme)
        self._apply_theme()
        self._edit.setFocus(Qt.OtherFocusReason)

        self._voice_loader: tts_engine.VoiceLoader | None = None
        QTimer.singleShot(300, self._refresh_voices)

        # 最大化按钮的命中是 HTMAXBUTTON（为了让系统弹贴靠布局），Qt 拿不到
        # 它的 hover 事件，只能自己按光标位置补一个高亮。
        self._caption_hover_timer = QTimer(self)
        self._caption_hover_timer.setInterval(120)
        self._caption_hover_timer.timeout.connect(self._poll_caption_hover)
        self._caption_hover_timer.start()

        # 拖拽导入：整窗接收，提示层浮在所有控件之上
        self.setAcceptDrops(True)
        # 文本框默认自己吃拖拽：文件拖到正文区时 Drop 会被它接走（插入一段 file://
        # 文本或干脆吞掉），主窗口收不到 dropEvent，提示层就永远收不掉。关掉它，
        # 让拖拽统一回到窗口上处理。
        self._edit.setAcceptDrops(False)
        self._drop_hint = _DropHint(self)
        self._drop_hint.setAcceptDrops(True)  # 万一它成了拖拽目标，也要能收到并转发
        self._drop_hint.hide()
        # 收提示层不要立刻收：拖动时 enter/leave 会因为浮层出现而抖动一下，
        # 立刻 hide 就变成"只闪一下"。给 180ms 宽限，期间再有 dragMove 就取消。
        self._drop_hide_timer = QTimer(self)
        self._drop_hide_timer.setSingleShot(True)
        self._drop_hide_timer.setInterval(180)
        self._drop_hide_timer.timeout.connect(self._drop_hint.hide)
        # 看门狗：拖拽在别的地方结束时（比如松手时被别的控件吃掉），Qt 未必再给
        # 我们 drop/leave，提示层会一直挂着。这里读真实按键状态兜底收尾。
        self._drop_last_activity = 0.0
        self._drop_watch = QTimer(self)
        self._drop_watch.setInterval(200)
        self._drop_watch.timeout.connect(self._check_drop_alive)

        # 快捷键（空格走 eventFilter，因为它要看焦点是不是在输入框里）
        self._shortcuts: list[QShortcut] = []
        self._install_shortcuts()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    # ================================================================ 快捷键

    def _install_shortcuts(self) -> None:
        """Ctrl+Enter 生成、Esc 停止。

        两个都是窗口级快捷键，焦点在文本框里也生效；空格例外——文本框里的空格
        必须还是空格，所以只在 eventFilter 里判断过焦点后才接管。
        """
        for seq in ("Ctrl+Return", "Ctrl+Enter"):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WindowShortcut)
            sc.activated.connect(self._primary_clicked)
            self._shortcuts.append(sc)
        esc = QShortcut(QKeySequence("Esc"), self)
        esc.setContext(Qt.WindowShortcut)
        esc.activated.connect(self._escape_action)
        self._shortcuts.append(esc)

    def _escape_action(self) -> None:
        """Esc = 停掉当前正在做的事：正在合成/跑队列就先取消，其次停止播放。

        Esc 是窗口级快捷键（快捷键映射在事件到达控件之前就把它吃了，挂在
        eventFilter 上收不到），所以「先收起清空确认卡片」放在这里做。
        """
        if self._hide_menus():
            return
        if self._hide_confirms():
            return
        if self._ai_panel.is_open() and not self._ai_panel.busy:
            self._ai_panel.set_open(False)
            self._ai_toggle.set_held(False)
            return
        if (self._job is not None and self._job.isRunning()) or self._queue_running:
            self._cancel_job()
            return
        if self._player.is_playing:
            self._player.stop()

    def _hide_menus(self) -> bool:
        """Esc / 点别处时先收起自绘菜单（右键菜单、语言菜单）。

        菜单自己会处理 Esc，但 Esc 是窗口级快捷键，键到这里就被窗口接走了，
        所以这个「先收菜单」的判断必须放在窗口侧，否则按 Esc 会去停播放。
        """
        closed = False
        for menu in (getattr(self, "_editor_menu", None), getattr(self, "_lang_menu", None)):
            if menu is not None and menu.isVisible():
                menu.close_menu()
                closed = True
        panel = getattr(self, "_ai_panel", None)
        if panel is not None and panel.hide_menu():
            closed = True
        return closed

    @staticmethod
    def _space_is_free(widget: QWidget | None) -> bool:
        """这些控件上空格另有含义（打字 / 展开下拉 / 按下按钮），不能抢。"""
        if widget is None:
            return True
        blocking = (
            QPlainTextEdit,
            QLineEdit,
            QTextEdit,
            QAbstractSpinBox,
            QComboBox,
            QAbstractButton,
        )
        return not isinstance(widget, blocking)

    def _confirms(self) -> list["_ConfirmPopover"]:
        """所有窗口内确认卡片（清空文本 / 清空队列）。"""
        out = []
        for name in ("_confirm_clear", "_confirm_queue"):
            pop = getattr(self, name, None)
            if pop is not None:
                out.append(pop)
        return out

    def _confirm_anchor(self, pop: "_ConfirmPopover") -> QWidget:
        if pop is getattr(self, "_confirm_queue", None):
            return self._queue_panel._clear_btn
        return self._clear_btn

    def _hide_confirms(self) -> bool:
        hidden = False
        for pop in self._confirms():
            if pop.isVisible():
                pop.hide()
                hidden = True
        return hidden

    def eventFilter(self, obj, event):
        """空格 = 播放 / 暂停，但只在焦点不在输入类控件上时接管。"""
        confirms = [p for p in self._confirms() if p.isVisible()]
        # 确认卡片：按 Esc 或点卡片以外的地方都关掉（轻量关闭，不抢焦点）
        if confirms:
            if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                for pop in confirms:
                    pop.hide()
                return True
            if event.type() in (
                QEvent.MouseButtonPress,
                QEvent.NonClientAreaMouseButtonPress,
            ):
                for pop in confirms:
                    keep = (
                        obj is pop
                        or (obj is not None and pop.isAncestorOf(obj))
                        or obj is self._confirm_anchor(pop)
                    )
                    if not keep:
                        pop.hide()
        if (
            event.type() == QEvent.KeyPress
            and event.key() == Qt.Key_Space
            and not (event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))
            and self.isActiveWindow()
            and QApplication.activeModalWidget() is None
        ):
            if self._space_is_free(QApplication.focusWidget()):
                self._toggle_play()
                return True
        # 松手落在别的控件上时，Drop 由那个控件收到；提示层在这里统一收掉。
        if event.type() == QEvent.Drop and self._drop_hint.isVisible():
            self._hide_drop_hint()
        return super().eventFilter(obj, event)

    # ================================================================ 构建

    def _label(self, text: str, token: str = "text_primary", size: int = 14,
               weight: QFont.Weight = F.Normal, *, display: bool = False) -> QLabel:
        lab = QLabel(text, self)
        lab.setFont(ui_font(size, weight, display=display))
        lab.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._labels.append((lab, token, size, weight))
        return lab

    # -- 界面语言：注册与重排 --------------------------------------------
    def _t_label(self, key: str, token: str = "text_primary", size: int = 14,
                 weight: QFont.Weight = F.Normal, *, display: bool = False) -> QLabel:
        lab = self._label(i18n.t(key), token, size, weight, display=display)
        self._tr_texts.append((lab, key))
        return lab

    def _tr_btn(self, btn, key: str):
        btn.setText(i18n.t(key))
        self._tr_texts.append((btn, key))
        return btn

    def _tr_tip(self, widget, key: str):
        widget.setToolTip(i18n.t(key))
        self._tr_tips.append((widget, key))
        return widget

    @staticmethod
    def _repaint_placeholder(widget) -> None:
        """换占位文案后主动重绘。

        QPlainTextEdit（正文框）只改 placeholderText 属性不会触发视口重绘，
        空框切语言时屏幕上会一直留着旧语言那句占位语，直到鼠标划过或改窗口
        大小才刷新。这里直接刷一次视口，QLineEdit 顺手也刷一下。
        """
        viewport = widget.viewport() if hasattr(widget, "viewport") else None
        (viewport or widget).update()

    def _tr_ph(self, widget, key: str):
        widget.setPlaceholderText(i18n.t(key))
        self._tr_placeholders.append((widget, key))
        return widget

    def _retranslate(self) -> None:
        """切语言后重排全部界面文案（不重建控件，输入内容与播放状态都保留）。"""
        for widget, key in self._tr_texts:
            widget.setText(i18n.t(key))
        for widget, key in self._tr_tips:
            widget.setToolTip(i18n.t(key))
        for widget, key in self._tr_placeholders:
            widget.setPlaceholderText(i18n.t(key))
            self._repaint_placeholder(widget)

        for btn in (self._min_btn, self._max_btn, self._close_btn):
            btn.retranslate()
        self._relabel_voice_lists()
        self._refresh_theme_tip()
        self._refresh_lang_tip()
        self._queue_panel.retranslate()
        self._ai_panel.retranslate()
        self._update_primary_label()
        self._update_count()
        self._update_confirm_texts()
        if self._status_is_ready:
            self._set_status(messages.READY, "info")

    def _relabel_voice_lists(self) -> None:
        """切语言后重建语言下拉与发音人列表：语言名、性别名都要跟着换。"""
        if not self._voices:
            return   # 语音库还没加载好（或离线没数据），等加载完自然会用新语言渲染
        locale_cur = self._locale_combo.currentData()
        voice_cur = str(self._voice_combo.currentData() or "")
        self._loading_voice_list = True
        self._fill_locale_combo()
        idx = self._locale_combo.findData(locale_cur)
        self._locale_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._loading_voice_list = False
        self._populate_voice_list(voice_cur)

    def _titlebar(self) -> QWidget:
        bar = QWidget(self)
        bar.setFixedHeight(TITLEBAR_HEIGHT)
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 0, 0, 0)
        h.setSpacing(8)

        icon = QLabel(bar)
        icon.setPixmap(glyphs.app_icon(16).pixmap(16, 16))
        icon.setFixedSize(16, 16)
        h.addWidget(icon)

        title = QLabel(config.APP_NAME, bar)
        title.setFont(ui_font(12, F.Normal))
        title.setStyleSheet("color: rgba(0,0,0,1.0);")
        self._labels.append((title, "text_primary", 12, F.Normal))
        h.addWidget(title)

        h.addStretch(1)

        # 语言按钮在主题按钮左边：Win11 的这类外观/语言入口都聚在标题栏右侧
        self._lang_btn = IconButton(
            "language", bar, size=28, variant="subtle", tooltip=i18n.t("bar.lang")
        )
        self._lang_btn.clicked.connect(self._open_lang_menu)
        h.addWidget(self._lang_btn)

        self._theme_btn = IconButton("sun", bar, size=28, variant="subtle", tooltip=i18n.t("bar.theme"))
        self._theme_btn.clicked.connect(self._cycle_theme)
        h.addWidget(self._theme_btn)

        self._caption_bar = QWidget(bar)
        ch = QHBoxLayout(self._caption_bar)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(0)
        self._min_btn = CaptionButton(CaptionButton.MIN, self._caption_bar)
        self._min_btn.clicked.connect(self.showMinimized)
        self._max_btn = CaptionButton(CaptionButton.MAX, self._caption_bar)
        self._max_btn.clicked.connect(self._toggle_max)
        self._close_btn = CaptionButton(CaptionButton.CLOSE, self._caption_bar)
        self._close_btn.clicked.connect(self.close)
        for b in (self._min_btn, self._max_btn, self._close_btn):
            ch.addWidget(b)
        h.addWidget(self._caption_bar)
        return bar

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(self._margin, self._margin, self._margin, self._margin)
        outer.setSpacing(0)
        self._outer = outer

        self.surface = _Surface(self)
        outer.addWidget(self.surface)

        inner = QVBoxLayout(self.surface)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)
        inner.addWidget(self._titlebar())

        body = QWidget(self.surface)
        inner.addWidget(body, 1)
        bl = QVBoxLayout(body)
        bl.setContentsMargins(28, 4, 28, 18)
        bl.setSpacing(14)

        # -- 页头 ----------------------------------------------------
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(self._t_label("page.title", "text_primary", 28, F.DemiBold, display=True))
        head.addWidget(self._t_label("page.subtitle", "text_secondary", 13))
        bl.addLayout(head)

        # -- 内容 ----------------------------------------------------
        content = QHBoxLayout()
        content.setSpacing(16)
        content.addWidget(self._editor_card(), 3)
        content.addWidget(self._voice_card(), 0)
        bl.addLayout(content, 1)

        # -- 底栏（播放条 / 进度条 / 状态与操作，由 _footer 一并创建）
        bl.addLayout(self._footer())

        # 清空的确认卡片（窗口内浮层，不是系统对话框）；平时隐藏，点「清空」才展开
        self._confirm_clear = _ConfirmPopover(
            self,
            i18n.t("confirm.clear_title"),
            i18n.t("confirm.clear_body"),
            i18n.t("confirm.clear_ok"),
        )
        self._confirm_clear.confirmed.connect(self._do_clear_text)
        self._confirm_clear.cancelled.connect(self._edit.setFocus)
        # 队列的「清空队列」同样要确认：一次点掉一整批段落，误触代价也不小
        self._confirm_queue = _ConfirmPopover(
            self,
            i18n.t("confirm.queue_title"),
            i18n.t("confirm.queue_body"),
            i18n.t("confirm.queue_ok"),
        )
        self._confirm_queue.confirmed.connect(self._do_clear_queue)
        self._confirm_queue.cancelled.connect(self._edit.setFocus)

    def _update_confirm_texts(self) -> None:
        """切语言时把两张确认卡片的标题/正文/按钮也换掉。"""
        self._confirm_clear.set_texts(
            i18n.t("confirm.clear_title"), i18n.t("confirm.clear_body"), i18n.t("confirm.clear_ok")
        )
        self._confirm_queue.set_texts(
            i18n.t("confirm.queue_title"),
            i18n.t("confirm.queue_body_n", n=len(self._queue)),
            i18n.t("confirm.queue_ok"),
        )

    def _editor_card(self) -> QWidget:
        card = Card(self)
        v = QVBoxLayout(card)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self._t_label("editor.title", "text_primary", 14, F.DemiBold))
        row.addStretch(1)
        self._count_label = self._label(i18n.t("editor.count_zero"), "text_tertiary", 12)
        row.addWidget(self._count_label)
        v.addLayout(row)

        self._edit = FluentTextEdit(card)
        self._tr_ph(self._edit, "editor.placeholder")
        self._edit.textChanged.connect(self._update_count)
        v.addWidget(self._edit, 1)

        tools = QHBoxLayout()
        tools.setSpacing(6)
        self._clear_btn = FluentButton(i18n.t("editor.clear"), card, variant="subtle", icon="clear", height=32)
        self._tr_btn(self._clear_btn, "editor.clear")
        self._tr_tip(self._clear_btn, "editor.clear_tip")
        self._clear_btn.clicked.connect(self._ask_clear_text)
        self._queue_btn = FluentButton(
            i18n.t("editor.queue"), card, variant="subtle", icon="queue", height=32
        )
        self._tr_btn(self._queue_btn, "editor.queue")
        self._tr_tip(self._queue_btn, "editor.queue_tip")
        self._queue_btn.clicked.connect(self._split_into_queue)
        tools.addWidget(self._clear_btn)
        tools.addWidget(self._queue_btn)
        tools.addStretch(1)
        hint = self._t_label("editor.hint", "text_tertiary", 12)
        tools.addWidget(hint)
        v.addLayout(tools)

        self._queue_panel = _QueuePanel(card)
        self._queue_panel.remove_requested.connect(self._remove_queue_item)
        self._queue_panel.clear_requested.connect(self._ask_clear_queue)
        self._queue_panel.play_requested.connect(self._play_queue_item)
        self._queue_panel.setVisible(False)
        v.addWidget(self._queue_panel)
        return card

    def _voice_card(self) -> QWidget:
        card = Card(self)
        card.setFixedWidth(340)
        # 内容比窗口高时（缩到最小尺寸、或以后再加控件）要能滚，否则
        # QVBoxLayout 会把固定高度的控件压扁、互相叠住。Win11 设置页也是这么做的。
        outer = QVBoxLayout(card)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._voice_scroll = QScrollArea(card)
        self._voice_scroll.setWidgetResizable(True)
        self._voice_scroll.setFrameShape(QFrame.NoFrame)
        self._voice_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._voice_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._voice_scroll.setFocusPolicy(Qt.NoFocus)
        self._voice_scroll.verticalScrollBar().setSingleStep(28)
        outer.addWidget(self._voice_scroll)

        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(20, 14, 20, 14)
        v.setSpacing(6)
        self._voice_scroll.setWidget(body)

        v.addWidget(self._t_label("voice.title", "text_primary", 14, F.DemiBold))
        v.addSpacing(2)

        v.addWidget(self._t_label("voice.language", "text_secondary", 12))
        self._locale_combo = FluentComboBox(card)
        self._locale_combo.currentIndexChanged.connect(self._on_locale_changed)
        v.addWidget(self._locale_combo)

        v.addSpacing(4)
        v.addWidget(self._t_label("voice.speaker", "text_secondary", 12))

        self._voice_combo = FluentComboBox(card)
        self._voice_combo.currentIndexChanged.connect(self._on_voice_changed)
        v.addWidget(self._voice_combo)

        preview = FluentButton(i18n.t("voice.preview"), card, variant="standard", icon="speaker", height=32)
        self._tr_btn(preview, "voice.preview")
        preview.clicked.connect(self._preview_voice)
        self._preview_btn = preview
        v.addWidget(preview)

        v.addSpacing(8)
        v.addWidget(Divider(card))
        v.addSpacing(4)

        self._rate_slider, rate_val = self._slider_row(v, "voice.rate", -50, 50, 0, "%")
        self._pitch_slider, pitch_val = self._slider_row(v, "voice.pitch", -50, 50, 0, "Hz")
        self._volume_slider, vol_val = self._slider_row(v, "voice.volume", -50, 50, 0, "%")
        self._rate_value = rate_val
        self._pitch_value = pitch_val
        self._volume_value = vol_val

        # AI 自动编写：占的就是删掉搜索框后腾出来的这段空档。
        # 平时只有一条按钮，点开面板才铺开（面板会撑高卡片，滚动区负责跟随）。
        v.addSpacing(10)
        self._ai_toggle = FluentButton(
            i18n.t("ai.button"), card, variant=FluentButton.SUBTLE,
            icon="sparkle", height=38,
        )
        self._tr_btn(self._ai_toggle, "ai.button")
        self._tr_tip(self._ai_toggle, "ai.button_tip")
        self._ai_toggle.clicked.connect(self._toggle_ai_panel)
        v.addWidget(self._ai_toggle)

        self._ai_panel = _AIPanel(self._settings, card)
        self._ai_panel.insert_requested.connect(self._apply_ai_text)
        v.addWidget(self._ai_panel)

        v.addStretch(1)
        v.addWidget(Divider(card))
        v.addSpacing(4)
        v.addWidget(self._t_label("voice.output", "text_secondary", 12))
        self._output_label = ElidedLabel(self._settings["output_dir"], card, size=12)
        v.addWidget(self._output_label)

        row = QHBoxLayout()
        row.setSpacing(6)
        pick = FluentButton(i18n.t("voice.change"), card, variant="subtle", height=32)
        self._tr_btn(pick, "voice.change")
        pick.clicked.connect(self._pick_output_dir)
        open_dir = FluentButton(i18n.t("voice.open"), card, variant="subtle", height=32)
        self._tr_btn(open_dir, "voice.open")
        open_dir.clicked.connect(self._open_output_dir)
        row.addWidget(pick)
        row.addWidget(open_dir)
        row.addStretch(1)
        v.addLayout(row)

        v.addSpacing(6)
        self._subtitle_cb = FluentCheckBox(
            i18n.t("voice.subtitle"),
            card,
            checked=bool(self._settings.get("subtitle", False)),
        )
        self._tr_btn(self._subtitle_cb, "voice.subtitle")
        self._tr_tip(self._subtitle_cb, "voice.subtitle_tip")
        self._subtitle_cb.toggled.connect(self._on_subtitle_toggled)
        v.addWidget(self._subtitle_cb)
        self._style_voice_scroll()
        return card

    def _style_voice_scroll(self) -> None:
        """卡片内滚动条：细、透明底、无箭头，颜色跟主题。"""
        th = tm().theme
        self._voice_scroll.setStyleSheet(
            f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollArea > QWidget > QWidget {{ background: transparent; }}
            QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px 0; }}
            QScrollBar::handle:vertical {{
                background: {th.qss('text_tertiary', 0.5)};
                border-radius: 3px; min-height: 32px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {th.qss('text_secondary', 0.6)}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
            """
        )
        self._voice_scroll.viewport().setStyleSheet("background: transparent;")

    def _slider_row(self, parent_layout: QVBoxLayout, name_key: str, lo: int, hi: int,
                    value: int, unit: str) -> tuple[FluentSlider, QLabel]:
        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(self._t_label(name_key, "text_secondary", 12))
        head.addStretch(1)
        val = self._label(f"{value:+d}{unit}", "text_tertiary", 12)
        val.setFont(ui_font(12, F.Normal))
        head.addWidget(val)
        parent_layout.addLayout(head)

        slider = FluentSlider(lo, hi, value)
        slider.valueChanged.connect(
            lambda v, lab=val, u=unit: lab.setText(f"{v:+d}{u}" if v else f"+0{u}")
        )
        parent_layout.addWidget(slider)
        return slider, val

    def _footer(self) -> QVBoxLayout:
        v = QVBoxLayout()
        v.setSpacing(8)

        # 播放条
        prow = QHBoxLayout()
        prow.setSpacing(10)
        self._play_btn = IconButton(
            "play", self, size=32, variant="subtle", tooltip=i18n.t("player.play_tip")
        )
        self._tr_tip(self._play_btn, "player.play_tip")
        self._play_btn.clicked.connect(self._toggle_play)
        self._play_btn.setEnabled(False)
        prow.addWidget(self._play_btn)

        self._seek = FluentSlider(0, 1000, 0)
        self._seek.setFixedHeight(30)
        self._seek.committed.connect(self._seek_to)
        self._seek.setEnabled(False)
        prow.addWidget(self._seek, 1)

        self._time_label = self._label("0:00 / 0:00", "text_tertiary", 12)
        self._time_label.setFont(ui_font(12))
        self._time_label.setFixedWidth(88)
        self._time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        prow.addWidget(self._time_label)

        self._probe_btn = IconButton(
            "folder", self, size=32, variant="subtle", tooltip=i18n.t("player.external_tip")
        )
        self._tr_tip(self._probe_btn, "player.external_tip")
        self._probe_btn.clicked.connect(self._open_in_system_player)
        self._probe_btn.setEnabled(False)
        prow.addWidget(self._probe_btn)
        v.addLayout(prow)

        # 进度
        self._progress = FluentProgressBar(self)
        self._progress.setFixedHeight(4)
        v.addWidget(self._progress)

        # 状态 + 操作
        arow = QHBoxLayout()
        arow.setSpacing(8)
        self._status = ScrollableStatus(self)
        self._status.set_message(messages.READY, tm().theme.qss("text_secondary"))
        arow.addWidget(self._status, 1)

        self._open_dir_btn = FluentButton(
            i18n.t("footer.open_dir"), self, variant="subtle", icon="folder", height=36
        )
        self._tr_btn(self._open_dir_btn, "footer.open_dir")
        self._open_dir_btn.clicked.connect(self._open_output_dir)
        arow.addWidget(self._open_dir_btn)

        self._save_as_btn = FluentButton(
            i18n.t("footer.save_as"), self, variant="standard", icon="save", height=36
        )
        self._tr_btn(self._save_as_btn, "footer.save_as")
        self._save_as_btn.clicked.connect(self._save_as)
        arow.addWidget(self._save_as_btn)

        self._primary_btn = FluentButton(
            i18n.t("footer.generate"), self, variant="accent", icon="play", height=36, min_width=132
        )
        self._tr_tip(self._primary_btn, "footer.generate_tip")
        self._primary_btn.clicked.connect(self._primary_clicked)
        arow.addWidget(self._primary_btn)
        v.addLayout(arow)
        return v

    # ================================================================ 语音列表

    def _locale_counts(self) -> dict[str, int]:
        """每种语言各有多少发音人。"""
        counts: dict[str, int] = {}
        for v in self._voices:
            loc = v["locale"]
            counts[loc] = counts.get(loc, 0) + 1
        return counts

    def _fill_locale_combo(self) -> None:
        """语言下拉：每条带上该语言的发音人数，例如「中文（简体） · 6」。"""
        counts = self._locale_counts()
        locales = sorted(counts, key=lambda loc: (loc != "zh-CN", loc))
        self._locale_combo.clear()
        # 「全部语言」放第一条：搜索想跨语言时不必先改语言
        self._locale_combo.addItem(messages.locale_all(len(self._voices)), "")
        for loc in locales:
            self._locale_combo.addItem(
                messages.locale_item(tts_engine.locale_label(loc), counts[loc]), loc
            )

    def _populate_locale_list(self) -> None:
        self._loading_voice_list = True
        self._fill_locale_combo()
        target = self._settings.get("locale", "zh-CN")
        idx = self._locale_combo.findData(target)
        self._locale_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._loading_voice_list = False
        self._populate_voice_list(str(self._settings.get("voice", "")))

    def _voice_scope(self) -> str:
        """当前语言筛选范围；空字符串表示「全部语言」。"""
        return self._locale_combo.currentData() or ""

    def _populate_voice_list(self, select: str = "") -> None:
        self._loading_voice_list = True
        locale = self._voice_scope()
        hits = [v for v in self._voices if not locale or v.get("locale") == locale]
        show_locale = not locale  # 全部语言时才标语言，避免同名列分不清
        self._voice_combo.clear()
        for v in hits:
            label = tts_engine.voice_display(v)
            if show_locale:
                label = f"{label} · {tts_engine.locale_label(v['locale'])}"
            self._voice_combo.addItem(label, v["short"])
        self._voice_combo.setToolTip(
            messages.voice_combo_hint(len(hits), len(self._voices))
        )
        idx = self._voice_combo.findData(select)
        self._voice_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._loading_voice_list = False
        self._on_voice_changed()

    def _on_locale_changed(self, _index: int) -> None:
        if self._loading_voice_list:
            return
        self._populate_voice_list()
        locale = self._voice_scope()
        if locale:
            self._set_status(
                messages.locale_voices(
                    tts_engine.locale_label(locale),
                    self._locale_counts().get(locale, 0),
                    len(self._voices),
                ),
                "info",
            )
        else:
            self._set_status(messages.all_voices(len(self._voices)), "info")

    def _on_voice_changed(self, _index: int = 0) -> None:
        if self._loading_voice_list:
            return
        voice = self._voice_combo.currentData()
        if not voice:
            return
        self._settings["voice"] = voice
        if self._voice_scope():
            self._settings["locale"] = self._voice_scope()
        # 语音库在后台刷新时也会走到这里（列表重建 → 选中项回填）。那时不能把状态栏
        # 打回「准备就绪」，否则刚算出来的「试听中」会被这一下擦掉。
        if not self._suppress_voice_status:
            self._set_neutral_status()

    # ---------------------------------------------------------- 发音人

    def _current_voice(self) -> dict:
        short = self._voice_combo.currentData()
        if not short:
            return {}
        for v in self._voices:
            if v.get("short") == short:
                return v
        return {}

    def _refresh_voices(self) -> None:
        if not tts_engine.EDGE_AVAILABLE:
            self._set_status(messages.EDGE_MISSING, "error")
            return
        if self._voice_loader is not None and self._voice_loader.isRunning():
            return
        self._voice_loader = tts_engine.VoiceLoader(self)
        self._voice_loader.loaded.connect(self._on_voices_loaded)
        self._voice_loader.failed.connect(self._on_voices_failed)
        self._voice_loader.start()

    def _on_voices_loaded(self, voices: list) -> None:
        if not voices:
            return
        current = self._voice_combo.currentData() or self._settings.get("voice")
        scope = self._voice_scope()  # 重建语言下拉前先记下用户选的范围（含「全部语言」）
        self._voices = voices
        self._loading_voice_list = True
        self._suppress_voice_status = True
        try:
            self._fill_locale_combo()
            target_locale = scope or self._settings.get("locale", "zh-CN")
            idx = self._locale_combo.findData(target_locale)
            self._locale_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self._loading_voice_list = False
            self._populate_voice_list(str(current or ""))
        finally:
            self._suppress_voice_status = False
        # 语音库刷新是后台补充信息：既别盖掉正在跑的合成，也别盖掉已经算出来的
        # 试听/合成结果（那条才是用户关心的）。
        busy = self._job is not None and self._job.isRunning()
        if not busy and self._status_text in ("", messages.READY):
            self._set_status(messages.voices_updated(len(voices)), "ok")

    def _on_voices_failed(self, msg: str) -> None:
        self._set_status(messages.voices_stale(msg), "warn")

    # ================================================================ 合成流程

    def _primary_clicked(self) -> None:
        if self._job is not None and self._job.isRunning():
            self._cancel_job()
            return
        if self._queue_running:
            self._cancel_job()
            return
        if self._queue:
            self._start_queue()
            return
        text = self._edit.toPlainText().strip()
        if not text:
            self._set_status(messages.NEED_TEXT, "error")
            self._edit.setFocus()
            return
        voice = self._voice_combo.currentData()
        if not voice:
            self._set_status(messages.NO_VOICE, "error")
            return
        out_dir = Path(self._settings.get("output_dir") or config.OUTPUT_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = voice.replace("Neural", "")
        name = f"{stem}_{time.strftime('%Y%m%d_%H%M%S')}.mp3"
        self._start_job(text, str(out_dir / name), "export")

    def _save_as(self) -> None:
        if self._job is not None and self._job.isRunning():
            return
        if self._queue_running:
            self._set_status(messages.QUEUE_BUSY_SAVE_AS, "warn")
            return
        text = self._edit.toPlainText().strip()
        if not text:
            self._set_status(messages.NEED_TEXT, "error")
            return
        voice = self._voice_combo.currentData() or self._settings.get("voice", "")
        default = str(Path(self._settings["output_dir"]) / f"{voice.replace('Neural', '')}.mp3")
        path, _ = QFileDialog.getSaveFileName(
            self, i18n.t("dlg.save_title"), default, i18n.t("dlg.mp3_filter")
        )
        if not path:
            return
        if not path.lower().endswith(".mp3"):
            path += ".mp3"
        self._start_job(text, path, "save_as")
    def _preview_voice(self) -> None:
        if self._job is not None and self._job.isRunning():
            return
        voice = self._voice_combo.currentData()
        if not voice:
            return
        text = self._edit.toPlainText().strip()
        if not text:
            text = i18n.pick(
                (
                    "这是当前发音人的试听效果，可以随时换一个再听听看。",
                    "This is a sample of the selected voice. Pick another voice and listen again.",
                )
            )
        # 以前这里硬截 [:48]，会在 "Engl" 这种词中间断开，听起来像程序没读完。
        # 现在超长时按句末标点切，并把实际朗读字数记下来提示用户。
        text, self._preview_spoken = batch.truncate_at_sentence(text)
        self._start_job(text, tts_engine.preview_path(), "preview")

    def _release_player_for(self, out_path: str) -> None:
        """MCI 打开的文件会一直被占着句柄。

        重新生成同名文件（典型是试听：目标永远是 preview.mp3）时，Windows 会让
        os.replace 报 [WinError 5] 拒绝访问。所以动笔之前先把播放器松开。
        """
        loaded = self._player.path
        if not loaded:
            return
        try:
            same = os.path.normcase(os.path.abspath(loaded)) == os.path.normcase(
                os.path.abspath(out_path)
            )
        except (OSError, ValueError):
            same = False
        if not same:
            return
        self._player.stop()
        self._player.shutdown()
        self._clear_follow()
        self._play_btn.setEnabled(False)
        self._seek.setEnabled(False)
        self._seek.setValue(0)
        self._time_label.setText("0:00 / 0:00")

    def _start_job(self, text: str, out_path: str, kind: str) -> None:
        self._release_player_for(out_path)
        req = tts_engine.SynthRequest(
            text=text,
            voice=self._voice_combo.currentData() or self._settings.get("voice", ""),
            out_path=out_path,
            rate=self._rate_slider.value(),
            pitch=self._pitch_slider.value(),
            volume=self._volume_slider.value(),
            subtitle=(kind != "preview") and self._subtitle_cb.isChecked(),
        )
        self._job_kind = kind
        self._job = tts_engine.SynthJob(req, self)
        self._job.progress.connect(self._on_job_progress)
        self._job.succeeded.connect(self._on_job_succeeded)
        self._job.failed.connect(self._on_job_failed)
        self._job.finished.connect(self._on_job_thread_finished)
        self._set_busy(True)
        self._progress.setIndeterminate(True)
        self._set_status(messages.SYNTHESIZING, "info")
        self._job.start()

    def _cancel_job(self) -> None:
        if self._queue_running:
            self._queue_abort = True
        if self._job is None:
            if self._queue_running:
                self._finish_queue()
            return
        self._job.cancel()
        self._set_status(messages.CANCELING, "warn")
        self._primary_btn.setEnabled(False)

    def _on_job_progress(self, pct: int) -> None:
        if self._progress.indeterminate:
            self._progress.setIndeterminate(False)
        if self._queue_running:
            total = max(len(self._queue), 1)
            overall = (self._queue_cursor + pct / 100.0) / total * 100
            self._progress.setValue(overall)
            self._set_status(
                messages.queue_progress(self._queue_cursor + 1, total, pct), "info"
            )
            return
        self._progress.setValue(pct)
        if self._job_kind == "preview":
            self._set_status(messages.preview_progress(pct), "info")
        else:
            self._set_status(
                messages.synth_progress(pct, len(self._edit.toPlainText())), "info"
            )

    def _on_job_succeeded(self, path: str, srt: str = "") -> None:
        if self._job_kind == "queue":
            if 0 <= self._queue_cursor < len(self._queue):
                item = self._queue[self._queue_cursor]
                item["status"] = "done"
                item["path"] = path
                item["srt"] = srt
            self._last_file = path
            self._last_srt = srt
            # 队列的正文是队列项自己的文字，和编辑区对不上，不参与跟随高亮
            self._follow_cues = []
            self._clear_follow()
            self._refresh_queue_panel()
            return  # 下一段由线程结束信号推进，避免两段同时开线程

        self._progress.setIndeterminate(False)
        self._progress.setValue(100)
        self._last_file = path
        self._last_srt = srt
        # 试听/正式生成会换掉播放器里的文件，队列那一段的「正在播」标记随之清掉
        self._queue_playing_index = None
        self._queue_panel.set_playing_index(None)
        self._begin_follow()
        self._play_btn.setEnabled(True)
        self._seek.setEnabled(True)
        self._probe_btn.setEnabled(True)
        if self._player.load(path):
            self._player.play()
        if self._job_kind == "preview":
            if self._preview_spoken:
                self._set_status(
                    messages.preview_done_limited(self._preview_spoken), "ok"
                )
            else:
                self._set_status(messages.PREVIEW_DONE, "ok")
        elif srt:
            self._set_status(messages.saved_with_srt(Path(path).name, Path(srt).name), "ok")
        else:
            self._set_status(messages.saved(Path(path).name), "ok")
        QTimer.singleShot(400, lambda: self._progress.setValue(0))

    def _on_job_failed(self, msg: str) -> None:
        if self._job_kind == "queue":
            if 0 <= self._queue_cursor < len(self._queue):
                item = self._queue[self._queue_cursor]
                item["status"] = "failed"
                item["error"] = msg
            self._refresh_queue_panel()
            return
        self._progress.setIndeterminate(False)
        self._progress.setValue(0)
        self._set_status(msg, "error")

    def _on_job_thread_finished(self) -> None:
        if self._job is not None:
            self._job.deleteLater()
            self._job = None
        if self._queue_running:
            # 队列期间不收放界面，避免每段之间闪一下
            if self._queue_abort:
                self._finish_queue()
            else:
                QTimer.singleShot(0, self._start_next_queue_item)
            return
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        if busy:
            self._primary_btn.setText(i18n.t("footer.cancel"))
            self._primary_btn._icon = "stop"
        else:
            self._update_primary_label()
        self._primary_btn.setEnabled(True)
        self._preview_btn.setEnabled(not busy)
        self._save_as_btn.setEnabled(not busy)
        self._edit.setReadOnly(busy)
        self._locale_combo.setEnabled(not busy)
        self._voice_combo.setEnabled(not busy)
        self._subtitle_cb.setEnabled(not busy)
        self._queue_btn.setEnabled(not busy)
        self._queue_panel.setEnabled(not busy)
        # 生成语音期间正文是只读的，AI 面板这时不许插入，干脆连入口一起禁用
        self._ai_toggle.setEnabled(not busy)
        if busy:
            self._ai_panel.setEnabled(False)
        else:
            self._ai_panel.setEnabled(True)
        self._primary_btn.update()

    # ================================================================ 批量队列

    def _split_into_queue(self) -> None:
        if self._queue_running:
            return
        text = self._edit.toPlainText()
        segments = batch.split_segments(text)
        if not segments:
            self._set_status(messages.QUEUE_EMPTY, "error")
            self._edit.setFocus()
            return
        for seg in segments:
            self._queue.append(
                {"text": seg, "status": "waiting", "path": "", "srt": "", "error": ""}
            )
        self._refresh_queue_panel()
        self._set_status(
            messages.queue_split(len(segments), len(self._queue)), "ok"
        )

    def _refresh_queue_panel(self) -> None:
        self._queue_panel.set_items(self._queue, self._queue_playing_index)
        self._queue_panel.setVisible(bool(self._queue))
        self._update_primary_label()

    def _update_primary_label(self) -> None:
        """空闲时主按钮跟随队列状态：有队列就是「生成队列 · N」。"""
        if self._queue_running or (self._job is not None and self._job.isRunning()):
            return
        n = len(self._queue)
        self._primary_btn.setText(
            i18n.t("footer.queue_n", n=n) if n else i18n.t("footer.generate")
        )
        self._primary_btn._icon = "play"
        self._primary_btn.update()

    def _remove_queue_item(self, index: int) -> None:
        if self._queue_running or not (0 <= index < len(self._queue)):
            return
        if self._queue_playing_index is not None:
            if self._queue_playing_index == index:
                self._stop_queue_playback()
            elif self._queue_playing_index > index:
                self._queue_playing_index -= 1
        self._queue.pop(index)
        self._refresh_queue_panel()
        self._set_status(messages.queue_removed(index + 1, len(self._queue)), "info")

    def _clear_queue(self) -> None:
        if self._queue_running:
            return
        if not self._queue:
            return
        count = len(self._queue)
        self._stop_queue_playback()
        self._queue.clear()
        self._refresh_queue_panel()
        self._set_status(messages.queue_cleared(count), "info")

    def _start_queue(self) -> None:
        if self._job is not None and self._job.isRunning():
            return
        if not self._voice_combo.currentData():
            self._set_status(messages.NO_VOICE, "error")
            return
        self._queue_running = True
        self._queue_abort = False
        self._queue_cursor = 0
        self._queue_started_at = time.time()
        # 重新生成会改写文件名：先把可能还在播的队列音频放开
        self._stop_queue_playback()
        for item in self._queue:
            item["status"] = "waiting"
            item["path"] = ""
            item["srt"] = ""
            item["error"] = ""
        self._refresh_queue_panel()
        self._progress.setIndeterminate(True)
        self._set_status(messages.queue_started(len(self._queue)), "info")
        self._start_next_queue_item()

    def _start_next_queue_item(self) -> None:
        if not self._queue_running:
            return
        if self._queue_abort:
            self._finish_queue()
            return
        index = next(
            (i for i, item in enumerate(self._queue) if item["status"] == "waiting"), None
        )
        if index is None:
            self._finish_queue()
            return

        item = self._queue[index]
        item["status"] = "running"
        self._queue_cursor = index
        self._refresh_queue_panel()

        out_dir = Path(self._settings.get("output_dir") or config.OUTPUT_DIR)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._set_status(messages.OUTPUT_DIR_BAD, "error")
            self._queue_abort = True
            self._finish_queue()
            return
        filename = batch.item_filename(index + 1, item["text"])
        out_path = batch.unique_path(str(out_dir), filename)
        self._start_job(item["text"], out_path, "queue")

    def _finish_queue(self) -> None:
        self._queue_running = False
        done = sum(1 for it in self._queue if it["status"] == "done")
        failed_items = [i for i, it in enumerate(self._queue) if it["status"] == "failed"]
        total = len(self._queue)
        elapsed = time.time() - self._queue_started_at if self._queue_started_at else 0.0

        self._set_busy(False)
        self._progress.setIndeterminate(False)

        if self._queue_abort:
            self._queue_abort = False
            self._progress.setValue(0)
            self._set_status(messages.queue_canceled(done, total), "warn")
            return

        self._progress.setValue(100)
        QTimer.singleShot(400, lambda: self._progress.setValue(0))
        if failed_items:
            first_err = self._queue[failed_items[0]].get("error", "")
            self._set_status(
                messages.queue_done_with_failures(
                    done, len(failed_items), failed_items[0] + 1, first_err, elapsed
                ),
                "warn",
            )
        else:
            self._set_status(messages.queue_done(done, elapsed), "ok")

        last = next((it for it in reversed(self._queue) if it["status"] == "done"), None)
        if last:
            self._last_file = last.get("path", "")
            self._last_srt = last.get("srt", "")
            self._queue_playing_index = None
            if self._last_file and self._player.load(self._last_file):
                self._play_btn.setEnabled(True)
                self._seek.setEnabled(True)
                self._probe_btn.setEnabled(True)
        self._queue_panel.set_playing_index(self._queue_playing_index)

    # ================================================================ 队列播放

    def _play_queue_item(self, index: int) -> None:
        """点队列行首的播放按钮：停掉当前试听，用底部的播放条放这一段。

        播放条本身不区分「试听」与「队列」——它们共用同一个 MCI 播放器和同一组
        控件，所以这里只需要把文件换掉，进度、时长、空格键、Esc 都自然跟上。
        """
        if not (0 <= index < len(self._queue)):
            return
        item = self._queue[index]
        path = str(item.get("path") or "")
        if item.get("status") != "done" or not path or not os.path.exists(path):
            self._set_status(messages.queue_play_missing(index + 1), "warn")
            return

        # 同一条再点一次 = 播放/暂停（和播放条上的按钮行为一致）
        if self._queue_playing_index == index and self._player.path:
            self._player.toggle()
            self._queue_panel.set_playing_index(self._queue_playing_index)
            return

        self._player.stop()
        # 队列正文和编辑区不是同一份文字，不参与朗读跟随
        self._follow_cues = []
        self._clear_follow()
        if not self._player.load(path):
            return
        # 先把「正在播哪一段」写好，再 play：play() 会立刻发 playingChanged，
        # 那一瞬间行首按钮就要能跟着变成暂停（否则要等下一次手动刷新）。
        self._queue_playing_index = index
        self._queue_panel.set_playing_index(index, False)
        self._player.play()
        self._last_file = path
        self._last_srt = str(item.get("srt") or "")
        self._play_btn.setEnabled(True)
        self._seek.setEnabled(True)
        self._probe_btn.setEnabled(True)
        self._seek.setValue(0)
        self._set_status(messages.queue_playing(index + 1), "info")

    def _stop_queue_playback(self) -> None:
        """停下队列音频并清掉「正在播哪一段」的标记（不动试听生成的音频）。"""
        if self._queue_playing_index is None:
            return
        self._player.stop()
        self._queue_playing_index = None
        if hasattr(self, "_queue_panel"):
            self._queue_panel.set_playing_index(None)

    # ================================================================ 播放器

    def _toggle_play(self) -> None:
        if not self._player.path:
            if self._last_file:
                self._player.load(self._last_file)
            else:
                return
        self._player.toggle()

    def _seek_to(self, value: int) -> None:
        dur = self._player.duration()
        if dur > 0:
            self._player.seek(int(dur * value / 1000))

    def _on_player_position(self, ms: int) -> None:
        dur = self._player.duration()
        if dur > 0 and not self._seek._dragging:
            self._seek.setValue(int(ms / dur * 1000))
        self._time_label.setText(f"{_fmt(ms)} / {_fmt(dur)}")
        self._sync_follow(ms)

    def _on_player_duration(self, ms: int) -> None:
        self._time_label.setText(f"0:00 / {_fmt(ms)}")

    def _on_player_playing(self, playing: bool) -> None:
        self._play_btn._icon = "pause" if playing else "play"
        self._play_btn.update()
        # 队列行首的按钮同步成「暂停 / 播放」，否则点了播放还在显示三角形
        if self._queue_playing_index is not None:
            self._queue_panel.set_playing_index(self._queue_playing_index, playing)

    def _on_player_finished(self) -> None:
        self._seek.setValue(0)
        self._play_btn._icon = "play"
        self._play_btn.update()
        self._clear_follow()
        if self._queue_playing_index is not None:
            self._queue_panel.set_playing_index(self._queue_playing_index, False)

    def _on_player_failed(self, msg: str) -> None:
        self._set_status(messages.player_hint(msg), "warn")

    def _open_in_system_player(self) -> None:
        if self._last_file and os.path.exists(self._last_file):
            player_mod.open_with_system(self._last_file)

    # ---------------------------------------------------------- 朗读跟随高亮

    def _begin_follow(self) -> None:
        """合成成功：记下这次的句级时间轴，等播放进度来对齐正文。

        时间轴取自 SynthJob 攒下的 SentenceBoundary（和字幕同一批数据），
        所以没勾「同时生成字幕」也能高亮。
        """
        job = self._job
        self._follow_cues = list(job.cues) if job is not None else []
        self._follow_index = None
        self._follow_span = None
        self._follow_ranges = []
        self._follow_map_text = ""
        self._follow_map_cues = None
        self._edit.set_running_highlight(None)

    def _clear_follow(self) -> None:
        """播完 / 换文件 / 正文被改时收掉高亮。时间轴留着，重新播还能用。"""
        self._follow_index = None
        self._follow_span = None
        self._edit.set_running_highlight(None)

    def _sync_follow(self, ms: int) -> None:
        """按播放进度把「正在读的那一句」高亮出来。

        播放器 120ms 报一次位置，句子才几秒一句，所以只在「换了句」时才动
        UI：平时零开销，也避免每帧都重排 ExtraSelection。
        """
        if not self._follow_cues:
            return
        idx = follow.cue_index_at(self._follow_cues, ms / 1000.0)
        if idx == self._follow_index:
            return
        self._follow_index = idx
        if idx is None:
            self._follow_span = None
            self._edit.set_running_highlight(None)
            return
        text = self._edit.toPlainText()
        if text != self._follow_map_text or self._follow_cues is not self._follow_map_cues:
            self._follow_map_text = text
            self._follow_map_cues = self._follow_cues
            self._follow_ranges = follow.cue_ranges(text, self._follow_cues)
        span = self._follow_ranges[idx] if idx < len(self._follow_ranges) else None
        self._follow_span = span
        self._edit.set_running_highlight(span)
        if span:
            self._edit.reveal_position(span[0])

    def _follow_text_changed(self) -> None:
        """正文一改，原来的字符区间就全错位了，先收掉高亮等下次重建。"""
        if self._follow_map_text and self._edit.toPlainText() != self._follow_map_text:
            self._follow_map_text = ""
            self._follow_map_cues = None
            self._follow_ranges = []
            self._follow_span = None
            self._edit.set_running_highlight(None)

    # ================================================================ 拖拽导入

    @staticmethod
    def _dropped_paths(mime) -> list[Path]:
        if mime is None or not mime.hasUrls():
            return []
        out: list[Path] = []
        for url in mime.urls():
            if url.isLocalFile():
                out.append(Path(url.toLocalFile()))
        return out

    def _show_drop_hint(self, count: int) -> None:
        main = i18n.t("drop.main", hint=importer.SUPPORTED_HINT)
        if count > 1:
            main += i18n.t("drop.more", n=count)
        sub = i18n.t("drop.sub") if self._edit.toPlainText().strip() else ""
        self._drop_hide_timer.stop()
        self._drop_last_activity = time.monotonic()
        if not self._drop_watch.isActive():
            self._drop_watch.start()
        text_changed = self._drop_hint.texts() != (main, sub)
        self._drop_hint.set_text(main, sub)
        if not self._drop_hint.isVisible():
            self._drop_hint.setGeometry(self.rect())
            self._drop_hint.show()
            self._drop_hint.raise_()
        elif text_changed:
            self._drop_hint.update()

    def _check_drop_alive(self) -> None:
        """拖拽结束就收起提示层，不管最后那条事件有没有送到我们手里。"""
        if not self._drop_hint.isVisible():
            self._drop_watch.stop()
            return
        if win_utils.mouse_dragging():
            self._drop_last_activity = time.monotonic()
            return
        # 按键已松开，且 0.5 秒内没有任何拖拽事件 → 这次拖拽确实结束了
        if time.monotonic() - self._drop_last_activity > 0.5:
            self._drop_hide_timer.stop()
            self._drop_hint.hide()
            self._drop_watch.stop()

    def _hide_drop_hint(self) -> None:
        self._drop_hide_timer.stop()
        self._drop_watch.stop()
        self._drop_hint.hide()

    def dragEnterEvent(self, e):
        paths = self._dropped_paths(e.mimeData())
        if not any(importer.is_supported_name(p.name) for p in paths):
            e.ignore()
            return
        self._show_drop_hint(len(paths))
        e.acceptProposedAction()

    def dragMoveEvent(self, e):
        paths = self._dropped_paths(e.mimeData())
        if any(importer.is_supported_name(p.name) for p in paths):
            self._show_drop_hint(len(paths))  # 顺带抵消一次抖动带来的收起
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        # 浮层铺满窗口，拖动过程中可能会出现"光标还在窗口里、却收到离开"的抖动；
        # 那种情况不收提示层。只有「光标真的移出窗口」或「鼠标键已经松了（拖拽结束
        # 但给我们的是 leave 而非 drop）」才收。
        inside = self.rect().contains(self.mapFromGlobal(QCursor.pos()))
        just_moved = time.monotonic() - self._drop_last_activity < 0.3
        if not inside:
            self._drop_hide_timer.start()
        elif not just_moved and not win_utils.mouse_dragging():
            self._drop_hide_timer.start()
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        self._hide_drop_hint()
        paths = self._dropped_paths(e.mimeData())
        usable = [p for p in paths if importer.is_supported_name(p.name)]
        if not usable:
            self._set_status(messages.IMPORT_UNSUPPORTED, "error")
            e.ignore()
            return
        e.acceptProposedAction()
        self._import_path(usable[0], ignored=len(paths) - 1)

    def _import_path(self, path: Path, ignored: int = 0) -> None:
        """把文件内容送进编辑区。

        编辑区已有内容时**追加**而不是覆盖：一次误拖就把写了半天的稿子冲掉是不可
        接受的；真要用新文件，先点「清空」。
        """
        try:
            body, _suffix = importer.text_from_path(path)
        except importer.ImportFailed as exc:
            self._set_status(messages.import_failed(exc.reason), "error")
            return
        chars = len(body.strip())
        current = self._edit.toPlainText()
        if current.strip():
            self._edit.setPlainText(current.rstrip() + "\n\n" + body)
            kind = "warn" if ignored else "info"
            text = (
                messages.imported_ignored(path.name, chars, ignored)
                if ignored
                else messages.imported_appended(path.name, chars)
            )
            self._set_status(text, kind)
        else:
            self._edit.setPlainText(body)
            text = (
                messages.imported_ignored(path.name, chars, ignored)
                if ignored
                else messages.imported(path.name, chars)
            )
            self._set_status(text, "warn" if ignored else "ok")
        self._edit.moveCursor(QTextCursor.End)
        self._edit.setFocus(Qt.OtherFocusReason)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        hint = getattr(self, "_drop_hint", None)
        if hint is not None:
            hint.setGeometry(self.rect())
        for pop in self._confirms():
            if pop.isVisible():
                pop.open_at(self._confirm_anchor(pop))

    # ================================================================ 杂项动作

    def _ask_clear_text(self) -> None:
        """点「清空」先问一次：这一步删了就没法撤销，误点代价太大。"""
        if not self._edit.toPlainText().strip():
            self._set_status(messages.CLEAR_EMPTY, "info")
            return
        self._open_confirm(self._confirm_clear, self._clear_btn)

    def _ask_clear_queue(self) -> None:
        """「清空队列」同样先确认：一次点掉整批段落，误触代价也不小。"""
        if self._queue_running:
            return
        if not self._queue:
            self._set_status(messages.QUEUE_CLEAR_EMPTY, "info")
            return
        n = len(self._queue)
        self._open_confirm(
            self._confirm_queue,
            self._queue_panel._clear_btn,
            i18n.t("confirm.queue_title"),
            i18n.t("confirm.queue_body_n", n=n),
        )

    def _open_confirm(self, pop: "_ConfirmPopover", anchor: QWidget,
                      title: str | None = None, body: str | None = None) -> None:
        """同一时间只挂一张确认卡片：开新的先把旧的收掉。"""
        for other in self._confirms():
            if other is not pop and other.isVisible():
                other.hide()
        pop.open_at(anchor, title, body)

    def _do_clear_queue(self) -> None:
        self._clear_queue()

    def _do_clear_text(self) -> None:
        self._edit.clear()
        self._set_status(messages.TEXT_CLEARED, "info")
        self._edit.setFocus(Qt.OtherFocusReason)

    def _update_count(self) -> None:
        text = self._edit.toPlainText()
        n = len(text.strip())
        est = tts_engine.estimate_seconds(text) if n else 0
        if n:
            self._count_label.setText(i18n.t("editor.count", n=n, sec=round(est)))
        else:
            self._count_label.setText(i18n.t("editor.count_zero"))
        self._follow_text_changed()

    def _on_subtitle_toggled(self, checked: bool) -> None:
        self._settings["subtitle"] = bool(checked)
        self._set_status(messages.SUB_ON if checked else messages.SUB_OFF, "info")

    # ---- AI 自动编写 ----------------------------------------------------

    def _toggle_ai_panel(self) -> None:
        opened = not self._ai_panel.is_open()
        self._ai_panel.set_open(opened)
        self._ai_toggle.set_held(opened)
        if opened:
            # 面板展开会把卡片撑高，滚一下让它整块进入视口（否则用户还得自己找）
            QTimer.singleShot(0, lambda: self._voice_scroll.ensureWidgetVisible(self._ai_panel))
        else:
            # 收起后卡片变矮，把滚动位置带回按钮附近，别停在半空
            QTimer.singleShot(0, lambda: self._voice_scroll.ensureWidgetVisible(self._ai_toggle))

    def _apply_ai_text(self, text: str, replace: bool) -> None:
        """把 AI 写好的文案放进正文：替换（可撤销）或追加到末尾。"""
        text = text.strip()
        if not text:
            return
        if replace:
            self._edit.selectAll()
            self._edit.insertPlainText(text)
        else:
            cur = self._edit.textCursor()
            cur.movePosition(QTextCursor.End)
            existing = self._edit.toPlainText()
            prefix = ""
            if existing and not existing.endswith("\n"):
                prefix = "\n\n"
            elif existing and not existing.endswith("\n\n"):
                prefix = "\n"
            self._edit.setTextCursor(cur)
            self._edit.insertPlainText(prefix + text)
        self._update_count()
        self._set_status(messages.ai_inserted(len(text), replace), "ok")
        # 插入后面板由面板自己收起，这里同步按钮的按下态与滚动位置
        self._ai_toggle.set_held(False)
        QTimer.singleShot(0, lambda: self._voice_scroll.ensureWidgetVisible(self._ai_toggle))
        self._edit.setFocus()

    def _pick_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, i18n.t("dlg.dir_title"), self._settings["output_dir"]
        )
        if path:
            self._settings["output_dir"] = path
            self._output_label.set_full_text(path)

    def _open_output_dir(self) -> None:
        path = self._settings.get("output_dir") or str(config.OUTPUT_DIR)
        Path(path).mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception:
            self._set_status(messages.OUTPUT_OPEN_FAILED, "error")

    def _restore_settings(self) -> None:
        self._rate_slider.setValue(int(self._settings.get("rate", 0)))
        self._pitch_slider.setValue(int(self._settings.get("pitch", 0)))
        self._volume_slider.setValue(int(self._settings.get("volume", 0)))
        self._output_label.set_full_text(self._settings["output_dir"])
        mode = self._settings.get("theme", "system")
        if mode in tm().MODES:
            tm().set_mode(mode)

    def _cycle_theme(self) -> None:
        mode = tm().cycle()
        self._settings["theme"] = mode
        self._set_status(messages.theme_switched(tm().MODE_LABELS[mode]), "info")

    # ================================================================ 界面语言

    def _refresh_theme_tip(self) -> None:
        self._theme_btn.setToolTip(
            i18n.t("bar.theme_state", name=tm().MODE_LABELS[tm().mode])
        )

    def _refresh_lang_tip(self) -> None:
        self._lang_btn.setToolTip(
            i18n.t("bar.lang_state", name=i18n.LANG_LABELS[i18n.lang()])
        )

    def _open_lang_menu(self) -> None:
        """点标题栏的地球按钮：弹出语言菜单，当前语言打勾；菜单开着时再点一次收起。"""
        if self._lang_menu.isVisible():
            self._lang_menu.close_menu()
            return
        items = [MenuItem.title(i18n.t("bar.lang"))]
        for code in i18n.LANG_CODES:
            items.append(
                MenuItem(
                    f"lang:{code}",
                    i18n.LANG_LABELS[code],
                    checked=(code == i18n.lang()),
                )
            )
        self._lang_menu.set_items(items)
        self._lang_menu.open_below(self._lang_btn)
        self._lang_btn.set_held(True)
        self._lang_btn._icon = "language"
        self._lang_btn.update()

    def _on_lang_menu(self, key: str) -> None:
        if key.startswith("lang:"):
            self._set_language(key.split(":", 1)[1])

    def _set_language(self, code: str) -> None:
        if code not in i18n.LANG_CODES or code == i18n.lang():
            return
        self._settings["lang"] = code
        # i18n.set_lang 会通知 messages 与主窗口重排文案（self._retranslate）
        i18n.set_lang(code)
        config.save_settings(self._settings)
        self._refresh_lang_tip()
        self._set_status(messages.READY, "info")

    # ================================================================ 右键菜单

    def _show_editor_menu(self, gpos: QPoint) -> None:
        """文本框右键菜单：条目跟随界面语言（Qt 自带的英文菜单不再使用）。"""
        edit = self._edit
        readonly = edit.isReadOnly()
        has_sel = edit.textCursor().hasSelection()
        has_text = bool(edit.toPlainText())
        can_undo = edit.document().isUndoAvailable() and not readonly
        can_redo = edit.document().isRedoAvailable() and not readonly
        clipboard = QApplication.clipboard()
        can_paste = (
            not readonly
            and clipboard is not None
            and clipboard.mimeData() is not None
            and clipboard.mimeData().hasText()
        )
        items = [
            MenuItem("undo", i18n.t("menu.undo"), shortcut="Ctrl+Z", enabled=can_undo),
            MenuItem("redo", i18n.t("menu.redo"), shortcut="Ctrl+Y", enabled=can_redo),
            MenuItem.separator(),
            MenuItem("cut", i18n.t("menu.cut"), shortcut="Ctrl+X", enabled=has_sel and not readonly),
            MenuItem("copy", i18n.t("menu.copy"), shortcut="Ctrl+C", enabled=has_sel),
            MenuItem("paste", i18n.t("menu.paste"), shortcut="Ctrl+V", enabled=can_paste),
            MenuItem("delete", i18n.t("menu.delete"), shortcut="Del", enabled=has_sel and not readonly),
            MenuItem.separator(),
            MenuItem("select_all", i18n.t("menu.select_all"), shortcut="Ctrl+A", enabled=has_text),
        ]
        self._editor_menu.set_items(items)
        self._editor_menu.open_at_global(gpos)

    def _on_editor_menu(self, key: str) -> None:
        edit = self._edit
        if key == "undo":
            edit.undo()
        elif key == "redo":
            edit.redo()
        elif key == "cut":
            edit.cut()
        elif key == "copy":
            edit.copy()
        elif key == "paste":
            edit.paste()
        elif key == "delete":
            edit.textCursor().removeSelectedText()
        elif key == "select_all":
            edit.selectAll()
        edit.setFocus(Qt.PopupFocusReason)

    # ================================================================ 状态 / 主题

    def _set_status(self, text: str, kind: str = "info") -> None:
        self._status_kind = kind
        self._status_text = text
        self._status_is_ready = text == messages.READY
        th = tm().theme
        # 四档语义：info 灰、ok 绿、warn 琥珀、error 红
        token = {
            "info": "text_secondary",
            "ok": "state_ok",
            "warn": "state_warn",
            "error": "state_error",
        }.get(kind, "text_secondary")
        self._status.set_message(text, th.qss(token))

    def _set_neutral_status(self) -> None:
        self._set_status(messages.READY, "info")

    def _apply_theme(self) -> None:
        th = tm().theme
        dark = th.is_dark
        win_utils.apply_dark_frame(int(self.winId()), dark)

        for lab, token, size, weight in self._labels:
            lab.setFont(ui_font(size, weight))
            lab.setStyleSheet(f"color: {th.qss(token)};")
        self._output_label.set_color(th.c("text_tertiary"))
        self._status.apply_theme()
        # 换主题后按当前语义重新上色，否则状态栏还留着旧主题的颜色
        self._set_status(self._status.text(), getattr(self, "_status_kind", "info"))
        for w in (self._edit, self._locale_combo, self._voice_combo):
            if hasattr(w, "apply_theme"):
                w.apply_theme()
        self._ai_panel.apply_theme()
        self._queue_panel.apply_theme()
        self._theme_btn._icon = {"system": "refresh", "light": "sun", "dark": "moon"}[tm().mode]
        self._refresh_theme_tip()
        self._refresh_lang_tip()
        confirm = getattr(self, "_confirm_clear", None)
        if confirm is not None:
            confirm.apply_theme()
        queue_confirm = getattr(self, "_confirm_queue", None)
        if queue_confirm is not None:
            queue_confirm.apply_theme()
        if hasattr(self, "_voice_scroll"):
            self._style_voice_scroll()
        for w in self.findChildren(QWidget):
            w.update()
        self.update()

    def _poll_caption_hover(self) -> None:
        """补最大化按钮的 hover：它的区域命中 HTMAXBUTTON，Qt 收不到鼠标事件。"""
        maxed_or_visible = self._max_btn.isVisible()
        if not maxed_or_visible:
            self._max_btn.set_hover(False)
            return
        pos = self._max_btn.mapFromGlobal(QCursor.pos())
        self._max_btn.set_hover(self._max_btn.rect().contains(pos) and self.isActiveWindow())

    def _clamp_min_size(self) -> None:
        """最小尺寸不能超过当前显示器的工作区。

        1000×680 是给 1080p 定的。换到更小的屏（或同样的屏但缩放更高，
        逻辑分辨率会变小）时，若最小尺寸大于工作区，最大化就会被最小尺寸顶住、
        窗口比屏幕还大，圆角和边框跑到屏幕外。
        """
        scr = self.screen() or QGuiApplication.primaryScreen()
        if scr is None:
            return
        av = scr.availableGeometry()
        self.setMinimumSize(min(1000, av.width()), min(680, av.height()))

    def moveEvent(self, e):
        super().moveEvent(e)
        # 拖到另一块屏幕上时重新收紧最小尺寸（只在该屏第一次出现时才做，避免刷屏）
        scr = self.screen()
        if scr is not None and scr.name() != self._screen_name:
            self._screen_name = scr.name()
            self._clamp_min_size()

    def _sync_window_state(self) -> None:
        maxed = self.isMaximized()
        m = 0 if maxed else SHADOW_MARGIN
        if m != self._margin:
            self._margin = m
            self._outer.setContentsMargins(m, m, m, m)
        self.surface.radius = 0 if maxed else RADIUS_WINDOW
        self._max_btn.set_kind(CaptionButton.RESTORE if maxed else CaptionButton.MAX)
        self.surface.update()
        self.update()

    def _toggle_max(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._sync_window_state()

    def changeEvent(self, e):
        if e.type() == QEvent.WindowStateChange:
            self._sync_window_state()
        super().changeEvent(e)

    # ================================================================ 原生窗口行为

    def paintEvent(self, e):
        th = tm().theme
        p = QPainter(self)
        # 窗口现在是实心的：圆角被 DWM 裁掉，露出来的四个角要填成窗口底色，
        # 否则会闪出 Qt 默认的窗口背景色。
        p.fillRect(self.rect(), th.c("window"))
        if self._margin <= 0:
            p.end()
            return
        base = QRectF(
            self._margin, self._margin,
            self.width() - 2 * self._margin, self.height() - 2 * self._margin,
        )
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        col = th.c("shadow")
        steps = int(self._margin)
        for i in range(steps, 0, -1):
            t = i / steps
            c = QColor(col)
            c.setAlpha(int(col.alpha() * (1 - t) ** 2 * 0.55) + 2)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(base.adjusted(-i, -i, i, i), RADIUS_WINDOW + i, RADIUS_WINDOW + i)
        p.end()

    def nativeEvent(self, eventType, message):
        if win_utils.IS_WIN and eventType == b"windows_generic_MSG":
            try:
                msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
                kind = int(msg.message)
                # 客户区铺满：不画系统标题栏，但保留原生框架的行为（动画/缩放/贴靠）
                if kind == win_utils.WM_NCCALCSIZE:
                    if int(msg.wParam):
                        # 这里必须用 Win32 的样式位判断，不能问 Qt：
                        # WM_NCCALCSIZE 在状态切换中途到达，Qt 的 isMaximized()
                        # 此时还是旧值，会导致还原后多缩一圈、露出系统标题栏。
                        if win_utils.is_zoomed(self._hwnd):
                            params = ctypes.cast(
                                int(msg.lParam),
                                ctypes.POINTER(win_utils.NCCALCSIZE_PARAMS),
                            ).contents
                            b = win_utils.frame_border(self._hwnd)
                            params.rgrc[0].left += b
                            params.rgrc[0].top += b
                            params.rgrc[0].right -= b
                            params.rgrc[0].bottom -= b
                        return True, 0
                if kind == win_utils.WM_NCHITTEST:
                    sx = ctypes.c_short(msg.lParam & 0xFFFF).value
                    sy = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                    zone = self._hit_test(self._logical_pos(sx, sy))
                    if zone is not None:
                        return True, zone
                # 最大化按钮走非客户区命中，Qt 收不到点击，这里自己接：
                # 按下时吞掉，避免系统把点击转成拖动；抬起时切换最大化。
                if kind in (
                    win_utils.WM_NCLBUTTONDOWN,
                    win_utils.WM_NCLBUTTONDBLCLK,
                ):
                    if int(msg.wParam) == win_utils.HTMAXBUTTON:
                        return True, 0
                if kind == win_utils.WM_NCLBUTTONUP:
                    if int(msg.wParam) == win_utils.HTMAXBUTTON:
                        self._toggle_max()
                        return True, 0
            except Exception:
                pass
        return super().nativeEvent(eventType, message)

    def showEvent(self, e):
        super().showEvent(e)
        # 必须在窗口真正创建之后再改样式，否则会被 Qt 的窗口标志覆盖
        if win_utils.IS_WIN:
            self._hwnd = int(self.winId())
            win_utils.make_native_frame(self._hwnd)
            win_utils.apply_round_corners(self._hwnd)
            self._sync_window_state()

    def _logical_pos(self, screen_x: int, screen_y: int) -> QPoint:
        """WM_NCHITTEST 的 lParam 是物理屏幕像素，转成窗口内逻辑坐标。"""
        dpr = self.devicePixelRatioF() or 1.0
        gp = QPoint(round(screen_x / dpr), round(screen_y / dpr))
        return self.mapFromGlobal(gp)

    def _hit_test(self, pos: QPoint | None = None) -> int | None:
        m = self._margin
        if pos is None:
            pos = self.mapFromGlobal(QCursor.pos())
        w, h = self.width(), self.height()
        if not (0 <= pos.x() < w and 0 <= pos.y() < h):
            return None
        # 阴影留白区域让鼠标穿透
        if not (m <= pos.x() < w - m and m <= pos.y() < h - m):
            return win_utils.HTTRANSPARENT

        lx = pos.x() - m
        ly = pos.y() - m
        iw = w - 2 * m
        ih = h - 2 * m
        edge = 6

        if not self.isMaximized():
            left, right = lx < edge, lx >= iw - edge
            top, bottom = ly < edge, ly >= ih - edge
            if top and left:
                return win_utils.HTTOPLEFT
            if top and right:
                return win_utils.HTTOPRIGHT
            if bottom and left:
                return win_utils.HTBOTTOMLEFT
            if bottom and right:
                return win_utils.HTBOTTOMRIGHT
            if left:
                return win_utils.HTLEFT
            if right:
                return win_utils.HTRIGHT
            if top:
                return win_utils.HTTOP
            if bottom:
                return win_utils.HTBOTTOM

        # 标题栏：交给系统做拖动 / 双击最大化 / Aero Snap。
        # 但标题栏上的按钮必须返回 HTCLIENT，否则系统把点击当成拖动，
        # 按钮（主题切换、最小化/最大化/关闭）永远收不到鼠标事件。
        if ly < TITLEBAR_HEIGHT:
            # 最大化：返回 HTMAXBUTTON，Windows 才会在悬停时弹出贴靠布局；
            # 点击由 nativeEvent 里的 WM_NCLBUTTONUP 自己处理。
            # 语言按钮也在标题栏上，漏掉它就会被系统当成拖动区、点了没反应
            for b in (self._lang_btn, self._theme_btn, self._min_btn, self._max_btn, self._close_btn):
                if not b.isVisible():
                    continue
                origin = b.mapTo(self, QPoint(0, 0))
                if QRect(origin, b.size()).contains(pos):
                    if b is self._max_btn:
                        return win_utils.HTMAXBUTTON
                    return win_utils.HTCLIENT
            return win_utils.HTCAPTION
        return win_utils.HTCLIENT

    # ================================================================ 生命周期

    def closeEvent(self, e):
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)  # 不摘掉的话，窗口关了空格还会往它上面发
        if self._voice_loader is not None and self._voice_loader.isRunning():
            self._voice_loader.quit()
            self._voice_loader.wait(1500)
        self._queue_abort = True
        if self._job is not None and self._job.isRunning():
            self._job.cancel()
            self._job.wait(2000)
        self._player.shutdown()
        self._settings["rate"] = self._rate_slider.value()
        self._settings["pitch"] = self._pitch_slider.value()
        self._settings["volume"] = self._volume_slider.value()
        self._settings["theme"] = tm().mode
        self._settings["subtitle"] = self._subtitle_cb.isChecked()
        if self._locale_combo.currentData():
            self._settings["locale"] = self._locale_combo.currentData()
        if self._voice_combo.currentData():
            self._settings["voice"] = self._voice_combo.currentData()
        self._ai_panel.sync_settings()
        if self._ai_panel.busy or self._ai_panel.detecting or self._ai_panel.installing:
            self._ai_panel.terminate_job()
        config.save_settings(self._settings)
        super().closeEvent(e)


def _fmt(ms: int) -> str:
    if ms <= 0:
        return "0:00"
    total = int(round(ms / 1000))
    return f"{total // 60}:{total % 60:02d}"


def _fmt_span(sec: float) -> str:
    """秒 -> 人类可读时长，用于队列统计。"""
    total = int(round(sec))
    if total < 60:
        return i18n.t("dur.seconds", n=total)
    return i18n.t("dur.minutes", m=total // 60, s=total % 60)
