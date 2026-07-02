"""面部情绪检测。

两种方案：
- FaceEmotionDetector: dlib 68 点关键点几何特征，零模型依赖，纯数学计算
- EmotiEffLibRecognizer: enet_b2_7 ONNX CNN，7 类情绪概率分布，~12ms 推理
"""

from __future__ import annotations

import math
import logging
import os

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class FaceEmotionDetector:
    """基于几何比率的面部情绪检测。

    使用 face_recognition.face_landmarks() 返回的 68 点关键点，
    计算 Mouth Aspect Ratio（微笑）、Eyebrow Depression Ratio（皱眉）、
    Eye Aspect Ratio（眯眼）。

    Usage:
        detector = FaceEmotionDetector()
        result = detector.analyze(landmarks)
        # {"dominant": "happy", "indicators": {"smile": 0.75, ...}}
    """

    # 归一化常量 — 将几何比率映射到 0-1 强度
    MAR_NEUTRAL = 0.55     # 嘴巴高度/宽度，中性时约 0.55
    MAR_EXTREME = 0.20     # 大笑时嘴巴高度降低
    EAR_NEUTRAL = 0.30     # 眼睛纵横比，正常睁开
    EAR_EXTREME = 0.18     # 眯眼时纵比降低
    BROW_NEUTRAL = 0.18    # 眉毛-眼角距 / 眼间距，中性时约 0.18
    BROW_EXTREME = 0.08    # 皱眉时眉毛压低

    # ── 公共 API ──────────────────────────────────────────

    def analyze(self, landmarks: dict) -> dict:
        """分析单张脸的关键点。

        Args:
            landmarks: face_recognition.face_landmarks() 返回的字典，
                       包含 chin, left_eye, right_eye, left_eyebrow,
                       right_eyebrow, top_lip, bottom_lip 等键，
                       每个值是 [(x, y), ...] 列表。

        Returns:
            {
                "dominant": "happy" | "angry" | "sad" | "neutral",
                "indicators": {
                    "smile": 0.0-1.0,
                    "brow_furrow": 0.0-1.0,
                    "eye_narrow": 0.0-1.0,
                }
            }
        """
        smile = self._smile_intensity(landmarks["top_lip"], landmarks["bottom_lip"])
        brow_furrow = self._brow_furrow_intensity(landmarks)
        eye_narrow = self._eye_narrow_intensity(
            landmarks["left_eye"], landmarks["right_eye"]
        )

        return {
            "dominant": self._classify(smile, brow_furrow, eye_narrow),
            "indicators": {
                "smile": round(smile, 4),
                "brow_furrow": round(brow_furrow, 4),
                "eye_narrow": round(eye_narrow, 4),
            },
        }

    def analyze_all(self, landmarks_list: list[dict]) -> list[dict]:
        """批量分析多张脸。"""
        return [self.analyze(lm) for lm in landmarks_list]

    # ── 指标计算 ──────────────────────────────────────────

    def _smile_intensity(self, top_lip: list, bottom_lip: list) -> float:
        """AU12 — 微笑强度。

        嘴宽高比：MAR = height / width。
        微笑时嘴角外拉 → width 变大 → MAR 变小。
        """
        mar = self._mouth_aspect_ratio(top_lip, bottom_lip)
        return self._normalize(mar, self.MAR_NEUTRAL, self.MAR_EXTREME)

    def _brow_furrow_intensity(self, landmarks: dict) -> float:
        """AU4 — 皱眉强度。

        眉毛内角到眼睛内角的距离 / 两眼间距。
        皱眉时眉毛压低 → 距离变小 → ratio 变小。
        """
        ratio = self._brow_depression_ratio(landmarks)
        return self._normalize(ratio, self.BROW_NEUTRAL, self.BROW_EXTREME)

    def _eye_narrow_intensity(self, left_eye: list, right_eye: list) -> float:
        """AU7 — 眯眼强度。

        眼部纵横比 EAR，取双眼平均。
        眯眼时眼睑高度变小 → EAR 变小。
        """
        ear_left = self._eye_aspect_ratio(left_eye)
        ear_right = self._eye_aspect_ratio(right_eye)
        ear = (ear_left + ear_right) / 2.0
        return self._normalize(ear, self.EAR_NEUTRAL, self.EAR_EXTREME)

    # ── 几何公式（静态）───────────────────────────────────

    @staticmethod
    def _euclidean(a: tuple, b: tuple) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    @staticmethod
    def _eye_aspect_ratio(eye: list) -> float:
        """Soukupová & Čech (2016) EAR。

        eye: 6 个点，顺序：
          0=corner_left, 1=upper_inner, 2=upper_outer,
          3=corner_right, 4=lower_outer, 5=lower_inner
        """
        h1 = FaceEmotionDetector._euclidean(eye[1], eye[5])
        h2 = FaceEmotionDetector._euclidean(eye[2], eye[4])
        w = FaceEmotionDetector._euclidean(eye[0], eye[3])
        if w < 1e-6:
            return 0.0
        return (h1 + h2) / (2.0 * w)

    @staticmethod
    def _mouth_aspect_ratio(top_lip: list, bottom_lip: list) -> float:
        """MAR = mouth_height / mouth_width。"""
        all_points = top_lip + bottom_lip
        xs = [p[0] for p in all_points]
        ys = [p[1] for p in all_points]
        width = max(xs) - min(xs)
        height = max(ys) - min(ys)
        if width < 1e-6:
            return 1.0
        return height / width

    @staticmethod
    def _brow_depression_ratio(landmarks: dict) -> float:
        """内眉-内眼角距离 / 眼间距。

        left_eye[3]  = 左眼内角
        right_eye[0] = 右眼内角
        left_eyebrow[-1]  = 左眉内端
        right_eyebrow[0]  = 右眉内端
        """
        inner_eye_l = landmarks["left_eye"][3]
        inner_eye_r = landmarks["right_eye"][0]
        inner_brow_l = landmarks["left_eyebrow"][-1]
        inner_brow_r = landmarks["right_eyebrow"][0]

        gap_l = max(0.0, inner_eye_l[1] - inner_brow_l[1])
        gap_r = max(0.0, inner_eye_r[1] - inner_brow_r[1])
        avg_gap = (gap_l + gap_r) / 2.0
        eye_sep = FaceEmotionDetector._euclidean(inner_eye_l, inner_eye_r)

        if eye_sep < 1e-6:
            return 1.0
        return avg_gap / eye_sep

    # ── 归一化与分类 ──────────────────────────────────────

    @staticmethod
    def _normalize(value: float, neutral: float, extreme: float) -> float:
        """将几何比率映射到 0-1 强度。

        假设：value 越小 = 越强烈（MAR/EAR/ratio 均符合）。
        neutral 时强度 0，extreme 时强度 1。
        """
        if value >= neutral:
            return 0.0
        if value <= extreme:
            return 1.0
        return (neutral - value) / (neutral - extreme)

    @staticmethod
    def _classify(smile: float, brow_furrow: float, eye_narrow: float) -> str:
        """规则分类：三个指标 → 主导情绪。"""
        if smile >= 0.5:
            return "happy"
        if brow_furrow >= 0.5:
            if eye_narrow >= 0.4:
                return "angry"
            return "sad"
        return "neutral"


