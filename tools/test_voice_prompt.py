from __future__ import annotations

import logging
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.voice_prompt import VoicePrompt  # noqa: E402


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("voice-test")
    voice = VoicePrompt(
        {
            "voice_prompt": {
                "enabled": True,
                "start_text": "语音测试成功",
                "stop_text": "录制已结束",
                "switch_text": "已切换录制",
                "duplicate_text": "单号已录过",
            }
        },
        logger,
    )
    time.sleep(0.8)
    submitted_results: list[bool] = []
    idle_results: list[bool] = []
    for text in ["语音测试一", "语音测试二", "语音测试三"]:
        submitted = voice.speak(text)
        submitted_results.append(submitted)
        idle_results.append(voice.wait_until_idle(timeout_seconds=8))
        time.sleep(1)
    print(f"当前语音引擎：{voice.backend_name()}")
    for index, (submitted, idle) in enumerate(zip(submitted_results, idle_results), 1):
        print(f"第 {index} 次提交播放成功：{submitted}")
        print(f"第 {index} 次等待播放完成：{idle}")
    print(f"语音线程仍然存活：{voice.is_worker_alive()}")
    if voice.last_error():
        print(f"最近错误：{voice.last_error()}")
    voice.stop()
    return 0 if all(submitted_results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
