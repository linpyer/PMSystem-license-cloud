from __future__ import annotations

import base64
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
import winsound
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.version import APP_DATA_DIR_NAME


VOICE_PROMPT_EVENTS: tuple[tuple[str, str, str], ...] = (
    ("start", "开始录制提示音", "start"),
    ("stop", "结束录制提示音", "stop"),
    ("switch", "切换录制提示音", "switch"),
    ("duplicate", "重复录制提示音", "duplicate"),
    ("no_order", "未输入单号提示音", "no_order"),
    ("camera_refresh", "摄像头刷新提示音", "camera_refresh"),
    ("video_missing", "视频文件不存在提示音", "video_missing"),
    ("save_failed", "保存失败提示音", "save_failed"),
    ("save_success", "配置保存成功提示音", "save_success"),
    ("list_refresh", "列表刷新提示音", "list_refresh"),
)

VOICE_EVENT_KEYS = tuple(item[0] for item in VOICE_PROMPT_EVENTS)
SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac"}

DEFAULT_SYSTEM_TEXT: dict[str, str] = {
    "start": "已开始录制",
    "stop": "录制已结束",
    "switch": "已切换录制",
    "duplicate": "单号已录过",
    "no_order": "请先输入或扫描单号",
    "camera_refresh": "摄像头已刷新",
    "video_missing": "视频文件不存在",
    "save_failed": "保存失败",
    "save_success": "配置已保存",
    "list_refresh": "列表已刷新",
}
LEGACY_NO_ORDER_PROMPT = "请先输入或扫描" + "物流" + "单号"
CURRENT_NO_ORDER_PROMPT = "请先输入或扫描单号"

LEGACY_TEXT_KEYS = {
    "start_text": "start",
    "stop_text": "stop",
    "switch_text": "switch",
    "duplicate_text": "duplicate",
}


def default_custom_voice_dir() -> str:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base_dir = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return str(base_dir / APP_DATA_DIR_NAME / "voice")


DEFAULT_VOICE_PROMPT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "mode": "system",
    "custom_voice_dir": default_custom_voice_dir(),
    "custom_files": {key: "" for key in VOICE_EVENT_KEYS},
    "system_text": dict(DEFAULT_SYSTEM_TEXT),
}


@dataclass(frozen=True)
class _VoiceRequest:
    kind: str
    payload: str
    triggered_at: float
    event_key: str = ""


