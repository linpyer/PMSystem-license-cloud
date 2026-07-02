from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from PySide6.QtCore import QThread, Signal

from app.core.database import (
    DatabaseManager,
    UPLOAD_DONE,
    UPLOAD_FAILED,
    UPLOAD_PENDING,
    UPLOAD_UPLOADING,
)
from app.utils.time_utils import format_datetime


DEFAULT_REMOTE_ROOT = "/电商溯源/videos/"
BAIDU_AUTHORIZE_URL = "https://openapi.baidu.com/oauth/2.0/authorize"
BAIDU_TOKEN_URL = "https://openapi.baidu.com/oauth/2.0/token"
BAIDU_USER_INFO_URL = "https://pan.baidu.com/rest/2.0/xpan/nas"
BAIDU_FILE_URL = "https://pan.baidu.com/rest/2.0/xpan/file"
BAIDU_PCS_FILE_URL = "https://pcs.baidu.com/rest/2.0/pcs/file"
BAIDU_UPLOAD_URL = "https://d.pcs.baidu.com/rest/2.0/pcs/superfile2"
BAIDU_OOB_REDIRECT_URI = "oob"
UPLOAD_CHUNK_SIZE = 4 * 1024 * 1024
UPLOAD_PART_MAX_ATTEMPTS = 3


SENSITIVE_KEYS = {"access_token", "refresh_token", "client_secret", "secret_key", "secret", "token"}


def _redact_sensitive_text(text: str, limit: int = 800) -> str:
    result = str(text or "")
    result = re.sub(r"access_token=[^&\s)]+", "access_token=<redacted>", result)
    result = re.sub(r"refresh_token=[^&\s)]+", "refresh_token=<redacted>", result)
    result = re.sub(r"client_secret=[^&\s)]+", "client_secret=<redacted>", result)
    return result[:limit]


class NetdiskError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        phase: str = "",
        local_path: str = "",
        remote_path: str = "",
        http_status: int | None = None,
        baidu_error_code: Any = None,
        baidu_error_msg: str = "",
        response_text: str = "",
    ) -> None:
        message = _redact_sensitive_text(message)
        super().__init__(message)
        self.message = message
        self.phase = phase
        self.local_path = local_path
        self.remote_path = remote_path
        self.http_status = http_status
        self.baidu_error_code = baidu_error_code
        self.baidu_error_msg = baidu_error_msg
        self.response_text = response_text

    def __str__(self) -> str:
        return self.message

    def log_context(self) -> dict[str, Any]:
        return {
            "phase": self.phase or "-",
            "local_path": self.local_path or "-",
            "remote_path": self.remote_path or "-",
            "http_status": self.http_status if self.http_status is not None else "-",
            "baidu_error_code": self.baidu_error_code if self.baidu_error_code not in (None, "") else "-",
            "baidu_error_msg": self.baidu_error_msg or "-",
            "response_text": self.response_text or "-",
        }


def _redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                result[key] = "<redacted>"
            else:
                result[key] = _redact_sensitive(item)
        return result
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value


def _safe_response_text(value: Any, limit: int = 800) -> str:
    if value is None:
        return ""
    try:
        if isinstance(value, (dict, list)):
            text = json.dumps(_redact_sensitive(value), ensure_ascii=False)
        else:
            text = str(value)
    except Exception:
        text = "<response stringify failed>"
    for marker in ("access_token", "refresh_token", "client_secret"):
        text = text.replace(marker, f"{marker[:4]}***")
    return text[:limit]


def _safe_exception_text(exc: Exception, limit: int = 500) -> str:
    text = str(exc) or exc.__class__.__name__
    text = re.sub(r"access_token=[^&\s)]+", "access_token=<redacted>", text)
    text = re.sub(r"refresh_token=[^&\s)]+", "refresh_token=<redacted>", text)
    text = re.sub(r"client_secret=[^&\s)]+", "client_secret=<redacted>", text)
    return text[:limit]


def _safe_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        safe_query = urlencode(
            [
                (key, "<redacted>" if key.lower() in SENSITIVE_KEYS else value)
                for key, value in parse_qsl(parts.query, keep_blank_values=True)
            ]
        )
        return urlunsplit((parts.scheme, parts.netloc, parts.path, safe_query, parts.fragment))
    except Exception:
        return "<url redacted>"


def default_netdisk_config() -> dict[str, Any]:
    return {
        "enabled": False,
        "provider": "baidu",
        "remote_root": DEFAULT_REMOTE_ROOT,
        "client_id": "",
        "client_secret": "",
        "access_token": "",
        "refresh_token": "",
        "token_expires_at": "",
        "last_auth_time": "",
        "debug": False,
    }


