"""Launch one concrete model worker for a host-local AI service."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .catalog import DEFAULT_MODELS, get_model_spec
from .selection import ModelSelectionStore, base_dir_for_runtime


def run(service_id: str, model_id: str, device: str, model_path: str, runtime_dir: str) -> None:
    get_model_spec(service_id, model_id)
    logging.info(
        "Starting local AI service: service=%s model=%s device=%s",
        service_id,
        model_id,
        device,
    )

    if service_id == "embedding" and model_id == "bge-m3":
        from .models.embedding_bge_m3 import run as run_model

        store = ModelSelectionStore(base_dir_for_runtime(runtime_dir))
        run_model(
            device,
            model_path,
            lambda: store.lock(
                "embedding",
                model_id,
                "当前 Embedding 已写入向量数据，不能直接更换模型",
            ),
        )
        return
    if service_id == "embedding" and model_id == "bge-small-zh-v1.5":
        from .models.embedding_bge_small_zh import run as run_model

        store = ModelSelectionStore(base_dir_for_runtime(runtime_dir))
        run_model(
            device,
            model_path,
            lambda: store.lock(
                "embedding",
                model_id,
                "当前 Embedding 已写入向量数据，不能直接更换模型",
            ),
        )
        return
    if service_id == "stt" and model_id == "sensevoice-small":
        from .models.stt_sensevoice import run as run_model

        run_model(device, model_path)
        return
    if service_id == "stt" and model_id == "whisper-small":
        from .models.stt_whisper_small import run as run_model

        run_model(device, model_path)
        return
    if service_id == "tts_voxcpm" and model_id == "voxcpm-1.5":
        from .models.tts_voxcpm import run as run_model

        run_model(device, model_path)
        return
    if service_id == "voiceprint" and model_id == "ecapa-voxceleb":
        from .models.voiceprint_ecapa import run as run_model

        run_model(device, model_path)
        return
    if service_id == "face" and model_id == "dlib":
        from .models.face_dlib import run as run_model

        run_model(device, model_path)
        return
    raise ValueError(f"No worker for {service_id}:{model_id}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("service", choices=tuple(DEFAULT_MODELS))
    parser.add_argument("--model", default="")
    parser.add_argument("--model-path", default="")
    parser.add_argument("--runtime-dir", default=str(Path.home() / ".xiaomei-brain" / "runtime" / "ai-services"))
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    args = parser.parse_args()
    model_id = args.model or ModelSelectionStore(base_dir_for_runtime(args.runtime_dir)).selected(args.service)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run(args.service, model_id, args.device, args.model_path, args.runtime_dir)


if __name__ == "__main__":
    main()