class VoicePrompt:
    def __init__(self, config: dict[str, Any], logger: logging.Logger) -> None:
        self.logger = logger
        self._queue: queue.Queue[_VoiceRequest | None] = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._config_lock = threading.Lock()
        self._backend_lock = threading.Lock()
        self._worker_lock = threading.Lock()
        self._config = self.normalize_config(config)
        self._backend_name = "initializing"
        self._last_error = ""
        self._speak_count = 0
        self._worker: threading.Thread | None = None
        self.logger.info(
            "VoicePrompt 实例创建 id=%s, enabled=%s, mode=%s",
            id(self),
            self._config.get("enabled", True),
            self._config.get("mode", "system"),
        )
        self.ensure_worker()

    def update_config(self, config: dict[str, Any]) -> None:
        with self._config_lock:
            self._config = self.normalize_config(config)
        self.logger.info(
            "语音配置已更新：enabled=%s, mode=%s, custom_voice_dir=%s",
            self._config.get("enabled", True),
            self._config.get("mode", "system"),
            self._config.get("custom_voice_dir", ""),
        )

    def play(self, event_key: str) -> bool:
        config = self._current_config()
        event_key = str(event_key or "").strip()
        if event_key not in VOICE_EVENT_KEYS:
            self.logger.warning("未知语音事件，跳过播放：%s", event_key)
            return False

        if not self._can_play(config):
            self.logger.info("语音提示已关闭，跳过事件播放：%s", event_key)
            return False

        mode = str(config.get("mode", "system") or "system")
        if mode == "custom":
            audio_path = str(config.get("custom_files", {}).get(event_key, "") or "").strip()
            if audio_path and Path(audio_path).exists():
                return self.play_audio_file(audio_path, event_key=event_key)
            self.logger.warning("自定义语音文件未设置或不存在，回退系统语音：event=%s, path=%s", event_key, audio_path)

        text = str(config.get("system_text", {}).get(event_key, "") or "").strip()
        return self.speak(text, event_key=event_key, respect_mode=False)

    def speak(self, text: str, event_key: str = "", respect_mode: bool = True) -> bool:
        self._speak_count += 1
        config = self._current_config()
        enabled = self._can_play(config)
        if respect_mode and str(config.get("mode", "system")) == "custom":
            self.logger.info("当前为自定义语音包模式，直接文本播报作为系统语音兜底处理")
        text = str(text or "").strip()
        self.logger.info(
            "speak 被调用：count=%s, enabled=%s, text_empty=%s, worker_alive=%s, backend=%s, event=%s, text=%s",
            self._speak_count,
            enabled,
            not bool(text),
            self.is_worker_alive(),
            self.backend_name(),
            event_key,
            text,
        )
        if not enabled:
            self.logger.info("语音提示已关闭，跳过播放")
            return False
        if not text:
            self.logger.warning("语音文本为空，跳过播放")
            return False
        return self._enqueue(_VoiceRequest("tts", text, time.perf_counter(), event_key))

    def play_audio_file(self, file_path: str | Path, event_key: str = "") -> bool:
        config = self._current_config()
        if not self._can_play(config):
            self.logger.info("语音提示已关闭，跳过自定义音频播放：%s", file_path)
            return False
        path = Path(file_path)
        if not path.exists():
            self.logger.warning("自定义语音文件不存在：%s", path)
            return False
        if path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
            self.logger.warning("自定义语音文件格式不支持：%s", path)
            return False
        return self._enqueue(_VoiceRequest("audio", str(path), time.perf_counter(), event_key))

    def speak_start(self) -> bool:
        self.logger.info("录制开始触发语音")
        return self.play("start")

    def speak_stop(self) -> bool:
        self.logger.info("录制结束触发语音")
        return self.play("stop")

    def speak_switch(self) -> bool:
        self.logger.info("切换录制触发语音")
        return self.play("switch")

    def speak_duplicate(self) -> bool:
        self.logger.info("重复录制触发语音")
        return self.play("duplicate")

    def set_enabled(self, enabled: bool) -> None:
        with self._config_lock:
            self._config["enabled"] = bool(enabled)

    def is_enabled(self) -> bool:
        return self._can_play(self._current_config())

    def backend_name(self) -> str:
        with self._backend_lock:
            return self._backend_name

    def last_error(self) -> str:
        with self._backend_lock:
            return self._last_error

    def is_available(self) -> bool:
        return self.backend_name() not in {"initializing", "none"}

    def is_worker_alive(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def ensure_worker(self) -> bool:
        with self._worker_lock:
            if self._worker is not None and self._worker.is_alive():
                self.logger.info("语音线程健康检查：alive=True, ident=%s", self._worker.ident)
                return True
            if self._stop_event.is_set():
                self.logger.error("语音线程重启失败：VoicePrompt 正在关闭")
                return False
            try:
                self._set_backend("initializing")
                self._worker = threading.Thread(target=self._run, name="VoicePromptWorker", daemon=True)
                self._worker.start()
                self.logger.info("语音线程已重启：alive=%s, ident=%s", self._worker.is_alive(), self._worker.ident)
                return self._worker.is_alive()
            except Exception as exc:
                self._set_last_error(str(exc))
                self.logger.exception("语音线程重启失败：%s", exc)
                return False

    def wait_until_idle(self, timeout_seconds: float = 5.0) -> bool:
        deadline = time.perf_counter() + timeout_seconds
        while time.perf_counter() < deadline:
            if self._queue.unfinished_tasks == 0:
                return True
            time.sleep(0.05)
        return self._queue.unfinished_tasks == 0

    def stop(self) -> None:
        self._stop_event.set()
        self._clear_pending()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._worker is not None:
            self._worker.join(timeout=2)

    def _enqueue(self, request: _VoiceRequest) -> bool:
        if not self.ensure_worker():
            self.logger.error("语音线程不可用，跳过播放请求：%s", request)
            return False
        try:
            self._clear_pending()
            self._queue.put_nowait(request)
            self.logger.info(
                "语音请求已入队：kind=%s, event=%s, payload=%s, queue_size=%s",
                request.kind,
                request.event_key,
                request.payload,
                self._queue.qsize(),
            )
            return True
        except Exception:
            self.logger.exception("语音提示入队失败")
            return False

    def _run(self) -> None:
        tts_backend: _SpeechBackend | None = None
        self.logger.info("语音工作线程进入运行：ident=%s", threading.get_ident())
        self._set_backend("ready")
        try:
            while not self._stop_event.is_set():
                request = self._queue.get()
                if request is None:
                    self._queue.task_done()
                    break

                started_at = time.perf_counter()
                self.logger.info(
                    "语音开始播放：kind=%s, event=%s, delay_ms=%.1f, payload=%s",
                    request.kind,
                    request.event_key,
                    (started_at - request.triggered_at) * 1000,
                    request.payload,
                )
                try:
                    if request.kind == "audio":
                        CustomAudioBackend(self.logger).speak(request.payload)
                    else:
                        if tts_backend is None:
                            tts_backend = self._init_tts_backend()
                        tts_backend.speak(request.payload)
                    self.logger.info(
                        "语音播放完成：kind=%s, event=%s, elapsed_ms=%.1f",
                        request.kind,
                        request.event_key,
                        (time.perf_counter() - started_at) * 1000,
                    )
                except Exception as exc:
                    self._set_last_error(str(exc))
                    self.logger.exception("语音播放失败：kind=%s, event=%s, payload=%s", request.kind, request.event_key, request.payload)
                    if request.kind == "tts":
                        try:
                            if tts_backend is not None:
                                tts_backend.close()
                        except Exception:
                            self.logger.exception("语音播放失败后关闭 TTS 后端失败")
                        tts_backend = self._init_tts_backend()
                        self._try_fallback_speak(request.payload)
                finally:
                    self._queue.task_done()
                    self.logger.info("播放完成后 worker 继续等待下一条语音")
        except Exception as exc:
            self._set_backend("none")
            self._set_last_error(str(exc))
            self.logger.exception("worker 异常退出原因：%s", exc)
        finally:
            if tts_backend is not None:
                try:
                    tts_backend.close()
                except Exception as exc:
                    self._set_last_error(str(exc))
                    self.logger.exception("语音模块关闭失败")

    def _init_tts_backend(self) -> "_SpeechBackend":
        try:
            backend = Pyttsx3SpeechBackend(self.logger)
            self._set_backend("pyttsx3")
            self.logger.info("pyttsx3 语音引擎初始化成功")
            self.logger.info("当前使用的语音引擎类型：pyttsx3")
            return backend
        except Exception as pyttsx3_exc:
            self._set_last_error(str(pyttsx3_exc))
            self.logger.exception("pyttsx3 初始化失败：%s", pyttsx3_exc)

        try:
            backend = SapiSpeechBackend(self.logger)
            self._set_backend("sapi")
            self.logger.info("Windows SAPI 初始化成功")
            self.logger.info("当前使用的语音引擎类型：sapi")
            return backend
        except Exception as sapi_exc:
            self._set_last_error(str(sapi_exc))
            self.logger.exception("Windows SAPI 初始化失败：%s", sapi_exc)

        if shutil.which("powershell"):
            self._set_backend("powershell")
            self.logger.info("当前使用的语音引擎类型：powershell")
            return PowerShellSpeechBackend(self.logger)

        self._set_backend("none")
        self._set_last_error("没有可用语音后端")
        self.logger.error("当前使用的语音引擎类型：none")
        return NullSpeechBackend(self.logger)

    def _try_fallback_speak(self, text: str) -> None:
        try:
            if self.backend_name() != "sapi":
                self.logger.info("尝试 Windows SAPI 兜底播放")
                SapiSpeechBackend(self.logger).speak_and_close(text)
                return
        except Exception as sapi_exc:
            self._set_last_error(str(sapi_exc))
            self.logger.exception("Windows SAPI 兜底播放失败")
        try:
            self.logger.info("尝试 PowerShell 兜底播放")
            PowerShellSpeechBackend(self.logger).speak(text)
        except Exception as ps_exc:
            self._set_last_error(str(ps_exc))
            self.logger.exception("PowerShell 兜底播放失败")

    def _clear_pending(self) -> None:
        while True:
            try:
                old_item = self._queue.get_nowait()
                self._queue.task_done()
                if old_item is not None:
                    self.logger.info("清空未播放语音：kind=%s, payload=%s", old_item.kind, old_item.payload)
            except queue.Empty:
                break

    def _current_config(self) -> dict[str, Any]:
        with self._config_lock:
            return {
                **self._config,
                "custom_files": dict(self._config.get("custom_files", {})),
                "system_text": dict(self._config.get("system_text", {})),
            }

    def _set_backend(self, backend_name: str) -> None:
        with self._backend_lock:
            self._backend_name = backend_name

    def _set_last_error(self, message: str) -> None:
        with self._backend_lock:
            self._last_error = message

    @staticmethod
    def _can_play(config: dict[str, Any]) -> bool:
        return bool(config.get("enabled", True)) and str(config.get("mode", "system")) != "off"

    @staticmethod
    def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
        raw = config.get("voice_prompt", {}) if isinstance(config, dict) else {}
        raw = raw if isinstance(raw, dict) else {}

        merged = {
            "enabled": True,
            "mode": "system",
            "custom_voice_dir": default_custom_voice_dir(),
            "custom_files": {key: "" for key in VOICE_EVENT_KEYS},
            "system_text": dict(DEFAULT_SYSTEM_TEXT),
        }

        enabled = bool(raw.get("enabled", True))
        mode = str(raw.get("mode", "system") or "system")
        if mode == "off":
            enabled = False
            mode = "system"
        if mode not in {"system", "custom"}:
            mode = "system"

        system_text = dict(DEFAULT_SYSTEM_TEXT)
        if isinstance(raw.get("system_text"), dict):
            for key, value in raw["system_text"].items():
                if key in VOICE_EVENT_KEYS:
                    system_text[key] = str(value)
        for legacy_key, event_key in LEGACY_TEXT_KEYS.items():
            if legacy_key in raw:
                system_text[event_key] = str(raw.get(legacy_key, "") or "")
        if system_text.get("no_order") == LEGACY_NO_ORDER_PROMPT:
            system_text["no_order"] = CURRENT_NO_ORDER_PROMPT

        custom_files = {key: "" for key in VOICE_EVENT_KEYS}
        if isinstance(raw.get("custom_files"), dict):
            for key, value in raw["custom_files"].items():
                if key in VOICE_EVENT_KEYS:
                    custom_files[key] = str(value or "")

        custom_voice_dir = str(raw.get("custom_voice_dir") or default_custom_voice_dir())
        custom_voice_dir = os.path.expandvars(custom_voice_dir)

        merged.update(
            {
                "enabled": enabled,
                "mode": mode,
                "custom_voice_dir": custom_voice_dir,
                "custom_files": custom_files,
                "system_text": system_text,
            }
        )
        return merged


class _SpeechBackend:
    def speak(self, text: str) -> None:
        raise NotImplementedError

    def close(self) -> None:
        return None


class CustomAudioBackend(_SpeechBackend):
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    def speak(self, text: str) -> None:
        path = Path(text)
        suffix = path.suffix.lower()
        if suffix == ".wav":
            winsound.PlaySound(str(path), winsound.SND_FILENAME)
            return
        self._play_with_powershell(path)

    def _play_with_powershell(self, path: Path) -> None:
        if not shutil.which("powershell"):
            raise RuntimeError("PowerShell 不可用，无法播放非 wav 自定义语音")
        path_b64 = base64.b64encode(str(path.resolve()).encode("utf-8")).decode("ascii")
        script = f"""
Add-Type -AssemblyName PresentationCore
$path = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{path_b64}'))
$player = New-Object System.Windows.Media.MediaPlayer
$player.Open([System.Uri]::new($path))
$deadline = (Get-Date).AddSeconds(5)
while (-not $player.NaturalDuration.HasTimeSpan -and (Get-Date) -lt $deadline) {{
    Start-Sleep -Milliseconds 80
}}
$player.Volume = 1.0
$player.Play()
if ($player.NaturalDuration.HasTimeSpan) {{
    $duration = $player.NaturalDuration.TimeSpan.TotalMilliseconds
    Start-Sleep -Milliseconds ([Math]::Min([Math]::Max($duration + 200, 500), 30000))
}} else {{
    Start-Sleep -Milliseconds 3000
}}
$player.Close()
"""
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            check=True,
            timeout=35,
            creationflags=creationflags,
        )