def normalize_remote_root(value: str | None) -> str:
    root = str(value or DEFAULT_REMOTE_ROOT).strip() or DEFAULT_REMOTE_ROOT
    root = root.replace("\\", "/")
    if not root.startswith("/"):
        root = "/" + root
    if not root.endswith("/"):
        root += "/"
    return root


def normalize_netdisk_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    config = default_netdisk_config()
    if isinstance(raw, dict):
        config.update(raw)
    config["enabled"] = bool(config.get("enabled", False))
    config["provider"] = str(config.get("provider") or "baidu")
    config["remote_root"] = normalize_remote_root(str(config.get("remote_root") or DEFAULT_REMOTE_ROOT))
    for key in ("client_id", "client_secret", "access_token", "refresh_token", "token_expires_at", "last_auth_time"):
        config[key] = str(config.get(key) or "").strip()
    config["debug"] = bool(config.get("debug", False))
    return config


def build_authorize_url(client_id: str) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": BAIDU_OOB_REDIRECT_URI,
            "scope": "basic,netdisk",
        }
    )
    return f"{BAIDU_AUTHORIZE_URL}?{query}"


def build_remote_video_path(
    local_path: str | Path,
    video_root: str | Path,
    remote_root: str,
    recorded_at: str | None = None,
) -> str:
    path = Path(local_path)
    remote_root = normalize_remote_root(remote_root)
    date_parts = _date_parts_from_text(recorded_at)
    if date_parts is None:
        try:
            date_parts = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y/%m/%d")
        except OSError:
            date_parts = datetime.now().strftime("%Y/%m/%d")
    return f"{remote_root}{date_parts}/{path.name}"


def _date_parts_from_text(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).strftime("%Y/%m/%d")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).strftime("%Y/%m/%d")
    except ValueError:
        return None


