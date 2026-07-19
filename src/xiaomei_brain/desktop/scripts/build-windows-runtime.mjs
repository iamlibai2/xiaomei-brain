import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { cp, mkdir, readFile, readdir, realpath, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

if (process.platform !== "win32") {
  throw new Error("The Windows runtime builder must run on Windows");
}

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const desktopDir = path.resolve(scriptDir, "..");
const repoRoot = path.resolve(desktopDir, "../../..");
const stageRoot = path.resolve(desktopDir, "runtime-stage");
const runtimeDir = path.join(stageRoot, "runtime");
const runtimePackageDir = path.join(stageRoot, "package");
const runtimePythonDir = path.join(runtimeDir, "python");
const runtimePython = path.join(runtimePythonDir, "python.exe");
const runtimeArchive = path.join(runtimePackageDir, "agent-runtime.zip");
const runtimeRequirements = path.join(desktopDir, "runtime-requirements.txt");

if (path.dirname(stageRoot) !== desktopDir || path.basename(stageRoot) !== "runtime-stage") {
  throw new Error(`Unsafe runtime staging path: ${stageRoot}`);
}

function findBuildPython() {
  if (process.env.XIAOMEI_BRAIN_BUILD_PYTHON) {
    return process.env.XIAOMEI_BRAIN_BUILD_PYTHON;
  }
  if (process.env.VIRTUAL_ENV) {
    return path.join(process.env.VIRTUAL_ENV, "Scripts", "python.exe");
  }
  return "python.exe";
}

function run(executable, args, options = {}) {
  const result = spawnSync(executable, args, {
    cwd: repoRoot,
    env: { ...process.env, PYTHONUTF8: "1", UV_LINK_MODE: process.env.UV_LINK_MODE || "copy" },
    stdio: "inherit",
    windowsHide: true,
    ...options,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${executable} exited with code ${result.status}`);
  }
}

function readPythonInfo(executable) {
  const script = [
    "import json, platform, struct, sys",
    "print(json.dumps({",
    "  'base_prefix': sys.base_prefix,",
    "  'version': platform.python_version(),",
    "  'architecture': struct.calcsize('P') * 8,",
    "}))",
  ].join("\n");
  return JSON.parse(execFileSync(executable, ["-c", script], {
    cwd: repoRoot,
    encoding: "utf8",
    windowsHide: true,
  }));
}

async function directorySize(directory) {
  let total = 0;
  const entries = await (await import("node:fs/promises")).readdir(directory, { withFileTypes: true });
  for (const entry of entries) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) total += await directorySize(entryPath);
    else if (entry.isFile()) total += (await stat(entryPath)).size;
  }
  return total;
}

async function directoryFileCount(directory) {
  let total = 0;
  const entries = await readdir(directory, { withFileTypes: true });
  for (const entry of entries) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) total += await directoryFileCount(entryPath);
    else if (entry.isFile()) total += 1;
  }
  return total;
}

function hashFile(filePath) {
  return new Promise((resolve, reject) => {
    const hash = createHash("sha256");
    const input = createReadStream(filePath);
    input.on("error", reject);
    input.on("data", (chunk) => hash.update(chunk));
    input.on("end", () => resolve(hash.digest("hex")));
  });
}

async function removeNamedDirectories(directory, names) {
  const entries = await readdir(directory, { withFileTypes: true });
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const entryPath = path.join(directory, entry.name);
    if (names.has(entry.name.toLowerCase())) {
      await rm(entryPath, { recursive: true, force: true });
    } else {
      await removeNamedDirectories(entryPath, names);
    }
  }
}

async function pruneRuntime() {
  const removableDirectories = [
    path.join(runtimePythonDir, "Include"),
    path.join(runtimePythonDir, "tcl"),
    path.join(runtimePythonDir, "Lib", "tkinter"),
    path.join(runtimePythonDir, "Lib", "site-packages", "pyarrow", "include"),
    path.join(runtimePythonDir, "Lib", "site-packages", "numpy", "_core", "include"),
  ];
  for (const directory of removableDirectories) {
    await rm(directory, { recursive: true, force: true });
  }

  await removeNamedDirectories(runtimePythonDir, new Set(["__pycache__", "test", "tests"]));
}

const buildPython = findBuildPython();
const pythonInfo = readPythonInfo(buildPython);
const pythonBaseDir = await realpath(pythonInfo.base_prefix);
if (!pythonInfo.version.startsWith("3.11.")) {
  throw new Error(`Windows runtime requires Python 3.11, found ${pythonInfo.version}`);
}
if (pythonInfo.architecture !== 64) {
  throw new Error(`Windows runtime requires 64-bit Python, found ${pythonInfo.architecture}-bit`);
}

console.log(`[runtime] source Python: ${pythonBaseDir}`);
console.log(`[runtime] staging at: ${runtimeDir}`);

await rm(stageRoot, { recursive: true, force: true });
await mkdir(runtimeDir, { recursive: true });
await cp(pythonBaseDir, runtimePythonDir, {
  recursive: true,
  filter(source) {
    const normalized = source.replaceAll("\\", "/");
    return !normalized.includes("/__pycache__/")
      && !normalized.endsWith("/__pycache__")
      && !normalized.endsWith(".pyc");
  },
});

const uvExecutable = process.env.UV_EXE || "uv.exe";
run(uvExecutable, [
  "pip", "install",
  "--python", runtimePython,
  "--break-system-packages",
  "--strict",
  "--no-compile",
  "--requirements", runtimeRequirements,
]);
run(uvExecutable, [
  "pip", "install",
  "--python", runtimePython,
  "--break-system-packages",
  "--no-deps",
  "--no-compile",
  repoRoot,
]);

await pruneRuntime();

run(runtimePython, [
  "-c",
  [
    "import fastapi, lancedb, numpy, psutil, pyarrow, xiaomei_brain",
    "import win32com.client",
    "from xiaomei_brain.cli.lifecycle import _build_restart_args",
    "assert _build_restart_args('agent', ['--cli']) == ['agent']",
    "print('bundled runtime import check: ok')",
  ].join("; "),
], {
  env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONUTF8: "1" },
});

await mkdir(runtimePackageDir, { recursive: true });
run(runtimePython, [
  "-c",
  [
    "from pathlib import Path",
    "from zipfile import ZIP_DEFLATED, ZipFile",
    "import sys",
    "root = Path(sys.argv[1])",
    "destination = Path(sys.argv[2])",
    "with ZipFile(destination, 'w', compression=ZIP_DEFLATED, compresslevel=9, allowZip64=True) as archive:",
    "    for file in sorted(root.rglob('*')):",
    "        if file.is_file():",
    "            archive.write(file, Path('python') / file.relative_to(root))",
  ].join("\n"),
  runtimePythonDir,
  runtimeArchive,
], {
  env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONUTF8: "1" },
});

const runtimeSizeBytes = await directorySize(runtimeDir);
const runtimeFileCount = await directoryFileCount(runtimeDir);
const archiveSizeBytes = (await stat(runtimeArchive)).size;
const archiveSha256 = await hashFile(runtimeArchive);

const project = JSON.parse(await readFile(path.join(desktopDir, "package.json"), "utf8"));
const pyproject = await readFile(path.join(repoRoot, "pyproject.toml"), "utf8");
const agentVersion = pyproject.match(/^version\s*=\s*"([^"]+)"/m)?.[1];
if (!agentVersion) throw new Error("Unable to read Agent version from pyproject.toml");
let revision = "unknown";
try {
  revision = execFileSync("git", ["rev-parse", "--short", "HEAD"], {
    cwd: repoRoot,
    encoding: "utf8",
    windowsHide: true,
  }).trim();
} catch {
  // Source archives may not include Git metadata.
}

const manifest = {
  schemaVersion: 2,
  component: "agent-runtime",
  desktopVersion: project.version,
  agentVersion,
  pythonVersion: pythonInfo.version,
  architecture: `x${pythonInfo.architecture}`,
  revision,
  embeddingBundled: false,
  archive: path.basename(runtimeArchive),
  archiveSha256,
  archiveSizeBytes,
  runtimeSizeBytes,
  runtimeFileCount,
  builtAt: new Date().toISOString(),
};
await writeFile(path.join(runtimePackageDir, "runtime-manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");

console.log(`[runtime] ready: ${(runtimeSizeBytes / 1024 / 1024).toFixed(1)} MiB across ${runtimeFileCount} files`);
console.log(`[runtime] archive: ${(archiveSizeBytes / 1024 / 1024).toFixed(1)} MiB (${archiveSha256})`);
console.log(`[runtime] manifest: ${path.join(runtimePackageDir, "runtime-manifest.json")}`);
