from __future__ import annotations

import base64
import logging
import queue
import shutil
import subprocess
import threading
import time
from typing import Any


DEFAULT_VOICE_PROMPT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "start_text": "已开始录制",
    "stop_text": "录制已结束",
    "switch_text": "已切换录制",
    "duplicate_text": "单号已录过",
}


class VoicePrompt:
    def __init__(self, config: dict[str, Any], logger: logging.Logger) -> None:
        self.logger = logger
        self._queue: queue.Queue[tuple[str, float] | None] = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._config_lock = threading.Lock()
        self._backend_lock = threading.Lock()
        self._worker_lock = threading.Lock()
        self._config = self._voice_config(config)
        self._backend_name = "initializing"
        self._last_error = ""
        self._speak_count = 0
        self.logger.info("VoicePrompt 实例创建 id=%s, enabled=%s", id(self), self._config.get("enabled", True))
        self._worker: threading.Thread | None = None
        self.ensure_worker()

    def update_config(self, config: dict[str, Any]) -> None:
        with self._config_lock:
            self._config = self._voice_config(config)
        self.logger.info(
            "语音配置已更新：enabled=%s, start_text_empty=%s",
            self._config.get("enabled", True),
            not bool(str(self._config.get("start_text", "")).strip()),
        )

    def speak(self, text: str) -> bool:
        self._speak_count += 1
        enabled = self.is_enabled()
        worker_alive = self.is_worker_alive()
        backend_name = self.backend_name()
        text = str(text or "").strip()
        self.logger.info(
            "speak 被调用：count=%s, enabled=%s, text_empty=%s, worker_alive=%s, backend=%s, text=%s",
            self._speak_count,
            enabled,
            not bool(text),
            worker_alive,
            backend_name,
            text,
        )
        if not enabled:
            self.logger.info("语音提示已关闭，跳过播放")
            return False
        if not text:
            self.logger.warning("语音文本为空，跳过播放")
            return False
        if not self.ensure_worker():
            self.logger.error("语音线程不可用，跳过播放")
            return False
        backend_name = self.backend_name()
        if backend_name == "none":
            self.logger.error("语音引擎不可用，跳过播放：last_error=%s", self.last_error())
            return False

        triggered_at = time.perf_counter()
        self.logger.info("语音播报触发：text=%s, triggered_at=%.6f", text, triggered_at)
        try:
            self._clear_pending()
            self._queue.put_nowait((text, triggered_at))
            self.logger.info("speak 请求已入队：text=%s, queue_size=%s", text, self._queue.qsize())
            return True
        except Exception:
            self.logger.exception("语音提示入队失败")
            return False

    def speak_start(self) -> bool:
        self.logger.info("录制开始触发语音")
        return self.speak(str(self._current_config().get("start_text", "")))

    def speak_stop(self) -> bool:
        self.logger.info("录制结束触发语音")
        return self.speak(str(self._current_config().get("stop_text", "")))

    def speak_switch(self) -> bool:
        self.logger.info("切换录制触发语音")
        return self.speak(str(self._current_config().get("switch_text", "")))

    def speak_duplicate(self) -> bool:
        self.logger.info("重复录制触发语音")
        return self.speak(str(self._current_config().get("duplicate_text", "")))

    def set_enabled(self, enabled: bool) -> None:
        with self._config_lock:
            self._config["enabled"] = bool(enabled)

    def is_enabled(self) -> bool:
        return bool(self._current_config().get("enabled", True))

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

    def _run(self) -> None:
        backend: _SpeechBackend | None = None
        self.logger.info("语音工作线程进入运行：ident=%s", threading.get_ident())
        try:
            backend = self._init_backend()
            while not self._stop_event.is_set():
                item = self._queue.get()
                if item is None:
                    self._queue.task_done()
                    break
                text, triggered_at = item
                self.logger.info("worker 取到语音文本：%s, queue_size=%s", text, self._queue.qsize())
                started_at = time.perf_counter()
                self.logger.info(
                    "语音开始播放：text=%s, started_at=%.6f, delay_ms=%.1f, backend=%s",
                    text,
                    started_at,
                    (started_at - triggered_at) * 1000,
                    self.backend_name(),
                )
                try:
                    backend.speak(text)
                    self.logger.info(
                        "语音播放完成：text=%s, elapsed_ms=%.1f",
                        text,
                        (time.perf_counter() - started_at) * 1000,
                    )
                except Exception as exc:
                    self._set_last_error(str(exc))
                    self.logger.exception("语音播放失败：%s", text)
                    try:
                        backend.close()
                    except Exception:
                        self.logger.exception("语音播放失败后关闭异常后端失败")
                    backend = self._init_backend()
                    self._try_fallback_speak(text)
                finally:
                    self._queue.task_done()
                    self.logger.info("播放完成后 worker 继续等待下一条语音")
        except Exception as exc:
            self._set_backend("none")
            self._set_last_error(str(exc))
            self.logger.exception("worker 异常退出原因：%s", exc)
        finally:
            if backend is not None:
                try:
                    backend.close()
                except Exception as exc:
                    self._set_last_error(str(exc))
                    self.logger.exception("语音模块关闭失败")

    def _init_backend(self) -> "_SpeechBackend":
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
                    self.logger.info("清空未播放语音：%s", old_item[0])
            except queue.Empty:
                break

    def _current_config(self) -> dict[str, Any]:
        with self._config_lock:
            return dict(self._config)

    def _set_backend(self, backend_name: str) -> None:
        with self._backend_lock:
            self._backend_name = backend_name

    def _set_last_error(self, message: str) -> None:
        with self._backend_lock:
            self._last_error = message

    @staticmethod
    def _voice_config(config: dict[str, Any]) -> dict[str, Any]:
        raw = config.get("voice_prompt", {}) if isinstance(config, dict) else {}
        raw = raw if isinstance(raw, dict) else {}
        merged = dict(DEFAULT_VOICE_PROMPT_CONFIG)
        merged.update(raw)
        if "enabled" not in raw:
            merged["enabled"] = True
        return merged


class _SpeechBackend:
    def speak(self, text: str) -> None:
        raise NotImplementedError

    def close(self) -> None:
        return None


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
        # pyttsx3 on Windows can leave the driver loop in a bad state after one
        # runAndWait(). Rebuilding the engine here keeps all COM/TTS work in the
        # worker thread while avoiding the "only first prompt speaks" failure.
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
