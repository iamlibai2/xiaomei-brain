"""FaceID — 人脸识别。

基于 face_recognition (dlib)，本地离线，不上传。
- detect(): 检测画面中的人脸，返回位置和特征向量
- match(): 特征向量与已知身份库比对
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
import urllib.request
import warnings

# face_recognition_models 使用了过时的 pkg_resources，消除噪声
warnings.filterwarnings("ignore", message="pkg_resources is deprecated", category=UserWarning)
import os
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# HF 镜像
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


class FaceID:
    """人脸检测 + 特征提取 + 身份匹配。

    Lazy loading，首次调用时初始化 dlib 模型。
    """

    _loaded: bool = False

    def __init__(self) -> None:
        self._server_url = os.environ.get(
            "FACE_SERVER_URL",
            "http://127.0.0.1:18769",
        ).rstrip("/")
        self._known_faces: list[dict] = []  # [{"name": "李白", "encoding": np.array}, ...]

    # ── 懒加载 ────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        if FaceID._loaded:
            return
        import face_recognition
        logger.info("face_recognition (dlib) 就绪")
        FaceID._loaded = True

    # ── 公共 API ──────────────────────────────────────────

    def detect(self, image_path: str) -> list[dict]:
        """检测画面中的人脸。

        返回: [{"bbox": (top,right,bottom,left), "encoding": np.array}, ...]
        没有检测到人脸则返回空列表。
        """
        if os.environ.get("XIAOMEI_FACE_LOCAL_ONLY") != "1":
            remote = self._detect_remote(image_path)
            if remote is not None:
                return [
                    {"bbox": face["bbox"], "encoding": face["encoding"]}
                    for face in remote
                ]

        self._ensure_loaded()
        import face_recognition

        if not os.path.exists(image_path):
            logger.warning("图片不存在: %s", image_path)
            return []

        try:
            image = face_recognition.load_image_file(image_path)
            locations = face_recognition.face_locations(image)
            if not locations:
                return []

            encodings = face_recognition.face_encodings(image, known_face_locations=locations)
            return [
                {"bbox": loc, "encoding": enc}
                for loc, enc in zip(locations, encodings)
            ]
        except Exception:
            logger.exception("人脸检测失败")
            return []

    def detect_all(self, image_path: str) -> list[dict]:
        """检测人脸 + 提取关键点。

        比 detect() 多返回 68 点 landmarks，用于表情分析等场景。
        复用同一次图片加载和 face_locations 调用。

        返回: [{"bbox": (top,right,bottom,left), "encoding": np.array,
                 "landmarks": {chin, left_eye, ...}}, ...]
        """
        if os.environ.get("XIAOMEI_FACE_LOCAL_ONLY") != "1":
            remote = self._detect_remote(image_path)
            if remote is not None:
                return remote

        self._ensure_loaded()
        import face_recognition

        if not os.path.exists(image_path):
            logger.warning("图片不存在: %s", image_path)
            return []

        try:
            image = face_recognition.load_image_file(image_path)
            locations = face_recognition.face_locations(image)
            if not locations:
                return []

            encodings = face_recognition.face_encodings(image, known_face_locations=locations)
            landmarks_list = face_recognition.face_landmarks(image, face_locations=locations)

            return [
                {"bbox": loc, "encoding": enc, "landmarks": lm}
                for loc, enc, lm in zip(locations, encodings, landmarks_list)
            ]
        except Exception:
            logger.exception("人脸检测失败")
            return []

    def _detect_remote(self, image_path: str) -> list[dict] | None:
        """Use the machine-wide face service when available.

        ``None`` means the service is unavailable. An empty list is a valid
        response meaning that no face was detected.
        """
        path = Path(image_path)
        if not path.is_file():
            return []
        payload = json.dumps({
            "image_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
            "suffix": path.suffix,
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{self._server_url}/detect",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                value = json.loads(response.read())
            raw_faces = value.get("faces") if isinstance(value, dict) else None
            if not isinstance(raw_faces, list):
                return None
            faces: list[dict] = []
            for raw in raw_faces:
                if not isinstance(raw, dict):
                    continue
                bbox = raw.get("bbox")
                encoding = raw.get("encoding")
                if not isinstance(bbox, list) or len(bbox) != 4 or not isinstance(encoding, list):
                    continue
                landmarks = {
                    str(key): [tuple(int(coordinate) for coordinate in point) for point in points]
                    for key, points in (raw.get("landmarks") or {}).items()
                    if isinstance(points, list)
                }
                faces.append({
                    "bbox": tuple(int(coordinate) for coordinate in bbox),
                    "encoding": np.asarray(encoding, dtype=np.float32),
                    "landmarks": landmarks,
                })
            return faces
        except Exception:
            logger.debug("Shared face service unavailable, falling back in-process", exc_info=True)
            return None

    def match(self, encoding, tolerance: float = 0.5) -> str | None:
        """单个特征向量 → 匹配已知身份。

        tolerance: 越小越严格（0.4=安全场景, 0.6=宽松场景）
        返回匹配到的 name 或 None。
        """
        if not self._known_faces:
            logger.warning("[FaceID] match: 已知人脸为空，无法匹配")
            return None

        known_encodings = np.asarray([f["encoding"] for f in self._known_faces])
        candidate = np.asarray(encoding)
        distances = np.linalg.norm(known_encodings - candidate, axis=1)
        results = [bool(distance <= tolerance) for distance in distances]
        logger.debug("[FaceID] match: %d 个已知人脸, distances=%s, matched=%s",
                    len(self._known_faces),
                    [round(float(d), 3) for d in distances],
                    any(results))
        if any(results):
            idx = results.index(True)
            return self._known_faces[idx]["name"]
        return None

    def register(self, name: str, image_path: str) -> bool:
        """注册一张脸。

        从 image_path 中提取第一张人脸，关联到 name。
        返回是否成功。
        """
        faces = self.detect(image_path)
        if not faces:
            logger.warning("未检测到人脸: %s", image_path)
            return False

        # 检查是否已注册
        for f in self._known_faces:
            if f["name"] == name:
                logger.info("更新 %s 的人脸特征", name)
                f["encoding"] = faces[0]["encoding"]
                return True

        self._known_faces.append({"name": name, "encoding": faces[0]["encoding"]})
        logger.info("已注册人脸: %s", name)
        return True

    @property
    def known_names(self) -> list[str]:
        """已注册的人名列表。"""
        return [f["name"] for f in self._known_faces]

    # ── 持久化 ────────────────────────────────────────────

    def save(self, faces_dir: str) -> None:
        """保存所有人脸特征到 faces_dir/*.npy。

        每张脸一个 .npy，文件名 = name + ".npy"。
        """
        os.makedirs(faces_dir, exist_ok=True)
        for f in self._known_faces:
            path = os.path.join(faces_dir, f"{f['name']}.npy")
            np.save(path, f["encoding"])
        logger.info("FaceID 已保存 %d 张脸到 %s", len(self._known_faces), faces_dir)

    def load(self, faces_dir: str) -> None:
        """从 faces_dir/*.npy 加载人脸特征。"""
        if not os.path.isdir(faces_dir):
            return
        for filename in sorted(os.listdir(faces_dir)):
            if not filename.endswith(".npy"):
                continue
            name = filename[:-4]  # 去 .npy
            path = os.path.join(faces_dir, filename)
            encoding = np.load(path)
            # 跳过已有重名
            if name in self.known_names:
                continue
            self._known_faces.append({"name": name, "encoding": encoding})
            logger.info("FaceID 加载: %s", name)