class Pyttsx3SpeechBackend(_SpeechBackend):
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self.pythoncom = None
        self.engine = None
        try:
            import pythoncom

            self.pythoncom = pythoncom
            self.pythoncom.CoInitialize()
            self.logger.info("pyttsx3 工作线程 COM 初始化成功")
        except Exception:
            self.logger.info("pyttsx3 工作线程 COM 初始化跳过或失败", exc_info=True)

        import pyttsx3

        self.pyttsx3 = pyttsx3
        self._init_engine()

    def _init_engine(self) -> None:
        self._close_engine()
        self.engine = self.pyttsx3.init()
        try:
            self.engine.setProperty("rate", 180)
            self.engine.setProperty("volume", 1.0)
        except Exception:
            self.logger.info("设置 pyttsx3 语音属性失败", exc_info=True)

    def speak(self, text: str) -> None:
        self._init_engine()
        self.logger.info("pyttsx3 say 调用：%s", text)
        self.engine.say(text)
        self.logger.info("pyttsx3 runAndWait 开始：%s", text)
        self.engine.runAndWait()
        self.logger.info("pyttsx3 runAndWait 结束：%s", text)
        self._close_engine()

    def close(self) -> None:
        try:
            self._close_engine()
        finally:
            if self.pythoncom is not None:
                self.pythoncom.CoUninitialize()

    def _close_engine(self) -> None:
        if self.engine is None:
            return
        try:
            self.engine.stop()
        except Exception:
            self.logger.info("关闭 pyttsx3 engine 失败", exc_info=True)
        self.engine = None


