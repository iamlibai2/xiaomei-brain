"""MiniMax H3/V2 and Hailuo/V1 video API adapter."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests


H3_MODEL = "MiniMax-H3"
HAILUO_MODEL = "MiniMax-Hailuo-2.3"
SUPPORTED_MODELS = (H3_MODEL, HAILUO_MODEL)
TERMINAL_FAILURES = frozenset({"failed", "fail", "cancelled", "expired"})


@dataclass(frozen=True)
class VideoTask:
    task_id: str
    api_version: str
    model: str
    status: str = "queued"
    file_id: str = ""
    download_url: str = ""
    error: str = ""
    scene_id: str = ""


class MiniMaxVideoProvider:
    """Create, query, download, and persist MiniMax video tasks."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.minimaxi.com",
        default_model: str = H3_MODEL,
        aigc_watermark: bool = False,
        poll_interval: float = 10,
        max_wait_seconds: float = 3600,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.aigc_watermark = aigc_watermark
        self.poll_interval = max(5.0, float(poll_interval))
        self.max_wait_seconds = max(60.0, float(max_wait_seconds))

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def create(
        self,
        *,
        prompt: str,
        model: str = "",
        duration: int = 6,
        resolution: str = "768P",
        ratio: str = "16:9",
        first_frame: str = "",
        last_frame: str = "",
        references: list[tuple[str, str]] | None = None,
        prompt_optimizer: bool = True,
    ) -> VideoTask:
        selected = model or self.default_model
        if selected not in SUPPORTED_MODELS:
            raise ValueError(f"不支持的视频模型: {selected}")
        if not prompt.strip():
            raise ValueError("视频描述不能为空")

        if selected == H3_MODEL:
            payload = self._h3_payload(
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                ratio=ratio,
                first_frame=first_frame,
                last_frame=last_frame,
                references=references or [],
            )
            data = self._request_json(
                "POST", "/v2/video_generation", json=payload, timeout=45,
            )
            task_id = str(data.get("task_id") or "")
            version = "v2"
        else:
            payload = self._hailuo_payload(
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                first_frame=first_frame,
                prompt_optimizer=prompt_optimizer,
            )
            data = self._request_json(
                "POST", "/v1/video_generation", json=payload, timeout=45,
            )
            self._raise_base_error(data)
            task_id = str(data.get("task_id") or "")
            version = "v1"
        if not task_id:
            raise RuntimeError("MiniMax 未返回视频任务 ID")
        return VideoTask(task_id=task_id, api_version=version, model=selected)

    def query(
        self,
        task_id: str,
        *,
        api_version: str,
        model: str,
        scene_id: str = "",
    ) -> VideoTask:
        if api_version == "v2":
            data = self._request_json(
                "GET", f"/v2/query/video_generation/{task_id}", timeout=30,
            )
            task = data.get("task") or {}
            status = str(task.get("status") or "unknown").lower()
            content = task.get("content") or {}
            error = task.get("error") or ""
            return VideoTask(
                task_id=task_id,
                api_version="v2",
                model=str(task.get("model") or model or H3_MODEL),
                status=status,
                download_url=str(content.get("url") or ""),
                error=self._error_text(error),
                scene_id=scene_id,
            )

        data = self._request_json(
            "GET",
            "/v1/query/video_generation",
            params={"task_id": task_id},
            timeout=30,
        )
        self._raise_base_error(data)
        return VideoTask(
            task_id=task_id,
            api_version="v1",
            model=model or HAILUO_MODEL,
            status=str(data.get("status") or "unknown").lower(),
            file_id=str(data.get("file_id") or ""),
            error=self._error_text(data.get("error") or ""),
            scene_id=scene_id,
        )

    def wait(self, task: VideoTask) -> VideoTask:
        deadline = time.monotonic() + self.max_wait_seconds
        current = task
        while time.monotonic() < deadline:
            time.sleep(self.poll_interval)
            current = self.query(
                current.task_id,
                api_version=current.api_version,
                model=current.model,
                scene_id=current.scene_id,
            )
            if current.status in {"success", "succeeded"}:
                return current
            if current.status in TERMINAL_FAILURES:
                raise RuntimeError(
                    f"视频生成未成功: {current.status}"
                    + (f"，{current.error}" if current.error else "")
                )
        raise TimeoutError(f"视频生成等待超时: {task.task_id}")

    def download(self, task: VideoTask, output_path: str | Path) -> Path:
        download_url = task.download_url
        if not download_url and task.file_id:
            data = self._request_json(
                "GET",
                "/v1/files/retrieve",
                params={"file_id": task.file_id},
                timeout=30,
            )
            self._raise_base_error(data)
            download_url = str((data.get("file") or {}).get("download_url") or "")
        if not download_url:
            raise RuntimeError("视频任务成功，但未返回下载地址")

        target = Path(output_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".part")
        try:
            with requests.get(download_url, stream=True, timeout=(20, 180)) as response:
                response.raise_for_status()
                with temporary.open("wb") as stream:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            stream.write(chunk)
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)
        return target

    @staticmethod
    def save_task(task: VideoTask, directory: str | Path) -> Path:
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{task.task_id}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(asdict(task), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path

    @staticmethod
    def load_task(task_id: str, directory: str | Path) -> VideoTask:
        if not task_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in task_id):
            raise ValueError("视频任务 ID 无效")
        path = Path(directory) / f"{task_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return VideoTask(**data)

    def _h3_payload(
        self,
        *,
        prompt: str,
        duration: int,
        resolution: str,
        ratio: str,
        first_frame: str,
        last_frame: str,
        references: list[tuple[str, str]],
    ) -> dict[str, Any]:
        if not 4 <= int(duration) <= 15:
            raise ValueError("MiniMax-H3 时长必须为 4～15 秒")
        if resolution not in {"768P", "2K"}:
            raise ValueError("MiniMax-H3 分辨率必须为 768P 或 2K")
        if ratio not in {"adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}:
            raise ValueError("MiniMax-H3 视频比例无效")
        if (first_frame or last_frame) and references:
            raise ValueError("首尾帧模式不能与多模态参考素材混用")
        reference_counts = {
            kind: sum(1 for _url, item_kind in references if item_kind == kind)
            for kind in ("image", "video", "audio")
        }
        if reference_counts["image"] > 9:
            raise ValueError("MiniMax-H3 最多支持 9 张参考图片")
        if reference_counts["video"] > 3 or reference_counts["audio"] > 3:
            raise ValueError("MiniMax-H3 最多支持 3 段参考视频和 3 段参考音频")
        if sum(reference_counts.values()) > 12:
            raise ValueError("MiniMax-H3 最多支持 12 个参考素材")
        encoded_size = sum(
            len(value.encode("ascii"))
            for value in (first_frame, last_frame, *(url for url, _kind in references))
            if value
        )
        if encoded_size > 63 * 1024 * 1024:
            raise ValueError("参考素材转为 Data URL 后超过 64 MB 请求上限")

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt[:7000]}]
        for value, role in ((first_frame, "first_frame"), (last_frame, "last_frame")):
            if value:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": value},
                    "role": role,
                })
        for media_url, media_type in references:
            content.append({
                "type": f"{media_type}_url",
                f"{media_type}_url": {"url": media_url},
                "role": f"reference_{media_type}",
            })
        payload: dict[str, Any] = {
            "model": H3_MODEL,
            "content": content,
            "resolution": resolution,
            "duration": int(duration),
            "aigc_watermark": self.aigc_watermark,
        }
        if first_frame or last_frame:
            payload["ratio"] = "adaptive"
        elif references:
            payload["ratio"] = ratio
        else:
            if ratio == "adaptive":
                raise ValueError("MiniMax-H3 文生视频必须指定具体比例")
            payload["ratio"] = ratio
        return payload

    def _hailuo_payload(
        self,
        *,
        prompt: str,
        duration: int,
        resolution: str,
        first_frame: str,
        prompt_optimizer: bool,
    ) -> dict[str, Any]:
        if int(duration) not in {6, 10}:
            raise ValueError("Hailuo 2.3 时长必须为 6 或 10 秒")
        if resolution not in {"768P", "1080P"}:
            raise ValueError("Hailuo 2.3 分辨率必须为 768P 或 1080P")
        if int(duration) == 10 and resolution != "768P":
            raise ValueError("Hailuo 2.3 的 10 秒视频仅支持 768P")
        payload: dict[str, Any] = {
            "model": HAILUO_MODEL,
            "prompt": prompt[:2000],
            "duration": int(duration),
            "resolution": resolution,
            "prompt_optimizer": bool(prompt_optimizer),
            "aigc_watermark": self.aigc_watermark,
        }
        if first_frame:
            payload["first_frame_image"] = first_frame
        return payload

    def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = requests.request(
            method,
            f"{self.base_url}{path}",
            headers=self.headers,
            **kwargs,
        )
        try:
            data = response.json()
        except ValueError as exc:
            response.raise_for_status()
            raise RuntimeError("MiniMax 返回了无法解析的响应") from exc
        if response.status_code >= 400:
            error = data.get("error") or {}
            message = self._error_text(error) or str(data)[:300]
            raise RuntimeError(f"MiniMax 视频 API 错误（HTTP {response.status_code}）: {message}")
        return data

    @staticmethod
    def _raise_base_error(data: dict[str, Any]) -> None:
        base = data.get("base_resp") or {}
        code = int(base.get("status_code") or 0)
        if code:
            raise RuntimeError(
                f"MiniMax 视频 API 错误（{code}）: {base.get('status_msg') or 'unknown'}"
            )

    @staticmethod
    def _error_text(error: Any) -> str:
        if isinstance(error, dict):
            return str(error.get("message") or error.get("type") or "")
        return str(error or "")