class BaiduNetdiskClient:
    def __init__(
        self,
        config: dict[str, Any],
        logger: logging.Logger | None = None,
        token_refreshed_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.config = normalize_netdisk_config(config)
        self.logger = logger
        self.token_refreshed_callback = token_refreshed_callback
        self.session = None
        self._created_remote_dirs: set[str] = set()
        self._checked_remote_dirs: set[str] = set()

    def has_credentials(self) -> bool:
        return bool(self.config.get("client_id") and self.config.get("client_secret"))

    def has_token(self) -> bool:
        return bool(self.config.get("access_token") or self.config.get("refresh_token"))

    def authorize_url(self) -> str:
        client_id = str(self.config.get("client_id") or "").strip()
        if not client_id:
            raise NetdiskError("请先填写百度网盘 App Key。", phase="检查授权状态")
        return build_authorize_url(client_id)

    def exchange_code(self, code: str) -> dict[str, Any]:
        if not self.has_credentials():
            raise NetdiskError("请先填写百度网盘 App Key 和 Secret Key。", phase="检查授权状态")
        payload = {
            "grant_type": "authorization_code",
            "code": code.strip(),
            "client_id": self.config["client_id"],
            "client_secret": self.config["client_secret"],
            "redirect_uri": BAIDU_OOB_REDIRECT_URI,
        }
        data = self._request_json("POST", BAIDU_TOKEN_URL, phase="检查授权状态", data=payload)
        return self._tokens_from_response(data)

    def refresh_access_token(self) -> dict[str, Any]:
        refresh_token = str(self.config.get("refresh_token") or "").strip()
        if not refresh_token:
            raise NetdiskError("access_token 刷新失败：缺少 refresh_token", phase="刷新 access_token")
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.config["client_id"],
            "client_secret": self.config["client_secret"],
        }
        data = self._request_json("POST", BAIDU_TOKEN_URL, phase="刷新 access_token", data=payload)
        tokens = self._tokens_from_response(data)
        self.config.update(tokens)
        if self.token_refreshed_callback is not None:
            self.token_refreshed_callback(tokens)
        return tokens

    def test_connection(self) -> bool:
        params = {"method": "uinfo", "access_token": self._access_token()}
        data = self._request_json("GET", BAIDU_USER_INFO_URL, phase="检查授权状态", params=params)
        if int(data.get("errno", 0) or 0) != 0:
            raise self._error_from_baidu(data, "检查授权状态", "百度网盘连接失败")
        return True

    def upload_file(self, local_path: str | Path, remote_path: str, progress_callback: Callable[[int, int], None] | None = None) -> dict[str, Any]:
        path = Path(local_path)
        if not path.exists():
            raise NetdiskError("本地视频文件不存在", phase="检查本地文件", local_path=str(path), remote_path=remote_path)
        if not path.is_file():
            raise NetdiskError("本地路径不是文件", phase="检查本地文件", local_path=str(path), remote_path=remote_path)
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise NetdiskError(f"读取本地文件失败：{exc}", phase="检查本地文件", local_path=str(path), remote_path=remote_path) from exc
        if size <= 0:
            raise NetdiskError("本地视频文件大小为 0，无法上传", phase="检查本地文件", local_path=str(path), remote_path=remote_path)

        remote_path = "/" + remote_path.strip().lstrip("/")
        remote_dir = remote_path.rsplit("/", 1)[0] if "/" in remote_path else "/"
        self._log_phase("创建远程目录", path, remote_path)
        self.ensure_remote_directory(remote_dir)
        self._log_phase("预上传", path, remote_path)
        block_list = self._file_block_md5s(path, progress_callback)
        precreate = self._precreate(remote_path, size, block_list)
        upload_id = str(precreate.get("uploadid") or "")
        if not upload_id:
            raise self._error_from_baidu(precreate, "预上传", "预上传失败", local_path=str(path), remote_path=remote_path)

        for part_index, offset in enumerate(range(0, size, UPLOAD_CHUNK_SIZE)):
            self._log_phase(f"分片上传 {part_index + 1}", path, remote_path)
            self._upload_part(path, remote_path, upload_id, part_index, offset)
            if progress_callback:
                progress_callback(min(size, offset + UPLOAD_CHUNK_SIZE), size)

        self._log_phase("创建远程文件", path, remote_path)
        created = self._create_file(remote_path, size, block_list, upload_id)
        if int(created.get("errno", 0) or 0) != 0:
            raise self._error_from_baidu(created, "创建远程文件", "创建文件失败", local_path=str(path), remote_path=remote_path)
        return created

    def ensure_remote_directory(self, remote_dir: str) -> None:
        remote_dir = self._normalize_remote_dir_path(remote_dir)
        if remote_dir in {"", "/"}:
            return
        if remote_dir in self._created_remote_dirs or remote_dir in self._checked_remote_dirs:
            return

        parts = [part for part in remote_dir.split("/") if part]
        current = ""
        for part in parts:
            current += "/" + part
            if current in self._created_remote_dirs or current in self._checked_remote_dirs:
                continue
            self._ensure_single_remote_directory(current)

    def _ensure_single_remote_directory(self, remote_dir: str) -> None:
        remote_dir = self._normalize_remote_dir_path(remote_dir)
        if self._remote_directory_exists(remote_dir):
            self._checked_remote_dirs.add(remote_dir)
            self._log_directory_action("skip_existing", remote_dir, remote_dir, "已存在")
            return
        self._create_remote_directory(remote_dir)
        if not self._remote_directory_exists(remote_dir):
            raise NetdiskError(
                f"创建远程目录失败：创建后未能确认目录存在：{remote_dir}",
                phase="创建远程目录",
                remote_path=remote_dir,
            )
        self._created_remote_dirs.add(remote_dir)
        self._checked_remote_dirs.add(remote_dir)

    def _create_remote_directory(self, remote_dir: str) -> None:
        remote_dir = self._normalize_remote_dir_path(remote_dir)
        self._create_remote_directory_xpan(remote_dir)
        return
        first_error: NetdiskError | None = None
        try:
            self._create_remote_directory_xpan(remote_dir)
            return
        except NetdiskError as exc:
            first_error = exc
            if self.logger:
                self.logger.warning(
                    "百度网盘 xpan 创建目录失败，将尝试 pcs mkdir：dir=%s, error=%s",
                    remote_dir,
                    exc,
                )

        try:
            self._create_remote_directory_pcs(remote_dir)
            return
        except NetdiskError as exc:
            combined = self._combined_directory_error(remote_dir, first_error, exc)
            if self.logger:
                self._log_netdisk_error(combined, BAIDU_PCS_FILE_URL)
            raise combined from exc

    @staticmethod
    def _normalize_remote_dir_path(value: str) -> str:
        text = str(value or "").replace("\\", "/").strip()
        text = "/" + text.strip("/")
        return "/" if text == "/" else text.rstrip("/")

    @staticmethod
    def _remote_parent_dir(remote_dir: str) -> str:
        remote_dir = BaiduNetdiskClient._normalize_remote_dir_path(remote_dir)
        if remote_dir == "/":
            return "/"
        parent = remote_dir.rsplit("/", 1)[0] or "/"
        return parent if parent.startswith("/") else f"/{parent}"

    @staticmethod
    def _remote_base_name(remote_dir: str) -> str:
        return BaiduNetdiskClient._normalize_remote_dir_path(remote_dir).rsplit("/", 1)[-1]

    def _remote_directory_exists(self, remote_dir: str) -> bool:
        remote_dir = self._normalize_remote_dir_path(remote_dir)
        if remote_dir == "/":
            return True
        parent_dir = self._remote_parent_dir(remote_dir)
        target_name = self._remote_base_name(remote_dir)
        self._log_directory_action("check_dir", remote_dir, "", "checking")
        params = {
            "method": "list",
            "access_token": self._access_token(),
            "dir": parent_dir,
        }
        response = self._request_json("GET", BAIDU_FILE_URL, phase="检查远程目录", params=params, timeout=45)
        errno = int(response.get("errno", 0) or 0)
        returned_path = str(response.get("path") or "")
        info = response.get("info")
        if not returned_path and isinstance(info, dict):
            returned_path = str(info.get("path") or "")
        if errno in (-8, 31061):
            if self._remote_directory_exists(remote_dir):
                self._log_directory_action("skip_existing", remote_dir, remote_dir, "已存在", errno, "目录已存在")
                return
        if errno != 0:
            self._log_directory_action("mkdir_failed", remote_dir, returned_path, "失败", errno, str(response.get("errmsg") or ""))
            raise self._error_from_baidu(response, "创建远程目录", "创建远程目录失败", remote_path=remote_dir)
        normalized_returned = self._normalize_remote_dir_path(returned_path) if returned_path else remote_dir
        normalized_requested = self._normalize_remote_dir_path(remote_dir)
        if normalized_returned != normalized_requested:
            self._log_directory_action("mkdir_failed", remote_dir, returned_path, "返回路径不一致")
            raise NetdiskError(
                f"远程目录创建异常：请求路径和返回路径不一致，疑似触发重名自动改名。请求：{remote_dir}，返回：{returned_path}",
                phase="创建远程目录",
                remote_path=remote_dir,
                baidu_error_code=errno,
                response_text=_safe_response_text(response),
            )
        self._log_directory_action("mkdir_success", remote_dir, returned_path or remote_dir, "成功", errno, "")
        return
        if errno != 0:
            raise self._error_from_baidu(response, "检查远程目录", "检查远程目录失败", remote_path=remote_dir)
        for item in response.get("list", []) or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("server_filename") or item.get("filename") or "").strip()
            item_path = str(item.get("path") or "").strip()
            is_dir = int(item.get("isdir", 0) or 0) == 1
            if is_dir and (name == target_name or self._normalize_remote_dir_path(item_path) == remote_dir):
                self._log_directory_action("skip_existing", remote_dir, item_path or remote_dir, "已存在")
                return True
        return False

    def _remote_directory_exists(self, remote_dir: str) -> bool:
        remote_dir = self._normalize_remote_dir_path(remote_dir)
        if remote_dir == "/":
            return True
        parent_dir = self._remote_parent_dir(remote_dir)
        target_name = self._remote_base_name(remote_dir)
        self._log_directory_action("check_dir", remote_dir, "", "checking")
        params = {
            "method": "list",
            "access_token": self._access_token(),
            "dir": parent_dir,
        }
        response = self._request_json("GET", BAIDU_FILE_URL, phase="检查远程目录", params=params, timeout=45)
        errno = int(response.get("errno", 0) or 0)
        if errno != 0:
            raise self._error_from_baidu(response, "检查远程目录", "检查远程目录失败", remote_path=remote_dir)
        for item in response.get("list", []) or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("server_filename") or item.get("filename") or "").strip()
            item_path = str(item.get("path") or "").strip()
            is_dir = int(item.get("isdir", 0) or 0) == 1
            if is_dir and (name == target_name or self._normalize_remote_dir_path(item_path) == remote_dir):
                self._log_directory_action("skip_existing", remote_dir, item_path or remote_dir, "已存在")
                return True
        return False

    def _log_directory_action(
        self,
        action: str,
        requested_path: str,
        returned_path: str = "",
        result: str = "",
        error_code: Any = "",
        error_msg: str = "",
    ) -> None:
        if not self.logger:
            return
        self.logger.info(
            "百度网盘目录操作：action=%s, requested_path=%s, returned_path=%s, result=%s, error_code=%s, error_msg=%s",
            action,
            requested_path,
            returned_path or "-",
            result or "-",
            error_code if error_code not in (None, "") else "-",
            error_msg or "-",
        )

    def _create_remote_directory_xpan(self, remote_dir: str) -> None:
        params = {"method": "create", "access_token": self._access_token()}
        data = {
            "path": remote_dir,
            "isdir": "1",
            "rtype": "0",
        }
        response = self._request_json("POST", BAIDU_FILE_URL, phase="创建远程目录", params=params, data=data, timeout=45)
        errno = int(response.get("errno", 0) or 0)
        if errno not in (0, -8, 31061):
            raise self._error_from_baidu(response, "创建远程目录", "创建远程目录失败", remote_path=remote_dir)

    def _create_remote_directory_xpan(self, remote_dir: str) -> None:
        remote_dir = self._normalize_remote_dir_path(remote_dir)
        params = {"method": "create", "access_token": self._access_token()}
        data = {
            "path": remote_dir,
            "isdir": "1",
            "rtype": "0",
        }
        response = self._request_json("POST", BAIDU_FILE_URL, phase="创建远程目录", params=params, data=data, timeout=45)
        errno = int(response.get("errno", 0) or 0)
        returned_path = str(response.get("path") or "")
        info = response.get("info")
        if not returned_path and isinstance(info, dict):
            returned_path = str(info.get("path") or "")
        if errno in (-8, 31061):
            if self._remote_directory_exists(remote_dir):
                self._log_directory_action("skip_existing", remote_dir, remote_dir, "已存在", errno, "目录已存在")
                return
        if errno != 0:
            self._log_directory_action("mkdir_failed", remote_dir, returned_path, "失败", errno, str(response.get("errmsg") or ""))
            raise self._error_from_baidu(response, "创建远程目录", "创建远程目录失败", remote_path=remote_dir)
        normalized_returned = self._normalize_remote_dir_path(returned_path) if returned_path else remote_dir
        normalized_requested = self._normalize_remote_dir_path(remote_dir)
        if normalized_returned != normalized_requested:
            self._log_directory_action("mkdir_failed", remote_dir, returned_path, "返回路径不一致")
            raise NetdiskError(
                f"远程目录创建异常：请求路径和返回路径不一致，疑似触发重名自动改名。请求：{remote_dir}，返回：{returned_path}",
                phase="创建远程目录",
                remote_path=remote_dir,
                baidu_error_code=errno,
                response_text=_safe_response_text(response),
            )
        self._log_directory_action("mkdir_success", remote_dir, returned_path or remote_dir, "成功", errno, "")

    def _create_remote_directory_pcs(self, remote_dir: str) -> None:
        params = {
            "method": "mkdir",
            "access_token": self._access_token(),
            "path": remote_dir,
        }
        response = self._request_json("POST", BAIDU_PCS_FILE_URL, phase="创建远程目录", params=params, timeout=45)
        errno = int(response.get("errno", 0) or 0)
        if errno not in (0, -8, 31061):
            raise self._error_from_baidu(response, "创建远程目录", "创建远程目录失败", remote_path=remote_dir)

    @staticmethod
    def _combined_directory_error(remote_dir: str, first_error: NetdiskError | None, second_error: NetdiskError) -> NetdiskError:
        first_text = str(first_error) if first_error else "-"
        second_text = str(second_error) or "-"
        response_parts = []
        if first_error and first_error.response_text:
            response_parts.append(f"xpan={first_error.response_text}")
        if second_error.response_text:
            response_parts.append(f"pcs={second_error.response_text}")
        return NetdiskError(
            f"创建远程目录失败：{remote_dir}；xpan：{first_text}；pcs：{second_text}",
            phase="创建远程目录",
            remote_path=remote_dir,
            http_status=second_error.http_status if second_error.http_status is not None else (first_error.http_status if first_error else None),
            baidu_error_code=second_error.baidu_error_code if second_error.baidu_error_code not in (None, "") else (first_error.baidu_error_code if first_error else None),
            baidu_error_msg=second_error.baidu_error_msg or (first_error.baidu_error_msg if first_error else ""),
            response_text=" | ".join(response_parts)[:800],
        )

    def _precreate(self, remote_path: str, size: int, block_list: list[str]) -> dict[str, Any]:
        params = {"method": "precreate", "access_token": self._access_token()}
        data = {
            "path": remote_path,
            "size": str(size),
            "isdir": "0",
            "autoinit": "1",
            "rtype": "3",
            "block_list": json.dumps(block_list),
        }
        response = self._request_json("POST", BAIDU_FILE_URL, phase="预上传", params=params, data=data)
        errno = int(response.get("errno", 0) or 0)
        if errno != 0:
            raise self._error_from_baidu(response, "预上传", "预上传失败", remote_path=remote_path)
        return response

    def _upload_part_legacy(self, path: Path, remote_path: str, upload_id: str, part_index: int, offset: int) -> None:
        params = {
            "method": "upload",
            "type": "tmpfile",
            "access_token": self._access_token(),
            "path": remote_path,
            "uploadid": upload_id,
            "partseq": str(part_index),
        }
        with path.open("rb") as file:
            file.seek(offset)
            data = file.read(UPLOAD_CHUNK_SIZE)
        file_name = path.name
        mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        files = {"file": (file_name, data, mime_type)}
        response = self._request_json("POST", BAIDU_UPLOAD_URL, phase="分片上传", params=params, files=files, timeout=180)
        if int(response.get("errno", 0) or 0) != 0:
            raise self._error_from_baidu(response, "分片上传", f"分片上传失败：第 {part_index + 1} 片", local_path=str(path), remote_path=remote_path)

    def _upload_part(self, path: Path, remote_path: str, upload_id: str, part_index: int, offset: int) -> None:
        params = {
            "method": "upload",
            "type": "tmpfile",
            "access_token": self._access_token(),
            "path": remote_path,
            "uploadid": upload_id,
            "partseq": str(part_index),
        }
        with path.open("rb") as file:
            file.seek(offset)
            data = file.read(UPLOAD_CHUNK_SIZE)
        file_name = path.name
        mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        files = {"file": (file_name, data, mime_type)}
        last_error: NetdiskError | None = None
        for attempt in range(1, UPLOAD_PART_MAX_ATTEMPTS + 1):
            try:
                response = self._request_json("POST", BAIDU_UPLOAD_URL, phase="分片上传", params=params, files=files, timeout=180)
                if int(response.get("errno", 0) or 0) != 0:
                    raise self._error_from_baidu(
                        response,
                        "分片上传",
                        f"分片上传失败：第 {part_index + 1} 片",
                        local_path=str(path),
                        remote_path=remote_path,
                    )
                return
            except NetdiskError as exc:
                last_error = exc
                transient = exc.http_status is None or int(exc.http_status or 0) >= 500
                if attempt >= UPLOAD_PART_MAX_ATTEMPTS or not transient:
                    break
                if self.logger:
                    self.logger.warning(
                        "百度网盘分片上传失败，准备重试：part=%s, attempt=%s/%s, reason=%s",
                        part_index + 1,
                        attempt,
                        UPLOAD_PART_MAX_ATTEMPTS,
                        exc.message,
                    )
                time.sleep(min(2 * attempt, 5))
        assert last_error is not None
        raise last_error

    def _create_file(self, remote_path: str, size: int, block_list: list[str], upload_id: str) -> dict[str, Any]:
        params = {"method": "create", "access_token": self._access_token()}
        data = {
            "path": remote_path,
            "size": str(size),
            "isdir": "0",
            "rtype": "3",
            "uploadid": upload_id,
            "block_list": json.dumps(block_list),
        }
        return self._request_json("POST", BAIDU_FILE_URL, phase="创建远程文件", params=params, data=data, timeout=90)

    def _file_block_md5s(self, path: Path, progress_callback: Callable[[int, int], None] | None = None) -> list[str]:
        result: list[str] = []
        total = path.stat().st_size
        read_bytes = 0
        with path.open("rb") as file:
            while True:
                chunk = file.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                result.append(hashlib.md5(chunk).hexdigest())
                read_bytes += len(chunk)
                if progress_callback:
                    progress_callback(min(read_bytes, total), total)
        return result or [hashlib.md5(b"").hexdigest()]

    def _access_token(self) -> str:
        token = str(self.config.get("access_token") or "").strip()
        if token and not self._token_expired():
            return token
        if self.config.get("refresh_token"):
            self.refresh_access_token()
            token = str(self.config.get("access_token") or "").strip()
        if not token:
            raise NetdiskError("未完成百度网盘授权", phase="检查授权状态")
        return token

    def _token_expired(self) -> bool:
        text = str(self.config.get("token_expires_at") or "").strip()
        if not text:
            return False
        try:
            expires_at = datetime.fromisoformat(text)
        except ValueError:
            return False
        return datetime.now() >= expires_at - timedelta(minutes=5)

    def _tokens_from_response(self, data: dict[str, Any]) -> dict[str, Any]:
        access_token = str(data.get("access_token") or "").strip()
        refresh_token = str(data.get("refresh_token") or self.config.get("refresh_token") or "").strip()
        if not access_token:
            raise self._error_from_baidu(data, "检查授权状态", "百度网盘授权失败")
        expires_in = int(float(data.get("expires_in") or 0))
        expires_at = datetime.now() + timedelta(seconds=max(0, expires_in))
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_expires_at": expires_at.isoformat(timespec="seconds") if expires_in else "",
            "last_auth_time": format_datetime(),
        }

    def _request_json(self, method: str, url: str, phase: str = "百度网盘接口请求", **kwargs: Any) -> dict[str, Any]:
        try:
            import requests
        except ImportError as exc:
            raise NetdiskError("当前缺少 requests 依赖，请先执行 pip install -r requirements.txt", phase=phase) from exc

        timeout = kwargs.pop("timeout", 30)
        response_text = ""
        http_status: int | None = None
        try:
            if self.session is None:
                self.session = requests.Session()
            response = self.session.request(method, url, timeout=timeout, **kwargs)
            http_status = response.status_code
            response_text = response.text or ""
            if response.status_code >= 400:
                data = self._try_response_json(response_text)
                error = self._error_from_baidu(
                    data,
                    phase,
                    f"{phase}失败：HTTP {response.status_code}",
                    http_status=http_status,
                    response_text=response_text,
                )
                if self.logger:
                    self._log_netdisk_error(error, url)
                raise error

            data = response.json()
            if not isinstance(data, dict):
                raise NetdiskError(
                    "百度接口返回异常：返回内容不是 JSON 对象",
                    phase=phase,
                    http_status=http_status,
                    response_text=_safe_response_text(response_text),
                )
            return data
        except NetdiskError:
            raise
        except requests.Timeout as exc:
            error = NetdiskError(
                "网络请求超时",
                phase=phase,
                http_status=http_status,
                response_text=_safe_response_text(response_text),
            )
            if self.logger:
                self._log_netdisk_error(error, url)
            raise error from exc
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", http_status)
            text = getattr(getattr(exc, "response", None), "text", response_text)
            error = NetdiskError(
                f"网络请求失败：{exc}",
                phase=phase,
                http_status=status,
                response_text=_safe_response_text(text),
            )
            if self.logger:
                self._log_netdisk_error(error, url)
            raise error from exc
        except ValueError as exc:
            error = NetdiskError(
                "百度接口返回异常：JSON 解析失败",
                phase=phase,
                http_status=http_status,
                response_text=_safe_response_text(response_text),
            )
            if self.logger:
                self._log_netdisk_error(error, url)
            raise error from exc

    @staticmethod
    def _baidu_error_message(data: dict[str, Any], fallback: str = "百度网盘操作失败") -> str:
        errno = data.get("errno", data.get("error", ""))
        message = data.get("errmsg") or data.get("error_description") or data.get("error_msg") or fallback
        return f"{message}（错误码：{errno}）" if errno != "" else str(message or fallback)

    @staticmethod
    def _try_response_json(text: str) -> dict[str, Any]:
        try:
            data = json.loads(text or "{}")
            return data if isinstance(data, dict) else {"response": data}
        except ValueError:
            return {"response_text": text}

    def _error_from_baidu(
        self,
        data: dict[str, Any],
        phase: str,
        fallback: str,
        *,
        local_path: str = "",
        remote_path: str = "",
        http_status: int | None = None,
        response_text: str = "",
    ) -> NetdiskError:
        code = data.get("errno", data.get("error", ""))
        msg = str(data.get("errmsg") or data.get("error_description") or data.get("error_msg") or fallback)
        text = response_text or _safe_response_text(data)
        if code not in (None, ""):
            message = f"{fallback}：错误码 {code}，{msg}"
        else:
            message = msg or fallback
        return NetdiskError(
            message,
            phase=phase,
            local_path=local_path,
            remote_path=remote_path,
            http_status=http_status,
            baidu_error_code=code,
            baidu_error_msg=msg,
            response_text=_safe_response_text(text),
        )

    def _log_netdisk_error(self, error: NetdiskError, url: str = "") -> None:
        if not self.logger:
            return
        context = error.log_context()
        self.logger.error(
            "百度网盘操作失败：phase=%s, local_path=%s, remote_path=%s, http_status=%s, baidu_error_code=%s, "
            "baidu_error_msg=%s, response_text=%s, url=%s",
            context["phase"],
            context["local_path"],
            context["remote_path"],
            context["http_status"],
            context["baidu_error_code"],
            context["baidu_error_msg"],
            context["response_text"],
            _safe_url(url),
        )

    def _log_phase(self, phase: str, local_path: Path | None = None, remote_path: str = "") -> None:
        if self.logger and bool(self.config.get("debug", False)):
            self.logger.info(
                "百度网盘上传阶段：phase=%s, local_path=%s, remote_path=%s",
                phase,
                str(local_path) if local_path is not None else "-",
                remote_path or "-",
            )


