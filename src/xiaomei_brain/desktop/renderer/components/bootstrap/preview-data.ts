import type { LocalAIModelOption, LocalAIServiceStatus, LocalAISystemStatus } from "../../types";

function model(
  id: string,
  name: string,
  expectedSize: string,
  devices: Array<"auto" | "cpu" | "cuda">,
): LocalAIModelOption {
  return {
    id,
    name,
    source: "preview",
    expected_size: expectedSize,
    expected_size_bytes: 0,
    downloaded_bytes: 0,
    model_present: false,
    recommended_device: devices.includes("cuda") ? "cuda" : "cpu",
    supported_devices: devices,
  };
}

function service(
  id: LocalAIServiceStatus["id"],
  name: string,
  models: LocalAIModelOption[],
): LocalAIServiceStatus {
  const selected = models[0];
  return {
    id,
    name,
    description: "",
    model: selected.name,
    selected_model_id: selected.id,
    models,
    selection_locked: false,
    selection_lock_reason: "",
    selected_device: "cpu",
    supported_devices: ["cpu", "cuda"],
    expected_size: selected.expected_size,
    endpoint: "",
    required: id === "embedding",
    controllable: true,
    downloadable: true,
    installed: true,
    missing_dependencies: [],
    model_present: false,
    model_path: "",
    expected_size_bytes: 0,
    downloaded_bytes: 0,
    download_progress: 0,
    state: "available",
    pid: null,
    started_at: "",
    device: "cpu",
    health: {},
    memory_bytes: 0,
    system_memory_total_bytes: 0,
    gpu_memory_bytes: 0,
    gpu_memory_total_bytes: 0,
    error: "",
    log_path: "",
    download_log_path: "",
  };
}

export const PREVIEW_LOCAL_AI_SYSTEM: LocalAISystemStatus = {
  cpu_percent: 18,
  memory_percent: 42,
  memory_used_bytes: 0,
  memory_total_bytes: 0,
  gpus: [{
    name: "NVIDIA GPU（预览）",
    utilization_percent: 0,
    memory_used_bytes: 0,
    memory_total_bytes: 0,
  }],
};

export const PREVIEW_LOCAL_AI_SERVICES: LocalAIServiceStatus[] = [
  service("embedding", "记忆向量", [
    model("bge-m3", "BGE-M3", "约 4.6 GB", ["cpu", "cuda"]),
    model("bge-small-zh-v1.5", "BGE Small 中文", "约 95 MB", ["cpu", "cuda"]),
  ]),
  service("stt", "语音识别", [
    model("sensevoice-small", "SenseVoice Small", "约 900 MB", ["cpu", "cuda"]),
    model("whisper-small", "Whisper Small", "约 500 MB", ["cpu", "cuda"]),
  ]),
  service("tts_voxcpm", "语音合成", [
    model("voxcpm", "VoxCPM", "约 4 GB", ["cpu", "cuda"]),
  ]),
  service("voiceprint", "声纹识别", [
    model("ecapa-tdnn", "ECAPA-TDNN", "约 100 MB", ["cpu", "cuda"]),
  ]),
  service("face", "人脸识别", [
    model("dlib-face", "dlib Face Recognition", "约 100 MB", ["cpu"]),
  ]),
];

export const PREVIEW_EMBEDDING_SERVICE = PREVIEW_LOCAL_AI_SERVICES[0];
