import { useCallback, useEffect, useMemo, useState } from "react";
import type { DesktopSettings, LocalAIServiceStatus, LocalAISystemStatus } from "../../types";
import { Button, Icon, SelectMenu } from "../ui";

const STATE_LABELS: Record<LocalAIServiceStatus["state"], string> = {
  online: "在线",
  starting: "加载中",
  downloading: "下载中",
  not_installed: "未下载",
  download_error: "下载失败",
  stopped: "已停止",
  unavailable: "不可用",
  available: "待接入",
  error: "异常",
};

export function LocalAIRuntimePanel({ language }: { language: DesktopSettings["language"] }) {
  const [services, setServices] = useState<LocalAIServiceStatus[]>([]);
  const [system, setSystem] = useState<LocalAISystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [log, setLog] = useState<{ id: string; content: string } | null>(null);
  const [downloadTarget, setDownloadTarget] = useState<LocalAIServiceStatus | null>(null);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    const result = await window.localAI.list();
    if (result.ok) {
      setServices(result.services);
      setSystem(result.system || null);
      setError("");
    } else {
      setError(result.error || "无法读取本机 AI 服务状态");
    }
    if (!quiet) setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const summary = useMemo(() => {
    const online = services.filter((item) => item.state === "online").length;
    const active = services.filter((item) => ["starting", "downloading"].includes(item.state)).length;
    return active ? `${active} 项正在准备` : `${online}/${services.length} 项在线`;
  }, [services]);
  const downloadingKey = useMemo(() => services
    .filter((service) => service.state === "downloading")
    .map((service) => `${service.id}:${service.selected_model_id}`)
    .join("|"), [services]);

  useEffect(() => {
    if (!downloadingKey) return undefined;
    const targets = downloadingKey.split("|").map((value) => {
      const [serviceId, modelId] = value.split(":", 2);
      return { serviceId, modelId };
    });
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      const results = await Promise.all(targets.map((target) => window.localAI.downloadProgress(target)));
      if (cancelled) return;
      let terminal = false;
      setServices((current) => current.map((service) => {
        const result = results.find((item) => item.progress?.serviceId === service.id);
        const progress = result?.progress;
        if (!result?.ok || !progress) return service;
        terminal ||= progress.completed || progress.failed;
        return {
          ...service,
          download_progress: progress.progress,
          downloaded_bytes: Math.round(service.expected_size_bytes * progress.progress / 100),
          model_present: progress.completed || service.model_present,
          state: progress.completed ? "stopped" : progress.failed ? "download_error" : "downloading",
          error: progress.error,
        };
      }));
      if (terminal) {
        await load(true);
      } else if (!cancelled) {
        timer = window.setTimeout(() => void poll(), 1_000);
      }
    };
    timer = window.setTimeout(() => void poll(), 400);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [downloadingKey, load]);

  async function control(
    service: LocalAIServiceStatus,
    action: "start" | "stop" | "restart" | "download" | "cancel-download",
  ) {
    setBusy(`${service.id}:${action}`);
    setError("");
    const result = await window.localAI.control({
      serviceId: service.id,
      action,
    });
    if (!result.ok) setError(result.error || `${service.name}操作失败`);
    await load(true);
    setBusy("");
  }

  async function toggleLog(service: LocalAIServiceStatus) {
    if (log?.id === service.id) {
      setLog(null);
      return;
    }
    const result = await window.localAI.readLog({ serviceId: service.id });
    if (!result.ok) {
      setError(result.error || "无法读取服务日志");
      return;
    }
    setLog({ id: service.id, content: result.content || "日志文件目前为空。" });
  }

  async function selectModel(service: LocalAIServiceStatus, modelId: string) {
    if (modelId === service.selected_model_id) return;
    const selected = service.models.find((model) => model.id === modelId);
    setServices((current) => current.map((item) => (
      item.id === service.id
        ? {
          ...item,
          selected_model_id: modelId,
          model: selected?.name || item.model,
          expected_size: selected?.expected_size || item.expected_size,
          expected_size_bytes: selected?.expected_size_bytes || item.expected_size_bytes,
          downloaded_bytes: selected?.downloaded_bytes || 0,
          model_present: selected?.model_present || false,
          model_path: "",
          download_progress: selected?.model_present ? 100 : 0,
          supported_devices: (selected?.supported_devices || item.supported_devices) as LocalAIServiceStatus["supported_devices"],
          state: selected?.model_present ? "stopped" : "not_installed",
          error: "",
        }
        : item
    )));
    setBusy(`${service.id}:select`);
    setError("");
    const result = await window.localAI.selectModel({ serviceId: service.id, modelId });
    if (result.ok && result.service) {
      setServices((current) => current.map((item) => (
        item.id === service.id ? result.service! : item
      )));
    } else {
      setServices((current) => current.map((item) => (
        item.id === service.id ? service : item
      )));
      setError(result.error || `${service.name}模型切换失败`);
    }
    setBusy("");
  }

  async function selectDevice(
    service: LocalAIServiceStatus,
    device: "auto" | "cpu" | "cuda",
  ) {
    if (device === service.selected_device) return;
    setServices((current) => current.map((item) => (
      item.id === service.id ? { ...item, selected_device: device } : item
    )));
    setBusy(`${service.id}:device`);
    setError("");
    const result = await window.localAI.selectDevice({ serviceId: service.id, device });
    if (result.ok && result.service) {
      setServices((current) => current.map((item) => (
        item.id === service.id ? result.service! : item
      )));
    } else {
      setServices((current) => current.map((item) => (
        item.id === service.id ? service : item
      )));
      setError(result.error || `${service.name}运行设备切换失败`);
    }
    setBusy("");
  }

  return (
    <div className="desktop-settings-panel local-ai-runtime-panel">
      <header className="desktop-settings-intro">
        <h2>{language === "zh-CN" ? "本机 AI 服务" : "Local AI services"}</h2>
        <p>{language === "zh-CN"
          ? "下载并运行这台电脑上由所有本机 Agent 共享的模型服务。"
          : "Download and run model services shared by all local Agents on this computer."}</p>
      </header>

      <section className="local-ai-runtime-section">
        <div className="settings-card-heading">
        <div>
          <h3>{language === "zh-CN" ? "共享推理服务" : "Shared inference services"}</h3>
        </div>
        <span className="desktop-setting-status">{loading ? "检查中…" : summary}</span>
      </div>

      {system && (
        <div className="local-ai-system-load" aria-label="系统负载">
          <div>
            <span>CPU</span>
            <strong>{Math.round(system.cpu_percent)}%</strong>
            <meter min={0} max={100} value={system.cpu_percent} />
          </div>
          <div>
            <span>内存</span>
            <strong>{Math.round(system.memory_percent)}%</strong>
            <small>{formatBytes(system.memory_used_bytes)} / {formatBytes(system.memory_total_bytes)}</small>
            <meter min={0} max={100} value={system.memory_percent} />
          </div>
          {system.gpus.map((gpu, index) => (
            <div key={`${gpu.name}:${index}`} title={gpu.name}>
              <span>GPU{system.gpus.length > 1 ? ` ${index + 1}` : ""}</span>
              <strong>{Math.round(gpu.utilization_percent)}%</strong>
              <small>{formatBytes(gpu.memory_used_bytes)} / {formatBytes(gpu.memory_total_bytes)} 显存</small>
              <meter min={0} max={100} value={gpu.utilization_percent} />
            </div>
          ))}
        </div>
      )}

      <div className="local-ai-service-list">
        {services.map((service) => {
          const working = busy.startsWith(`${service.id}:`);
          return (
            <article className="local-ai-service-row" key={service.id}>
              <span className="desktop-setting-icon"><Icon name="cpu" size={17} /></span>
              <div className="local-ai-service-copy">
                <div className="local-ai-service-title">
                  <strong>{service.name}</strong>
                  {service.required && <span className="local-ai-required">核心依赖</span>}
                  <span className={`local-ai-state ${service.state}`}>{STATE_LABELS[service.state]}</span>
                </div>
                <p>{service.description}</p>
                <div className="local-ai-runtime-controls">
                  {(service.models.length > 1 || service.supported_devices.length > 1) && (
                    <div className="local-ai-runtime-selectors">
                    {service.models.length > 1 && (
                      <label className="local-ai-model-selector is-model">
                        <span>模型</span>
                        <SelectMenu
                          value={service.selected_model_id}
                          placeholder="选择模型"
                          disabled={working || service.selection_locked || ["online", "starting", "downloading"].includes(service.state)}
                          options={service.models.map((model) => ({
                            value: model.id,
                            label: model.name,
                            description: `${model.expected_size}${model.model_present ? " · 已下载" : ""}`,
                          }))}
                          onChange={(value) => void selectModel(service, value)}
                        />
                      </label>
                    )}
                    {service.supported_devices.length > 1 && (
                      <label className="local-ai-model-selector is-device">
                        <span>运行设备</span>
                        <SelectMenu
                          value={service.selected_device}
                          placeholder="选择设备"
                          disabled={working || ["online", "starting", "downloading"].includes(service.state)}
                          options={[
                            ...(service.supported_devices.includes("auto") ? [{ value: "auto", label: "自动" }] : []),
                            ...(service.supported_devices.includes("cpu") ? [{ value: "cpu", label: "CPU" }] : []),
                            ...(service.supported_devices.includes("cuda") && system?.gpus.length
                              ? [{ value: "cuda", label: "CUDA", description: system.gpus[0]?.name }]
                              : []),
                          ]}
                          onChange={(value) => void selectDevice(
                            service,
                            value as "auto" | "cpu" | "cuda",
                          )}
                        />
                      </label>
                    )}
                    </div>
                  )}
                  <div className="local-ai-service-actions">
                    {service.downloadable && !service.model_present && service.state !== "downloading" && (
                      <Button size="sm" disabled={working} onClick={() => setDownloadTarget(service)}>
                        {service.state === "download_error" ? "重试下载" : "下载"}
                      </Button>
                    )}
                    {service.state === "downloading" && (
                      <Button size="sm" variant="secondary" disabled={working} onClick={() => void control(service, "cancel-download")}>取消</Button>
                    )}
                    {service.controllable && service.installed && service.model_present && ["stopped", "error"].includes(service.state) && (
                      <Button size="sm" variant="secondary" disabled={working} onClick={() => void control(service, "start")}>启动</Button>
                    )}
                    {service.controllable && service.state === "starting" && (
                      <Button size="sm" variant="secondary" disabled={working} onClick={() => void control(service, "stop")}>停止</Button>
                    )}
                    {service.controllable && service.state === "online" && (
                      <Button size="sm" variant="secondary" disabled={working} onClick={() => void control(service, "restart")}>重启</Button>
                    )}
                    {service.controllable && service.state === "online" && (
                      <Button size="sm" variant="ghost" disabled={working} onClick={() => void control(service, "stop")}>停止</Button>
                    )}
                    {service.controllable && (
                      <Button size="sm" variant="ghost" onClick={() => void toggleLog(service)}>
                        {log?.id === service.id ? "收起日志" : "日志"}
                      </Button>
                    )}
                  </div>
                </div>
                <small>
                  {service.model} · {service.expected_size}
                  {service.state === "online" ? ` · 实际运行于 ${service.device.toUpperCase()}` : ` · ${deviceLabel(service.selected_device)}`}
                  {service.pid ? ` · PID ${service.pid}` : ""}
                </small>
                {["online", "starting"].includes(service.state) && (
                  <small className="local-ai-resource-usage">
                    {service.memory_bytes > 0 ? `内存 ${formatBytes(service.memory_bytes)}` : "内存暂不可统计"}
                    {service.gpu_memory_bytes > 0
                      ? ` · 显存 ${formatBytes(service.gpu_memory_bytes)}${service.gpu_memory_total_bytes > 0 ? ` / ${formatBytes(service.gpu_memory_total_bytes)}` : ""}`
                      : service.device.startsWith("cuda") ? " · 显存暂不可统计" : ""}
                  </small>
                )}
                {service.model_path && <small title={service.model_path}>位置：{service.model_path}</small>}
                {service.selection_locked && (
                  <small className="local-ai-selection-lock">
                    已锁定：{service.selection_lock_reason || "该模型已经产生兼容性数据"}
                  </small>
                )}
                {service.downloadable
                  && !service.model_present
                  && ["downloading", "download_error"].includes(service.state) && (
                  <div className="local-ai-download-progress">
                    <div className="local-ai-download-track" aria-label={`下载进度 ${service.download_progress}%`}>
                      <span style={{ width: `${service.download_progress}%` }} />
                    </div>
                    <small>
                      {formatBytes(service.downloaded_bytes)} / {formatBytes(service.expected_size_bytes)}
                      {service.state === "downloading" ? ` · ${service.download_progress}%` : ""}
                    </small>
                  </div>
                )}
                {service.error && <small className="local-ai-error">{service.error}</small>}
              </div>
            </article>
          );
        })}
        {!loading && services.length === 0 && <div className="settings-empty">没有发现本机 AI 服务。</div>}
      </div>

      <div className="local-ai-runtime-footer">
        <Button variant="secondary" size="sm" onClick={() => void load()}>刷新状态</Button>
        <Button variant="ghost" size="sm" onClick={() => void window.localAI.openDirectory()}>打开服务目录</Button>
      </div>
      {log && <pre className="desktop-settings-log local-ai-log">{log.content}</pre>}
      {error && <p className="settings-error">{error}</p>}
      </section>
      {downloadTarget && (
        <DownloadConfirmationDialog
          service={downloadTarget}
          onCancel={() => setDownloadTarget(null)}
          onConfirm={() => {
            const target = downloadTarget;
            setDownloadTarget(null);
            void control(target, "download");
          }}
        />
      )}
    </div>
  );
}

