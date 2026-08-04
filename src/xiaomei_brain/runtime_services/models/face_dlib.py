from __future__ import annotations

import base64
import logging
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

from xiaomei_brain.runtime_services.http_utils import health_payload, read_json, send_json, serve


def run(_device: str, _model_path: str) -> None:
    os.environ["XIAOMEI_FACE_LOCAL_ONLY"] = "1"
    from xiaomei_brain.body.perception.face_id import FaceID

    engine = FaceID()
    engine._ensure_loaded()
    inference_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            logging.info(fmt, *args)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/") == "/health":
                send_json(self, 200, health_payload(model="dlib", device="cpu"))
            else:
                send_json(self, 404, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path.rstrip("/") != "/detect":
                send_json(self, 404, {"error": "not_found"})
                return
            temporary = ""
            try:
                value = read_json(self)
                image = base64.b64decode(str(value.get("image_base64") or ""), validate=True)
                if not image:
                    raise ValueError("image_base64 不能为空")
                suffix = str(value.get("suffix") or ".jpg")
                if suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
                    suffix = ".jpg"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as stream:
                    stream.write(image)
                    temporary = stream.name
                with inference_lock:
                    faces = engine.detect_all(temporary)
                send_json(self, 200, {"faces": [
                    {
                        "bbox": list(face["bbox"]),
                        "encoding": face["encoding"].tolist(),
                        "landmarks": {
                            key: [list(point) for point in points]
                            for key, points in face.get("landmarks", {}).items()
                        },
                    }
                    for face in faces
                ]})
            except Exception as exc:
                logging.exception("Face request failed")
                send_json(self, 400, {"error": str(exc)})
            finally:
                if temporary:
                    Path(temporary).unlink(missing_ok=True)

    serve(18769, Handler)
