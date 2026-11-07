"""音频播放：调用 Windows 原生 MCI（winmm），无需 QtMultimedia 或额外解码器。

MCI 直接复用系统自带的 MP3 解码器，和「电影和电视」播放同一个文件的效果一致。
"""

from __future__ import annotations

import ctypes
import os
import random
import sys
from ctypes import wintypes

from PySide6.QtCore import QObject, QTimer, Signal

import messages

IS_WIN = sys.platform == "win32"

if IS_WIN:
    _winmm = ctypes.WinDLL("winmm")
    _winmm.mciSendStringW.argtypes = [
        wintypes.LPWSTR, wintypes.LPWSTR, wintypes.UINT, wintypes.HWND
    ]
    _winmm.mciSendStringW.restype = wintypes.UINT
    _winmm.mciGetErrorStringW.argtypes = [wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
    _winmm.mciGetErrorStringW.restype = wintypes.BOOL
else:
    _winmm = None


def _mci(command: str, alias: str) -> tuple[bool, str]:
    """执行一条 MCI 命令，返回 (成功, 返回串或错误信息)。"""
    if not IS_WIN:
        return False, "仅支持 Windows"
    buf = ctypes.create_unicode_buffer(512)
    err = _winmm.mciSendStringW(command, buf, 511, None)
    if err == 0:
        return True, buf.value.strip()
    msg = ctypes.create_unicode_buffer(512)
    _winmm.mciGetErrorStringW(err, msg, 511)
    return False, msg.value or f"MCI 错误码 {err}"


class AudioPlayer(QObject):
    """统一的播放接口：load / play / pause / stop / seek。"""

    positionChanged = Signal(int)   # 毫秒
    durationChanged = Signal(int)   # 毫秒
    playingChanged = Signal(bool)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._alias = f"vs{random.randint(100000, 999999)}"
        self._loaded = False
        self._playing = False
        self._duration = 0
        self._path = ""
        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._poll)

    # -- 状态 --------------------------------------------------------
    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def path(self) -> str:
        return self._path

    def duration(self) -> int:
        return self._duration

    def position(self) -> int:
        if not self._loaded:
            return 0
        ok, val = _mci(f"status {self._alias} position", self._alias)
        try:
            return int(val) if ok and val.isdigit() else 0
        except ValueError:
            return 0

    # -- 控制 --------------------------------------------------------
    def load(self, path: str) -> bool:
        self.stop()
        self._close()
        self._path = path
        if not os.path.exists(path):
            self.failed.emit(messages.player_no_file())
            return False
        # 加引号以支持含空格与中文的路径；type mpegvideo 覆盖 wav/mp3
        ok, info = _mci(f'open "{path}" type mpegvideo alias {self._alias}', self._alias)
        if not ok:
            ok, info = _mci(f'open "{path}" alias {self._alias}', self._alias)
        if not ok:
            self.failed.emit(messages.player_open_failed(info))
            return False
        _mci(f"set {self._alias} time format milliseconds", self._alias)
        self._loaded = True
        ok, val = _mci(f"status {self._alias} length", self._alias)
        self._duration = int(val) if ok and val.isdigit() else 0
        self.durationChanged.emit(self._duration)
        self.positionChanged.emit(0)
        return True

    def play(self) -> None:
        if not self._loaded:
            return
        ok, info = _mci(f"play {self._alias} from 0", self._alias)
        if not ok:
            # 暂停后恢复：MCI 的 resume 与 from 0 的语义不同
            ok, info = _mci(f"resume {self._alias}", self._alias)
        if not ok:
            self.failed.emit(messages.player_play_failed(info))
            return
        self._set_playing(True)

    def resume(self) -> None:
        if not self._loaded:
            return
        _mci(f"resume {self._alias}", self._alias)
        self._set_playing(True)

    def pause(self) -> None:
        if not self._loaded:
            return
        _mci(f"pause {self._alias}", self._alias)
        self._set_playing(False)

    def stop(self) -> None:
        if self._loaded:
            _mci(f"stop {self._alias}", self._alias)
            _mci(f"seek {self._alias} to start", self._alias)
        self._set_playing(False)

    def seek(self, ms: int) -> None:
        if not self._loaded:
            return
        _mci(f"seek {self._alias} to {max(0, int(ms))}", self._alias)
        self.positionChanged.emit(max(0, int(ms)))

    def toggle(self) -> None:
        if not self._loaded:
            return
        if self._playing:
            self.pause()
        elif self.position() > 0 and self.position() < max(self._duration - 200, 0):
            self.resume()
        else:
            self.play()

    # -- 内部 --------------------------------------------------------
    def _set_playing(self, playing: bool) -> None:
        if playing == self._playing:
            return
        self._playing = playing
        self.playingChanged.emit(playing)
        if playing:
            self._timer.start()
        else:
            self._timer.stop()

    def _poll(self) -> None:
        if not self._loaded:
            return
        self.positionChanged.emit(self.position())
        ok, mode = _mci(f"status {self._alias} mode", self._alias)
        if ok and mode == "stopped" and self._playing:
            self._set_playing(False)
            self.finished.emit()

    def _close(self) -> None:
        if self._loaded:
            _mci(f"close {self._alias}", self._alias)
        self._loaded = False
        self._path = ""          # 句柄已放开，不再指向任何文件
        self._timer.stop()
        self._playing = False
        self._duration = 0

    def shutdown(self) -> None:
        self._close()


def open_with_system(path: str) -> None:
    """兜底：交给系统默认播放器打开。"""
    try:
        os.startfile(path)  # type: ignore[attr-defined]
    except Exception:
        pass