function DownloadConfirmationDialog({
  service,
  onCancel,
  onConfirm,
}: {
  service: LocalAIServiceStatus;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const model = service.models.find((item) => item.id === service.selected_model_id);
  const remaining = Math.max(0, service.expected_size_bytes - service.downloaded_bytes);
  return (
    <div className="model-editor-backdrop" onMouseDown={onCancel}>
      <section
        className="model-editor-dialog local-ai-download-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="local-ai-download-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="model-editor-header">
          <div>
            <h2 id="local-ai-download-title">下载 {model?.name || service.model}</h2>
            <p>模型将保存到本机共享缓存，供所有本机 Agent 使用。</p>
          </div>
          <button type="button" aria-label="关闭" onClick={onCancel}>
            <Icon name="x" size={18} />
          </button>
        </header>
        <div className="model-editor-body local-ai-download-body">
          <dl>
            <div><dt>服务</dt><dd>{service.name}</dd></div>
            <div><dt>模型</dt><dd>{model?.name || service.model}</dd></div>
            <div><dt>来源</dt><dd>{model?.source || "未声明"}</dd></div>
            <div><dt>预计大小</dt><dd>{service.expected_size}</dd></div>
            <div><dt>尚需下载</dt><dd>{formatBytes(remaining)}</dd></div>
          </dl>
          <p>下载可能持续数分钟，并占用网络带宽和磁盘空间。下载期间可以取消，之后可继续重试。</p>
        </div>
        <footer className="model-editor-footer">
          <span>确认后才会开始联网下载。</span>
          <div>
            <Button variant="secondary" onClick={onCancel}>取消</Button>
            <Button variant="primary" onClick={onConfirm}>确认下载</Button>
          </div>
        </footer>
      </section>
    </div>
  );
}

function formatBytes(value: number): string {
  if (!value) return "0 MB";
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(1)} GB`;
  return `${Math.max(1, Math.round(value / 1024 ** 2))} MB`;
}

function deviceLabel(device: "auto" | "cpu" | "cuda"): string {
  if (device === "auto") return "自动选择设备";
  return device.toUpperCase();
}
