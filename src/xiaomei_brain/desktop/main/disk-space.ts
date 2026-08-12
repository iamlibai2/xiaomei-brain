import { promises as fs } from "fs";
import path from "path";

function formatGiB(bytes: number): string {
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

async function existingDirectory(candidate: string): Promise<string> {
  let current = path.resolve(candidate);
  while (true) {
    try {
      const stat = await fs.stat(current);
      if (stat.isDirectory()) return current;
      current = path.dirname(current);
    } catch {
      const parent = path.dirname(current);
      if (parent === current) throw new Error(`无法确定安装磁盘：${candidate}`);
      current = parent;
    }
  }
}

/**
 * Fail before a large extraction or dependency installation starts.
 *
 * Callers provide the complete peak working-space budget, including temporary
 * archives and safety reserve. Keeping that estimate at the component boundary
 * makes the number visible and avoids silently adding the same reserve twice.
 */
export async function ensureDiskSpace(
  targetPath: string,
  requiredBytes: number,
  operation: string,
): Promise<void> {
  if (!Number.isFinite(requiredBytes) || requiredBytes <= 0) return;
  const directory = await existingDirectory(targetPath);
  const stat = await fs.statfs(directory);
  const availableBytes = Number(stat.bavail) * Number(stat.bsize);
  const required = Math.ceil(requiredBytes);
  if (availableBytes >= required) return;
  throw new Error(
    `磁盘空间不足，无法${operation}：需要至少 ${formatGiB(required)}，`
    + `当前可用 ${formatGiB(availableBytes)}。请清理空间后重试。`,
  );
}
