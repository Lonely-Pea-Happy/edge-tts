"""Fluent 图标：全部用 QPainter 在 16×16 设计网格里矢量绘制。

不依赖图标字体或外部资源文件，因此换色、换主题、缩放到任意 DPI 都清晰。
"""

from __future__ import annotations

import math

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

DESIGN = 16.0


def _draw(p: QPainter, kind: str, color: QColor, pen: QPen) -> None:
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    if kind == "play":
        path = QPainterPath()
        path.moveTo(4.8, 3.0)
        path.lineTo(12.6, 8.0)
        path.lineTo(4.8, 13.0)
        path.closeSubpath()
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawPath(path)

    elif kind == "pause":
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(4.2, 3.2, 2.6, 9.6), 0.8, 0.8)
        p.drawRoundedRect(QRectF(9.2, 3.2, 2.6, 9.6), 0.8, 0.8)

    elif kind == "stop":
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(4.2, 4.2, 7.6, 7.6), 1.2, 1.2)

    elif kind == "save":  # 向下箭头入托盘
        p.drawLine(QPointF(8, 2.4), QPointF(8, 9.6))
        path = QPainterPath()
        path.moveTo(4.8, 6.4)
        path.lineTo(8, 9.7)
        path.lineTo(11.2, 6.4)
        p.drawPath(path)
        p.drawLine(QPointF(3.2, 13.2), QPointF(12.8, 13.2))

    elif kind == "folder":
        path = QPainterPath()
        path.moveTo(2.4, 5.6)
        path.lineTo(2.4, 12.2)
        path.lineTo(13.6, 12.2)
        path.lineTo(13.6, 5.6)
        path.lineTo(8.2, 5.6)
        path.lineTo(6.8, 3.6)
        path.lineTo(2.4, 3.6)
        path.closeSubpath()
        p.drawPath(path)

    elif kind == "chevron_down":
        path = QPainterPath()
        path.moveTo(4.4, 6.2)
        path.lineTo(8, 9.8)
        path.lineTo(11.6, 6.2)
        p.drawPath(path)

    elif kind == "close":
        p.drawLine(QPointF(3.8, 3.8), QPointF(12.2, 12.2))
        p.drawLine(QPointF(12.2, 3.8), QPointF(3.8, 12.2))

    elif kind == "min":
        p.drawLine(QPointF(3.8, 8), QPointF(12.2, 8))

    elif kind == "max":
        p.drawRect(QRectF(4.2, 4.2, 7.6, 7.6))

    elif kind == "restore":
        p.drawRect(QRectF(2.8, 5.8, 7.0, 7.0))
        p.drawRect(QRectF(6.2, 3.2, 7.0, 7.0))

    elif kind == "sun":
        p.drawEllipse(QPointF(8, 8), 3.0, 3.0)
        for i in range(8):
            import math

            ang = math.radians(i * 45)
            p.drawLine(
                QPointF(8 + 4.6 * math.cos(ang), 8 + 4.6 * math.sin(ang)),
                QPointF(8 + 6.2 * math.cos(ang), 8 + 6.2 * math.sin(ang)),
            )

    elif kind == "moon":
        outer = QPainterPath()
        outer.addEllipse(QPointF(9.0, 8.0), 4.6, 4.6)
        cut = QPainterPath()
        cut.addEllipse(QPointF(12.2, 4.4), 5.0, 5.0)
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawPath(outer.subtracted(cut))

    elif kind == "refresh":
        path = QPainterPath()
        path.arcMoveTo(QRectF(3.2, 3.2, 9.6, 9.6), 55)
        path.arcTo(QRectF(3.2, 3.2, 9.6, 9.6), 55, 290)
        p.drawPath(path)
        head = QPainterPath()
        head.moveTo(11.0, 1.9)
        head.lineTo(12.6, 4.6)
        head.lineTo(9.5, 4.9)
        p.drawPath(head)

    elif kind == "clear":  # 垃圾桶
        p.drawLine(QPointF(3.4, 4.8), QPointF(12.6, 4.8))
        p.drawLine(QPointF(6.4, 4.8), QPointF(6.4, 2.8))
        p.drawLine(QPointF(6.4, 2.8), QPointF(9.6, 2.8))
        p.drawLine(QPointF(9.6, 2.8), QPointF(9.6, 4.8))
        path = QPainterPath()
        path.moveTo(4.6, 5.4)
        path.lineTo(5.2, 13.2)
        path.lineTo(10.8, 13.2)
        path.lineTo(11.4, 5.4)
        p.drawPath(path)

    elif kind == "sparkle":  # 示例文本
        for dx, dy, r in ((5.0, 5.0, 2.2), (11.2, 4.2, 1.3), (9.4, 11.0, 1.6)):
            star = QPainterPath()
            star.moveTo(dx, dy - r)
            star.lineTo(dx + r * 0.55, dy - r * 0.35)
            star.lineTo(dx + r, dy)
            star.lineTo(dx + r * 0.55, dy + r * 0.35)
            star.lineTo(dx, dy + r)
            star.lineTo(dx - r * 0.55, dy + r * 0.35)
            star.lineTo(dx - r, dy)
            star.lineTo(dx - r * 0.55, dy - r * 0.35)
            star.closeSubpath()
            p.setBrush(color)
            p.setPen(Qt.NoPen)
            p.drawPath(star)

    elif kind == "check":  # 勾选
        path = QPainterPath()
        path.moveTo(3.1, 8.5)
        path.lineTo(6.4, 11.6)
        path.lineTo(12.9, 4.4)
        p.drawPath(path)

    elif kind == "queue":  # 队列：三条横线，最后一条短一截
        for y, x2 in ((4.0, 13.5), (8.0, 13.5), (12.0, 9.5)):
            p.drawLine(QLineF(2.5, y, x2, y))

    elif kind == "speaker":
        path = QPainterPath()
        path.moveTo(2.6, 6.2)
        path.lineTo(5.2, 6.2)
        path.lineTo(8.4, 3.2)
        path.lineTo(8.4, 12.8)
        path.lineTo(5.2, 9.8)
        path.lineTo(2.6, 9.8)
        path.closeSubpath()
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawPath(path)
        p.setBrush(Qt.NoBrush)
        p.setPen(pen)
        p.drawArc(QRectF(7.4, 4.2, 7.0, 7.6), -55 * 16, 110 * 16)

    elif kind == "language":  # 地球：外圈 + 竖经线 + 赤道
        p.drawEllipse(QPointF(8, 8), 5.6, 5.6)
        p.drawEllipse(QPointF(8, 8), 2.3, 5.6)
        p.drawLine(QPointF(2.6, 8), QPointF(13.4, 8))

    else:  # 兜底：一个小圆点，便于发现漏画的图标名
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(8, 8), 2.0, 2.0)


