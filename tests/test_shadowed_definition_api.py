from __future__ import annotations

import inspect
from dataclasses import fields


def _parameter_shape(callable_object) -> list[tuple[str, inspect._ParameterKind, object]]:
    return [
        (parameter.name, parameter.kind, parameter.default)
        for parameter in inspect.signature(callable_object).parameters.values()
    ]


def test_effective_netdisk_directory_methods_keep_their_shape() -> None:
    from app.core.netdisk_sync import BaiduNetdiskClient

    expected = [
        ("self", inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty),
        ("remote_dir", inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty),
    ]
    assert _parameter_shape(BaiduNetdiskClient._remote_directory_exists) == expected
    assert _parameter_shape(BaiduNetdiskClient._create_remote_directory_xpan) == expected
    assert "_normalize_remote_dir_path" in BaiduNetdiskClient._remote_directory_exists.__code__.co_names
    assert "_normalize_remote_dir_path" in BaiduNetdiskClient._create_remote_directory_xpan.__code__.co_names
    assert "_log_directory_action" in BaiduNetdiskClient._create_remote_directory_xpan.__code__.co_names


def test_effective_video_checker_public_shape_is_stable() -> None:
    from app.core.video_checker import VideoCheckResult, VideoChecker

    assert [field.name for field in fields(VideoCheckResult)] == [
        "file_path", "exists", "file_size", "duration_seconds", "frame_count",
        "is_playable", "is_valid", "message", "status", "error", "warning",
        "width", "height", "fps", "codec", "validated_at",
    ]
    checker = VideoChecker()
    assert checker.logger is None
    assert checker.min_size_bytes == 0
    assert checker.min_valid_duration_seconds == 3.0
    assert list(inspect.signature(VideoChecker.check_video).parameters) == ["self", "file_path"]
    assert list(inspect.signature(VideoChecker.validate_video_file).parameters) == ["self", "file_path"]
    assert list(inspect.signature(VideoChecker.scan_unfinished_files).parameters) == ["self", "video_dir"]


def test_netdisk_history_effective_close_event_is_the_retry_guard_override() -> None:
    from app.ui.query_tab import NetdiskHistoryDialog

    method = NetdiskHistoryDialog.closeEvent
    assert list(inspect.signature(method).parameters) == ["self", "event"]
    assert {"_retry_running", "ignore"} <= set(method.__code__.co_names)
    assert "sync_history" not in method.__code__.co_consts