class SapiSpeechBackend(_SpeechBackend):
    def __init__(self, logger: logging.Logger) -> None:
        import pythoncom
        import win32com.client

        self.logger = logger
        self.pythoncom = pythoncom
        self.pythoncom.CoInitialize()
        self.speaker = win32com.client.Dispatch("SAPI.SpVoice")

    def speak(self, text: str) -> None:
        self.speaker.Volume = 100
        self.speaker.Rate = 0
        self.speaker.Speak(text)

    def speak_and_close(self, text: str) -> None:
        try:
            self.speak(text)
        finally:
            self.close()

    def close(self) -> None:
        self.speaker = None
        self.pythoncom.CoUninitialize()


class PowerShellSpeechBackend(_SpeechBackend):
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    def speak(self, text: str) -> None:
        if not shutil.which("powershell"):
            raise RuntimeError("PowerShell 不可用")
        text_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        script = f"""
Add-Type -AssemblyName System.Speech
$text = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{text_b64}'))
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$speaker.Volume = 100
$speaker.Rate = 0
$speaker.Speak($text)
$speaker.Dispose()
"""
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            check=True,
            timeout=15,
            creationflags=creationflags,
        )


class NullSpeechBackend(_SpeechBackend):
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    def speak(self, text: str) -> None:
        self.logger.warning("语音提示不可用，已忽略：%s", text)