# ── EmotiEffLib CNN 推理器 ─────────────────────────────────

class EmotiEffLibRecognizer:
    """EmotiEffLib enet_b2_7 ONNX 情绪识别。

    EfficientNet-B2，7 类情绪：Anger, Disgust, Fear, Happiness, Neutral, Sadness, Surprise。
    ~12ms 推理（纯模型），260×260 输入，ImageNet 归一化。

    直接使用 ONNX Runtime，绕过 EmotiEffLib 官方 wrapper（后者有 graph 解析兼容性问题）。

    Usage:
        rec = EmotiEffLibRecognizer()
        result = rec.classify(face_img)  # face_img: np.ndarray (H, W, 3) RGB
        # {"dominant": "Happiness", "probabilities": {"Anger": 0.01, ...}}
    """

    CLASSES = ["Anger", "Disgust", "Fear", "Happiness", "Neutral", "Sadness", "Surprise"]
    IMG_SIZE = 260
    MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    def __init__(self, model_path: str | None = None) -> None:
        import onnxruntime as ort

        if model_path is None:
            model_path = os.path.expanduser("~/.cache/emotiefflib/enet_b2_7.onnx")
        ort.set_default_logger_severity(3)
        self._session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self._warm = False

    @property
    def is_available(self) -> bool:
        return self._session is not None

    def classify(self, face_img: np.ndarray) -> dict:
        """对单张人脸图像进行情绪分类。

        Args:
            face_img: (H, W, 3) RGB 人脸图像（已裁剪）

        Returns:
            {"dominant": "Happiness", "probabilities": {"Anger": 0.01, ...}}
        """
        if face_img.shape[0] < 20 or face_img.shape[1] < 20:
            return {"dominant": "Neutral", "probabilities": {}}

        # 预处理：resize → normalize → CHW → batch
        x = cv2.resize(face_img, (self.IMG_SIZE, self.IMG_SIZE)).astype(np.float32) / 255.0
        for i in range(3):
            x[..., i] = (x[..., i] - self.MEAN[i]) / self.STD[i]
        x = x.transpose(2, 0, 1)[np.newaxis, ...]

        # 推理
        logits = self._session.run(None, {"input": x})[0][0]

        # Softmax
        probs = np.exp(logits - logits.max())
        probs = probs / probs.sum()

        dominant_idx = int(np.argmax(probs))
        return {
            "dominant": self.CLASSES[dominant_idx],
            "probabilities": {cls: float(p) for cls, p in zip(self.CLASSES, probs)},
        }
