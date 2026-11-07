"""入口：文字转语音 · Voice Studio（Windows 11 Fluent 界面 + edge-tts 引擎）。

运行：python main.py
"""

from __future__ import annotations

import sys
import traceback


def _install_excepthook() -> None:
    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        # 打包成无控制台 exe 后，报错没地方看；顺手留一份到状态目录
        if getattr(sys, "frozen", False):
            try:
                import config
                config.STATE_DIR.mkdir(parents=True, exist_ok=True)
                (config.STATE_DIR / "crash.log").write_text(text, encoding="utf-8")
            except Exception:
                pass
        traceback.print_exception(exc_type, exc, tb)

    sys.excepthook = hook


def main() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    _install_excepthook()

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    import config
    import win_utils

    config.ensure_dirs()
    win_utils.set_app_user_model_id(config.APP_ID)

    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setApplicationDisplayName(config.APP_NAME)
    app.setQuitOnLastWindowClosed(True)

    import glyphs
    from theme import tm, ui_font

    app.setWindowIcon(glyphs.app_icon(256))
    app.setFont(ui_font(14))

    # 提示框自己画：Qt 的 QToolTip 在这套自绘窗口里只会画出一块黑（见 tooltip.py 顶部说明）
    import tooltip

    tips = tooltip.install(app)
    tm().changed.connect(tips.restyle)


    # 系统切换浅色/深色时，若处于「跟随系统」立刻跟随
    try:
        QGuiApplication.paletteChanged.connect(lambda *_: tm().follow_system_change())
    except Exception:
        pass

    from main_window import MainWindow

    window = MainWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