def paint(p: QPainter, kind: str, rect: QRectF, color: QColor, weight: float = 1.4) -> None:
    """把图标画进 rect（正方形区域，按中心对齐）。"""
    side = min(rect.width(), rect.height())
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    p.translate(rect.center().x() - side / 2.0, rect.center().y() - side / 2.0)
    p.scale(side / DESIGN, side / DESIGN)
    pen = QPen(color)
    pen.setWidthF(weight)
    pen.setCapStyle(Qt.FlatCap)
    pen.setJoinStyle(Qt.MiterJoin)
    _draw(p, kind, color, pen)
    p.restore()


def pixmap(kind: str, color: QColor, size: int = 16, dpr: float = 2.0) -> QPixmap:
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    paint(p, kind, QRectF(0, 0, size, size), color)
    p.end()
    return pm


def app_icon(size: int = 64) -> QIcon:
    """程序图标：强调色圆角方块 + 白色声波。"""
    from theme import tm

    px = QPixmap(size, size)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing, True)
    accent = tm().theme.c("accent")
    p.setBrush(accent)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.16, size * 0.16)
    # 五根高低不同的声波
    heights = (0.22, 0.44, 0.62, 0.44, 0.22)
    bar_w = size * 0.055
    gap = size * 0.075
    total_w = 5 * bar_w + 4 * gap
    x = (size - total_w) / 2
    p.setBrush(QColor("#FFFFFFFF"))
    for h in heights:
        bar_h = size * h
        p.drawRoundedRect(
            QRectF(x, (size - bar_h) / 2, bar_w, bar_h), bar_w / 2, bar_w / 2
        )
        x += bar_w + gap
    p.end()
    return QIcon(px)
