from __future__ import annotations

import hashlib
from pathlib import Path


SUPPORTED_HASH_ALGORITHMS = {"SHA256", "MD5"}
DEFAULT_HASH_ALGORITHM = "SHA256"
DEFAULT_HASH_CHUNK_SIZE = 4 * 1024 * 1024


def normalize_hash_algorithm(algorithm: str | None) -> str:
    text = str(algorithm or DEFAULT_HASH_ALGORITHM).strip().upper().replace("-", "")
    if text == "SHA256":
        return "SHA256"
    if text == "MD5":
        return "MD5"
    return DEFAULT_HASH_ALGORITHM


def calculate_file_hash(
    file_path: str | Path,
    algorithm: str = DEFAULT_HASH_ALGORITHM,
    chunk_size: int = DEFAULT_HASH_CHUNK_SIZE,
) -> str:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError("视频文件不存在")
    if not path.is_file():
        raise FileNotFoundError("视频文件不存在")
    if path.stat().st_size <= 0:
        raise ValueError("视频文件大小为 0，无法生成校验码")

    normalized_algorithm = normalize_hash_algorithm(algorithm)
    hasher = hashlib.sha256() if normalized_algorithm == "SHA256" else hashlib.md5()
    block_size = max(64 * 1024, int(chunk_size or DEFAULT_HASH_CHUNK_SIZE))
    with path.open("rb") as file:
        while True:
            chunk = file.read(block_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()
