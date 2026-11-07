"""配置与路径。

用户可写的状态（语音缓存、上次的选择）放 %LOCALAPPDATA%，成品放项目下的 output/。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "Voice Studio"
APP_ID = "EdgeTTS.VoiceStudio.1"

# 打包成 exe 后 __file__ 指向 PyInstaller 的临时解包目录，用 exe 所在目录才对
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
STATE_DIR = Path(os.environ.get("LOCALAPPDATA", str(ROOT))) / "EdgeTTSStudio"
VOICE_CACHE = STATE_DIR / "voices.json"
SETTINGS_FILE = STATE_DIR / "settings.json"

DEFAULTS = {
    "locale": "zh-CN",
    "voice": "zh-CN-XiaoxiaoNeural",
    "rate": 0,
    "pitch": 0,
    "volume": 0,
    "theme": "system",
    "lang": "zh",
    "subtitle": False,
    "output_dir": str(OUTPUT_DIR),
    # AI 扩写：provider = ark（火山方舟 / 豆包）或 ollama（本机模型）
    "ai_provider": "ark",
    "ai_base": "https://ark.cn-beijing.volces.com/api/v3",
    "ai_key": "",
    "ai_model": "",
    "ai_ollama_base": "http://localhost:11434",
    "ai_ollama_model": "",
    "ai_style": "natural",
    "ai_chars": 200,
}


def ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict:
    data = dict(DEFAULTS)
    try:
        if SETTINGS_FILE.exists():
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data.update({k: v for k, v in raw.items() if k in DEFAULTS})
    except Exception:
        pass
    return data


def save_settings(data: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {k: data.get(k, DEFAULTS[k]) for k in DEFAULTS}
        SETTINGS_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass
