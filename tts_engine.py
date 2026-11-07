"""edge-tts 合成引擎：语音列表、合成任务、进度回调。

网络与解码全部在 QThread 里跑，UI 线程只收信号，保证拖动窗口不掉帧。
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal

import config
import i18n
import messages
import subtitles

try:
    import edge_tts

    EDGE_AVAILABLE = True
except Exception:  # pragma: no cover
    edge_tts = None
    EDGE_AVAILABLE = False


# ------------------------------------------------------------------ 离线语音表

_FALLBACK_RAW = """
zh-CN-XiaoxiaoNeural|F|zh-CN
zh-CN-XiaoyiNeural|F|zh-CN
zh-CN-YunjianNeural|M|zh-CN
zh-CN-YunxiNeural|M|zh-CN
zh-CN-YunxiaNeural|M|zh-CN
zh-CN-YunyangNeural|M|zh-CN
zh-CN-liaoning-XiaobeiNeural|F|zh-CN
zh-CN-shaanxi-XiaoniNeural|F|zh-CN
zh-TW-HsiaoChenNeural|F|zh-TW
zh-TW-HsiaoYuNeural|F|zh-TW
zh-TW-YunJheNeural|M|zh-TW
zh-HK-HiuGaaiNeural|F|zh-HK
zh-HK-HiuMaanNeural|F|zh-HK
zh-HK-WanLungNeural|M|zh-HK
en-US-AriaNeural|F|en-US
en-US-JennyNeural|F|en-US
en-US-MichelleNeural|F|en-US
en-US-AnaNeural|F|en-US
en-US-GuyNeural|M|en-US
en-US-DavisNeural|M|en-US
en-US-AndrewNeural|M|en-US
en-US-BrianNeural|M|en-US
en-US-ChristopherNeural|M|en-US
en-US-EricNeural|M|en-US
en-US-RogerNeural|M|en-US
en-US-SteffanNeural|M|en-US
en-GB-LibbyNeural|F|en-GB
en-GB-MaisieNeural|F|en-GB
en-GB-SoniaNeural|F|en-GB
en-GB-RyanNeural|M|en-GB
en-GB-ThomasNeural|M|en-GB
ja-JP-NanamiNeural|F|ja-JP
ja-JP-KeitaNeural|M|ja-JP
ko-KR-SunHiNeural|F|ko-KR
ko-KR-InJoonNeural|M|ko-KR
ko-KR-BongJinNeural|M|ko-KR
fr-FR-DeniseNeural|F|fr-FR
fr-FR-HenriNeural|M|fr-FR
de-DE-KatjaNeural|F|de-DE
de-DE-ConradNeural|M|de-DE
es-ES-ElviraNeural|F|es-ES
es-ES-AlvaroNeural|M|es-ES
ru-RU-SvetlanaNeural|F|ru-RU
ru-RU-DmitryNeural|M|ru-RU
pt-BR-FranciscaNeural|F|pt-BR
pt-BR-AntonioNeural|M|pt-BR
it-IT-ElsaNeural|F|it-IT
it-IT-DiegoNeural|M|it-IT
"""


def _uniq_list(items) -> list[str]:
    """VoiceTag 里同一风格可能同时出现在两个字段，去重且去掉泛味精的 General。"""
    out: list[str] = []
    for it in items or []:
        s = str(it).strip()
        if not s or s.lower() == "general":
            continue
        if s not in out:
            out.append(s)
    return out


def _fallback_voices() -> list[dict]:
    voices = []
    for line in _FALLBACK_RAW.strip().splitlines():
        short, gender, locale = line.strip().split("|")
        voices.append(
            {"short": short, "gender": gender, "locale": locale, "friendly": "", "styles": []}
        )
    return voices


LOCALE_LABELS = {
    "zh-CN": "中文（简体）",
    "zh-CN-liaoning": "中文（简体·辽宁）",
    "zh-CN-shaanxi": "中文（简体·陕西）",
    "zh-TW": "中文（台湾）",
    "zh-HK": "中文（粤语·香港）",
    "en-US": "English (US)",
    "en-GB": "English (UK)",
    "en-AU": "English (AU)",
    "en-CA": "English (CA)",
    "en-IN": "English (IN)",
    "en-NZ": "English (NZ)",
    "en-IE": "English (IE)",
    "ja-JP": "日本語",
    "ko-KR": "한국어",
    "fr-FR": "Français",
    "fr-CA": "Français (CA)",
    "de-DE": "Deutsch",
    "es-ES": "Español",
    "es-MX": "Español (MX)",
    "ru-RU": "Русский",
    "pt-BR": "Português (BR)",
    "pt-PT": "Português (PT)",
    "it-IT": "Italiano",
    "nl-NL": "Nederlands",
    "pl-PL": "Polski",
    "tr-TR": "Türkçe",
    "ar-SA": "العربية",
    "th-TH": "ไทย",
    "vi-VN": "Tiếng Việt",
    "id-ID": "Bahasa Indonesia",
    "ms-MY": "Bahasa Melayu",
    "hi-IN": "हिन्दी",
    "sv-SE": "Svenska",
    "da-DK": "Dansk",
    "nb-NO": "Norsk",
    "fi-FI": "Suomi",
    "cs-CZ": "Čeština",
    "el-GR": "Ελληνικά",
    "he-IL": "עברית",
    "hu-HU": "Magyar",
    "uk-UA": "Українська",
}


# 英文界面下语言下拉/语音列表里显示的名字。键与 LOCALE_LABELS 一致，
# 表里没有的新语言回退成 BCP-47 代码（例如 "xx-YY"），不会显示成空白。
LOCALE_LABELS_EN = {
    "zh-CN": "Chinese (Simplified)",
    "zh-CN-liaoning": "Chinese (Simplified, Liaoning)",
    "zh-CN-shaanxi": "Chinese (Simplified, Shaanxi)",
    "zh-TW": "Chinese (Taiwan)",
    "zh-HK": "Chinese (Cantonese, Hong Kong)",
    "ja-JP": "Japanese",
    "ko-KR": "Korean",
    "fr-FR": "French",
    "fr-CA": "French (CA)",
    "de-DE": "German",
    "es-ES": "Spanish",
    "es-MX": "Spanish (MX)",
    "ru-RU": "Russian",
    "pt-BR": "Portuguese (BR)",
    "pt-PT": "Portuguese (PT)",
    "it-IT": "Italian",
    "nl-NL": "Dutch",
    "pl-PL": "Polish",
    "tr-TR": "Turkish",
    "ar-SA": "Arabic",
    "th-TH": "Thai",
    "vi-VN": "Vietnamese",
    "id-ID": "Indonesian",
    "ms-MY": "Malay",
    "hi-IN": "Hindi",
    "sv-SE": "Swedish",
    "da-DK": "Danish",
    "nb-NO": "Norwegian",
    "fi-FI": "Finnish",
    "cs-CZ": "Czech",
    "el-GR": "Greek",
    "he-IL": "Hebrew",
    "hu-HU": "Hungarian",
    "uk-UA": "Ukrainian",
}


def locale_label(locale: str) -> str:
    if i18n.lang() == "en":
        return LOCALE_LABELS_EN.get(locale, locale)
    return LOCALE_LABELS.get(locale, locale)


def gender_label(gender: str) -> str:
    if i18n.lang() == "en":
        return {
            "F": "Female",
            "Female": "Female",
            "M": "Male",
            "Male": "Male",
        }.get(gender, "Unknown")
    return {
        "F": "女",
        "M": "男",
        "Female": "女",
        "Male": "男",
    }.get(gender, gender or "未知")


def voice_display(voice: dict) -> str:
    """zh-CN-XiaoxiaoNeural -> 晓晓？不必造映射，直接显示 Xiaoxiao · 女。"""
    short = voice.get("short", "")
    locale = voice.get("locale", "")
    name = short[len(locale) + 1:] if locale and short.startswith(locale + "-") else short
    if name.endswith("Neural"):
        name = name[:-6]
    return f"{name} · {gender_label(voice.get('gender', ''))}"


# ------------------------------------------------------------------ 语音列表


def load_cached_voices() -> list[dict]:
    try:
        if config.VOICE_CACHE.exists():
            payload = json.loads(config.VOICE_CACHE.read_text(encoding="utf-8"))
            voices = payload.get("voices", [])
            if voices:
                # 老版本缓存里没有 styles 字段：补齐，别让读缓存的地方拿到 KeyError
                for v in voices:
                    v.setdefault("styles", [])
                    v.setdefault("friendly", "")
                return voices
    except Exception:
        pass
    return _fallback_voices()


def _save_cache(voices: list[dict]) -> None:
    try:
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        config.VOICE_CACHE.write_text(
            json.dumps({"fetched_at": time.time(), "voices": voices}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


class VoiceLoader(QThread):
    """在线拉取语音列表；失败时 UI 继续用缓存/内置表，不阻塞启动。"""

    loaded = Signal(list)
    failed = Signal(str)

    def run(self) -> None:
        if not EDGE_AVAILABLE:
            self.failed.emit(messages.EDGE_MISSING)
            return
        try:
            raw = asyncio.run(edge_tts.list_voices())
        except Exception as exc:
            self.failed.emit(_friendly_error(exc))
            return
        voices = []
        for v in raw:
            short = v.get("ShortName", "")
            if not short:
                continue
            tag = v.get("VoiceTag") or {}
            styles = _uniq_list(tag.get("ContentCategories")) + _uniq_list(
                tag.get("VoicePersonalities")
            )
            voices.append(
                {
                    "short": short,
                    "locale": v.get("Locale", ""),
                    "gender": v.get("Gender", ""),
                    "friendly": v.get("FriendlyName", ""),
                    "styles": styles,
                }
            )
        voices.sort(key=lambda r: (r["locale"] != "zh-CN", r["locale"], r["short"]))
        _save_cache(voices)
        self.loaded.emit(voices)


# ------------------------------------------------------------------ 合成任务


def estimate_seconds(text: str) -> float:
    """粗略估计音频时长，用于把流式进度换算成百分比。"""
    cjk = 0
    other = 0
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            cjk += 1
        elif ch.strip():
            other += 1
    return max(1.5, cjk / 4.2 + other / 13.0)


def _pct(value: int) -> str:
    return f"{value:+d}%"


def _hz(value: int) -> str:
    return f"{value:+d}Hz"


def _friendly_error(exc: BaseException) -> str:
    """保留这个薄包装，文案表本身在 messages.py。"""
    return messages.friendly_error(exc)


@dataclass
class SynthRequest:
    text: str
    voice: str
    out_path: str
    rate: int = 0
    pitch: int = 0
    volume: int = 0
    subtitle: bool = False


class SynthJob(QThread):
    """把一个 SynthRequest 合成成 MP3，可选同时导出同名 SRT 字幕。

    同时通过 SentenceBoundary 事件（每句一条，offset 单位 100ns）回传进度，
    并把这些事件攒下来生成字幕。
    """

    progress = Signal(int)
    succeeded = Signal(str, str)  # (音频路径, 字幕路径或空串)
    failed = Signal(str)

    def __init__(self, request: SynthRequest, parent=None):
        super().__init__(parent)
        self._req = request
        self._cancel = threading.Event()
        self._cues: list[tuple[float, float, str]] = []

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def request(self) -> SynthRequest:
        return self._req

    @property
    def cues(self) -> list[tuple[float, float, str]]:
        """最后一次合成的字幕时间轴 (start_sec, end_sec, text)。"""
        return list(self._cues)

    def run(self) -> None:
        if not EDGE_AVAILABLE:
            self.failed.emit(messages.EDGE_MISSING_JOB)
            return
        try:
            asyncio.run(self._run())
        except BaseException as exc:  # noqa: BLE001 - 线程里必须兜住所有异常
            if self._cancel.is_set():
                return
            self.failed.emit(_friendly_error(exc))

    async def _run(self) -> None:
        req = self._req
        est = estimate_seconds(req.text)
        timeout_sec = 30 + est * 5
        tmp_path = req.out_path + ".part"
        os.makedirs(os.path.dirname(os.path.abspath(req.out_path)), exist_ok=True)

        communicate = edge_tts.Communicate(
            req.text,
            req.voice,
            rate=_pct(req.rate),
            pitch=_hz(req.pitch),
            volume=_pct(req.volume),
            boundary="SentenceBoundary",
        )
        total_bytes = 0
        last_pct = 0
        self._cues.clear()
        stream = communicate.stream()
        try:
            with open(tmp_path, "wb") as fh:
                async with asyncio.timeout(timeout_sec):
                    async for chunk in stream:
                        if self._cancel.is_set():
                            break
                        kind = chunk.get("type")
                        if kind == "audio":
                            data = chunk.get("data") or b""
                            fh.write(data)
                            total_bytes += len(data)
                            continue
                        if kind in ("SentenceBoundary", "WordBoundary"):
                            offset_s = chunk.get("offset", 0) / 10_000_000
                            duration_s = chunk.get("duration", 0) / 10_000_000
                            self._cues.append(
                                (offset_s, offset_s + duration_s, chunk.get("text", ""))
                            )
                            pct = int(min(96, (offset_s / est) * 100))
                            if pct > last_pct:
                                last_pct = pct
                                self.progress.emit(pct)
        except BaseException:
            _silent_remove(tmp_path)
            raise
        finally:
            # 取消时提前 break 会让 async generator 挂在那里，
            # 内部的 aiohttp ClientSession 就不会关闭（日志里的 Unclosed client session）。
            # 显式 aclose 让它走完 async with 的善后。
            try:
                await stream.aclose()
            except Exception:
                pass

        if self._cancel.is_set():
            _silent_remove(tmp_path)
            return
        if total_bytes == 0:
            _silent_remove(tmp_path)
            raise RuntimeError("NoAudioReceived")

        # 目标文件可能刚被播放器/杀软占着，短重试几次再放弃
        last_error: BaseException | None = None
        for attempt in range(3):
            try:
                os.replace(tmp_path, req.out_path)
                last_error = None
                break
            except PermissionError as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.2)
        if last_error is not None:
            _silent_remove(tmp_path)
            raise last_error

        srt_path = ""
        if req.subtitle and self._cues:
            candidate = os.path.splitext(req.out_path)[0] + ".srt"
            try:
                subtitles.write_srt(self._cues, candidate)
                srt_path = candidate
            except OSError:
                srt_path = ""

        self.progress.emit(100)
        self.succeeded.emit(req.out_path, srt_path)


def _silent_remove(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def preview_path() -> str:
    config.ensure_dirs()
    return str(config.STATE_DIR / "preview.mp3")
