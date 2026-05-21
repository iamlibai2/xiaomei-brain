"""DingTalk 媒体上传/下载。

参考 OpenClaw dingtalk-connector services/media/。

API:
- 下载：POST /v1.0/robot/messageFiles/download → downloadUrl → 本地文件
- 上传：POST oapi.dingtalk.com/media/upload → media_id
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

DINGTALK_API = "https://api.dingtalk.com"
DINGTALK_OAPI = "https://oapi.dingtalk.com"

# 媒体类型 → 扩展名映射
MEDIA_EXTENSIONS = {
    "image": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"},
    "video": {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm"},
    "audio": {".mp3", ".wav", ".aac", ".ogg", ".m4a", ".flac", ".wma", ".amr"},
}

# Markdown 图片语法: ![alt](file://path) 或 ![alt](/absolute/path)
_LOCAL_IMAGE_RE = re.compile(
    r"!\[([^\]]*)\]\(((?:file://|MEDIA:|attachment://)[^)]+"
    r"|/(?:tmp|var|private|Users|home|root)[^)]+"
    r"|[A-Za-z]:[\\/][^)]+)\)"
)


def _ensure_directory(path: str) -> None:
    os.makedirs(path, exist_ok=True)


# ── 下载 ────────────────────────────────────────────────

def download_media(
    download_code: str,
    robot_code: str,
    access_token: str,
    media_dir: str | None = None,
) -> str | None:
    """根据 downloadCode 下载媒体文件到本地。

    流程：
    1. POST /v1.0/robot/messageFiles/download 获取 downloadUrl
    2. HTTP GET downloadUrl 写入本地文件

    Args:
        download_code: 钉钉回调中的 downloadCode
        robot_code: 机器人 clientId
        access_token: 新版 API accessToken
        media_dir: 保存目录，默认系统临时目录

    Returns:
        本地文件路径，失败返回 None
    """
    import requests as _requests

    if not media_dir:
        media_dir = os.path.join(tempfile.gettempdir(), "dingtalk-media", "inbound")
    _ensure_directory(media_dir)

    headers = {
        "x-acs-dingtalk-access-token": access_token,
        "Content-Type": "application/json",
    }

    # Step 1: 换取 downloadUrl
    try:
        resp = _requests.post(
            f"{DINGTALK_API}/v1.0/robot/messageFiles/download",
            json={"robotCode": robot_code, "downloadCode": download_code},
            headers=headers,
            timeout=15,
        )
        data = resp.json()
        download_url = data.get("downloadUrl")
        if not download_url:
            logger.warning("[DingTalk/Media] downloadCode 换取 downloadUrl 失败: %s", data)
            return None
    except Exception as e:
        logger.error("[DingTalk/Media] 获取 downloadUrl 异常: %s", e)
        return None

    # Step 2: 下载文件
    try:
        resp = _requests.get(
            download_url,
            headers={"Content-Type": None},  # OSS 签名验证要求不带 Content-Type
            timeout=30,
        )
        content = resp.content
    except Exception as e:
        logger.error("[DingTalk/Media] 下载文件异常: %s", e)
        return None

    # 推断扩展名
    content_type = resp.headers.get("content-type", "")
    ext = _guess_extension(content_type, content)

    filename = f"{int(time.time() * 1000)}_{_random_suffix()}{ext}"
    filepath = os.path.join(media_dir, filename)

    with open(filepath, "wb") as f:
        f.write(content)

    logger.info("[DingTalk/Media] 下载完成: %s (%d bytes)", filepath, len(content))
    return filepath


def _guess_extension(content_type: str, content: bytes) -> str:
    """根据 Content-Type 或文件头推断扩展名。"""
    ct = content_type.lower()
    if "png" in ct:
        return ".png"
    if "gif" in ct:
        return ".gif"
    if "webp" in ct:
        return ".webp"
    if "jpeg" in ct or "jpg" in ct:
        return ".jpg"
    if "mp4" in ct:
        return ".mp4"
    if "mpeg" in ct or "mp3" in ct:
        return ".mp3"
    if "ogg" in ct:
        return ".ogg"
    if "amr" in ct:
        return ".amr"
    if "pdf" in ct:
        return ".pdf"
    # 魔数检测
    if content[:4] == b"\x89PNG":
        return ".png"
    if content[:2] == b"\xff\xd8":
        return ".jpg"
    if content[:4] == b"RIFF":
        return ".webp"
    if content[:4] == b"GIF8":
        return ".gif"
    return ".bin"


def _random_suffix(length: int = 8) -> str:
    import random
    import string
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


# ── 上传 ────────────────────────────────────────────────

def upload_media(
    file_path: str,
    media_type: str = "image",
    oapi_token: str | None = None,
    max_size: int = 20 * 1024 * 1024,  # 20MB
) -> str | None:
    """上传媒体文件到钉钉，返回 media_id。

    API: POST https://oapi.dingtalk.com/media/upload?access_token=...&type=...

    Args:
        file_path: 本地文件绝对路径
        media_type: image / file / video / voice
        oapi_token: OAPI access_token
        max_size: 文件大小上限（bytes）

    Returns:
        media_id（去掉了开头的 @），失败返回 None
    """
    import requests as _requests

    if not oapi_token:
        logger.error("[DingTalk/Media] 无 oapiToken，无法上传")
        return None

    if not os.path.isfile(file_path):
        logger.warning("[DingTalk/Media] 文件不存在: %s", file_path)
        return None

    file_size = os.path.getsize(file_path)
    if file_size > max_size:
        size_mb = file_size / (1024 * 1024)
        max_mb = max_size / (1024 * 1024)
        logger.warning(
            "[DingTalk/Media] 文件过大: %s (%.1fMB > %.0fMB)", file_path, size_mb, max_mb
        )
        return None

    try:
        filename = os.path.basename(file_path)
        content_type = "image/jpeg" if media_type == "image" else "application/octet-stream"

        with open(file_path, "rb") as f:
            resp = _requests.post(
                f"{DINGTALK_OAPI}/media/upload",
                params={"access_token": oapi_token, "type": media_type},
                files={"media": (filename, f, content_type)},
                timeout=60,
            )

        data = resp.json()
        media_id = data.get("media_id")
        if media_id:
            # 去掉开头的 @
            clean_id = media_id.lstrip("@")
            logger.info("[DingTalk/Media] 上传成功: media_id=%s", clean_id)
            return clean_id

        logger.warning("[DingTalk/Media] 上传返回无 media_id: %s", data)
        return None
    except Exception as e:
        logger.error("[DingTalk/Media] 上传异常: %s", e)
        return None


# ── 后处理 ──────────────────────────────────────────────

def process_local_images(
    content: str, oapi_token: str | None
) -> str:
    """扫描文本中的本地图片路径，上传到钉钉并替换为 media_id。

    ![alt](file:///path/to/img.png) → ![alt](@media_id)
    """
    if not oapi_token:
        return content

    matches = list(_LOCAL_IMAGE_RE.finditer(content))
    if not matches:
        return content

    logger.info("[DingTalk/Media] 检测到 %d 个本地图片引用，开始上传...", len(matches))
    result = content

    for match in matches:
        full = match.group(0)
        alt = match.group(1)
        raw_path = match.group(2)
        file_path = _to_local_path(raw_path)

        media_id = upload_media(file_path, "image", oapi_token)
        if media_id:
            replacement = f"![{alt}]({media_id})"
            result = result.replace(full, replacement)

    return result


def _to_local_path(raw: str) -> str:
    """去掉 file:// / MEDIA: / attachment:// 前缀。"""
    path = raw
    for prefix in ("file://", "MEDIA:", "attachment://"):
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    try:
        from urllib.parse import unquote
        path = unquote(path)
    except Exception:
        pass
    return path


# ── 文本解析 ─────────────────────────────────────────────

TEXT_EXTENSIONS = {
    ".txt", ".md", ".json", ".yaml", ".yml", ".xml", ".html", ".css",
    ".js", ".ts", ".py", ".java", ".c", ".cpp", ".h", ".sh", ".bat",
    ".csv", ".log", ".ini", ".cfg", ".toml",
}


def read_text_file(file_path: str) -> str | None:
    """读取文本文件内容。"""
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in TEXT_EXTENSIONS:
        return None
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:
        logger.warning("[DingTalk/Media] 读取文件失败: %s: %s", file_path, e)
        return None