class NetdiskUploadWorker(QThread):
    progress_message = Signal(str)
    progress_changed = Signal(int, int, str, int, int)
    row_changed = Signal(str)
    upload_failed = Signal(str, str)
    tokens_refreshed = Signal(dict)
    finished_summary = Signal(int, int)

    def __init__(
        self,
        *,
        config: dict[str, Any],
        database_path: str | Path,
        video_root: str | Path,
        entries: list[dict[str, Any]],
        task_label: str = "同步",
        retry_failed: bool = False,
        logger: logging.Logger | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.config = normalize_netdisk_config(config)
        self.database_path = Path(database_path)
        self.video_root = Path(video_root)
        self.entries = entries
        self.task_label = str(task_label or "同步")
        self.retry_failed = bool(retry_failed)
        self.logger = logger
        self._stop_requested = False

    def stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:  # type: ignore[override]
        database = DatabaseManager(self.database_path, self.logger)
        client = BaiduNetdiskClient(self.config, self.logger, token_refreshed_callback=self.tokens_refreshed.emit)
        success_count = 0
        fail_count = 0
        try:
            total = len(self.entries)
            for index, entry in enumerate(self.entries, start=1):
                if self._stop_requested:
                    break
                file_path = Path(str(entry.get("file_path") or ""))
                self.progress_changed.emit(index - 1, total, file_path.name, success_count, fail_count)
                self.progress_message.emit(f"正在{self.task_label} {index}/{total}：{file_path.name}")
                if not file_path.exists():
                    database.mark_file_missing(file_path)
                    message = "本地视频文件不存在，无法上传"
                    if self.logger:
                        self.logger.warning("百度网盘上传跳过：phase=检查本地文件, local_path=%s, reason=%s", file_path, message)
                    self.row_changed.emit(str(file_path))
                    self.upload_failed.emit(str(file_path), message)
                    fail_count += 1
                    self.progress_changed.emit(index, total, file_path.name, success_count, fail_count)
                    continue

                try:
                    file_size = file_path.stat().st_size
                except OSError as exc:
                    message = f"读取本地文件失败：{exc}"
                    database.update_upload_status(file_path, UPLOAD_FAILED, error=message, increment_retry=True)
                    self.row_changed.emit(str(file_path))
                    self.upload_failed.emit(str(file_path), message)
                    fail_count += 1
                    self.progress_changed.emit(index, total, file_path.name, success_count, fail_count)
                    continue
                if file_size <= 0:
                    message = "本地视频文件大小为 0，无法上传"
                    database.update_upload_status(file_path, UPLOAD_FAILED, error=message, increment_retry=True)
                    self.row_changed.emit(str(file_path))
                    self.upload_failed.emit(str(file_path), message)
                    fail_count += 1
                    self.progress_changed.emit(index, total, file_path.name, success_count, fail_count)
                    continue

                remote_path = build_remote_video_path(
                    file_path,
                    self.video_root,
                    str(self.config.get("remote_root") or DEFAULT_REMOTE_ROOT),
                    str(entry.get("recorded_at") or entry.get("created_time") or ""),
                )
                try:
                    database.update_upload_status(
                        file_path,
                        UPLOAD_UPLOADING,
                        remote_path=remote_path,
                        error="",
                        increment_retry=self.retry_failed,
                    )
                    self.row_changed.emit(str(file_path))
                    client.upload_file(file_path, remote_path)
                    database.update_upload_status(file_path, UPLOAD_DONE, remote_path=remote_path, error="")
                    self.row_changed.emit(str(file_path))
                    success_count += 1
                    self.progress_changed.emit(index, total, file_path.name, success_count, fail_count)
                except Exception as exc:
                    error_text = self._upload_error_text(exc)
                    if self.logger:
                        if isinstance(exc, NetdiskError):
                            self.logger.exception(
                                "百度网盘上传失败：phase=%s, local_path=%s, remote_path=%s, http_status=%s, "
                                "baidu_error_code=%s, baidu_error_msg=%s, response_text=%s",
                                exc.phase or "-",
                                file_path,
                                remote_path,
                                exc.http_status if exc.http_status is not None else "-",
                                exc.baidu_error_code if exc.baidu_error_code not in (None, "") else "-",
                                exc.baidu_error_msg or "-",
                                exc.response_text or "-",
                            )
                        else:
                            self.logger.exception("百度网盘上传失败：phase=未知, path=%s, remote_path=%s", file_path, remote_path)
                    database.update_upload_status(
                        file_path,
                        UPLOAD_FAILED,
                        remote_path=remote_path,
                        error=error_text,
                        increment_retry=not self.retry_failed,
                    )
                    self.row_changed.emit(str(file_path))
                    self.upload_failed.emit(str(file_path), error_text)
                    fail_count += 1
                    self.progress_changed.emit(index, total, file_path.name, success_count, fail_count)
                time.sleep(0.05)
        finally:
            database.close()
            self.finished_summary.emit(success_count, fail_count)

    @staticmethod
    def _upload_error_text(exc: Exception) -> str:
        if isinstance(exc, NetdiskError):
            phase = exc.phase or "上传"
            text = exc.message or str(exc) or "上传失败"
            if phase and not text.startswith(phase):
                text = f"{phase}失败：{text}" if not text.endswith("失败") else f"{phase}：{text}"
            return _redact_sensitive_text(text, 500)
        return (str(exc) or "上传失败")[:500]
