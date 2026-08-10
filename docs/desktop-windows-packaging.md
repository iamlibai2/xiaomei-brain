# Desktop Windows packaging

The Windows installer contains two independently versioned layers:

- Electron Desktop UI and main process.
- A portable Agent Runtime containing Python 3.11 and Node.js LTS, distributed as
  `resources/runtime-package/agent-runtime.zip`.

Agent configuration, memory, logs, and models remain in
`%USERPROFILE%\.xiaomei-brain`. Installing, upgrading, or uninstalling the
Desktop application does not remove that directory.

On first packaged launch, Desktop verifies the archive SHA256 and extracts the
Runtime to `%LOCALAPPDATA%\xiaomei-brain\runtimes\<agent-version>-<hash>`.
This cache is independent of Agent data and can be recreated from the package.

The Windows package uses an assisted all-users installation. It requests
elevation, shows the installation directory and progress pages, and lets the
person choose a destination under `Program Files` or another writable drive.
Uninstalling the Desktop application does not delete Agent data under the
person's profile.

## Build prerequisites

- Windows x64.
- Node.js and the Desktop npm dependencies.
- `uv` available on `PATH` (or set `UV_EXE`).
- A 64-bit CPython 3.11 environment activated through `VIRTUAL_ENV`, or set
  `XIAOMEI_BRAIN_BUILD_PYTHON` to its `python.exe`.

## Build

From `src/xiaomei_brain/desktop`:

```powershell
npm run package:win
```

The command performs these steps:

1. Copies the base CPython distribution into `runtime-stage/runtime/python`.
2. Downloads the pinned official Node.js Windows x64 archive, verifies it
   against `SHASUMS256.txt`, and includes Node.js, npm, and npx under
   `runtime-stage/runtime/node`.
3. Installs `xiaomei-brain` and its core dependencies into that runtime.
4. Removes bytecode caches, test suites, Tcl/Tk data, and native development
   headers that are not needed by the packaged Agent.
5. Verifies Python imports and the bundled Node.js/npm/npx executables.
6. Creates `agent-runtime.zip` and a schema-3 manifest containing its SHA256,
   compressed size, uncompressed size, and file count.
7. Builds the Electron application.
8. Creates an NSIS installer and updater metadata under `release/`.

## Runtime initialization

Desktop starts Runtime initialization in the background after its window is
created. Initialization uses a per-version lock and extracts into a unique
staging directory. It verifies both the archive hash and key Python imports,
then atomically renames the staging directory into the versioned Runtime path.
An interrupted extraction is never treated as ready, and stale locks can be
recovered on a later launch.

Set `XIAOMEI_BRAIN_RUNTIME_HOME` to override the extraction root for packaging
smoke tests. Existing `XIAOMEI_BRAIN_RUNTIME`, `XIAOMEI_BRAIN_PYTHON`, and
legacy directly bundled Runtime paths remain supported.

The prototype sets `signAndEditExecutable: false`, so it can build without a
Windows code-signing certificate or symlink privileges. Enable executable
editing/signing and configure a certificate before public distribution.

Both `runtime-stage/` and `release/` are generated artifacts and are ignored by
Git.

## First-run components

The NSIS package stays small by separating the Agent Runtime from host-local
inference and media components:

- `runtime-requirements.txt` contains only the Agent's core runtime.
- `ai-runtime-requirements.txt` is installed after the person chooses CPU or
  NVIDIA CUDA acceleration during first-run setup.
- PyTorch 2.6 is installed from the explicit official CPU or CUDA 12.4 wheel
  index. A CUDA selection is installed directly; setup never downloads CPU
  PyTorch first and replaces it afterwards.
- The selected embedding model is mandatory and is downloaded and started
  before normal Agent startup.
- FFmpeg/FFprobe is recommended but optional. On Windows it is downloaded as
  the release essentials build, verified against the publisher's SHA256, and
  stored under `%LOCALAPPDATA%\xiaomei-brain\components`.
- STT, TTS, face, voiceprint, and their model weights remain opt-in services.

Completed setup is recorded outside the application directory and tied to the
resolved Python Runtime path. Normal launches read that marker and do not render
or execute the first-run flow. Runtime upgrades naturally require the inference
component to be prepared once for the new Python Runtime.

Managed FFmpeg is added only to child-process `PATH`; setup does not modify the
user or machine environment variables. All local Agents share these host
components, while a remote Agent remains responsible for its own dependencies.
The bundled Node.js directory is injected into local Agent child-process
`PATH` in the same way, so `node`, `npm`, and `npx` work without a system-wide
Node.js installation.
