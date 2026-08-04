"""Download model weights into machine-wide caches.

This process intentionally does not load inference models. The Desktop runtime
manager supervises it and derives progress from cache size, so downloads can be
cancelled without coupling the renderer to ModelScope or Hugging Face APIs.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path


_DEFAULT_HUGGINGFACE_ENDPOINTS = (
    "https://hf-mirror.com",
    "https://huggingface.co",
)


def _download_huggingface(repo_id: str) -> str:
    """Download from an explicit endpoint and fall back to the official Hub.

    Some Hugging Face mirrors serve model files but omit metadata headers used
    by newer huggingface_hub clients. Keep the mirror as the first choice for
    domestic networks, then retry against the official endpoint when the
    metadata request fails. An explicitly configured HF_ENDPOINT remains the
    user's only endpoint and is never silently bypassed.
    """
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    from huggingface_hub import snapshot_download

    configured = os.environ.get("HF_ENDPOINT", "").strip().rstrip("/")
    endpoints = (configured,) if configured else _DEFAULT_HUGGINGFACE_ENDPOINTS
    failures: list[str] = []
    for endpoint in endpoints:
        logging.info("Downloading Hugging Face model %s from %s", repo_id, endpoint)
        try:
            return str(snapshot_download(repo_id, endpoint=endpoint, max_workers=4))
        except Exception as exc:
            failures.append(f"{endpoint}: {exc}")
            logging.warning("Download from %s failed: %s", endpoint, exc)
    raise RuntimeError(
        f"Failed to download {repo_id}; " + " | ".join(failures)
    )


def _download_whisper_small() -> str:
    """Prefer the multilingual ModelScope mirror for mainland networks."""
    try:
        from modelscope import snapshot_download

        repo_id = "openai-mirror/whisper-small"
        logging.info("Downloading Whisper Small from ModelScope: %s", repo_id)
        return str(snapshot_download(
            repo_id,
            max_workers=4,
            allow_file_pattern=[
                "model.safetensors",
                "config.json",
                "generation_config.json",
                "preprocessor_config.json",
                "tokenizer.json",
                "tokenizer_config.json",
                "special_tokens_map.json",
                "added_tokens.json",
                "normalizer.json",
                "vocab.json",
                "merges.txt",
            ],
        ))
    except Exception as exc:
        logging.warning("ModelScope download failed; trying Hugging Face sources: %s", exc)
        return _download_huggingface("openai/whisper-small")


def download(service_id: str, model_id: str) -> str:
    if service_id == "embedding" and model_id == "bge-m3":
        from modelscope import snapshot_download

        return str(snapshot_download("BAAI/bge-m3"))
    if service_id == "embedding" and model_id == "bge-small-zh-v1.5":
        return _download_huggingface("BAAI/bge-small-zh-v1.5")
    if service_id == "stt" and model_id == "sensevoice-small":
        from modelscope import snapshot_download

        return str(snapshot_download("iic/SenseVoiceSmall"))
    if service_id == "stt" and model_id == "whisper-small":
        return _download_whisper_small()
    if service_id == "tts_voxcpm" and model_id == "voxcpm-1.5":
        return _download_huggingface("openbmb/VoxCPM1.5")
    if service_id == "voiceprint" and model_id == "ecapa-voxceleb":
        return _download_huggingface("speechbrain/spkrec-ecapa-voxceleb")
    raise ValueError(f"Model is not downloadable: {service_id}:{model_id}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("service", choices=("embedding", "stt", "tts_voxcpm", "voiceprint"))
    parser.add_argument("--model", required=True)
    parser.add_argument("--completion-file", default="")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.info("Starting model download: service=%s model=%s", args.service, args.model)
    location = download(args.service, args.model)
    if args.completion_file:
        destination = Path(args.completion_file)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"service": args.service, "model": args.model, "model_path": location}, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(destination)
    logging.info("Model download completed: %s", location)


if __name__ == "__main__":
    main()
