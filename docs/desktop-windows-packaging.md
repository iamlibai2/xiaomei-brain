# Desktop Windows packaging

The Windows installer contains two independently versioned layers:

- Electron Desktop UI and main process.
- A portable Python 3.11 Agent Runtime distributed as
  `resources/runtime-package/agent-runtime.zip`.

Agent configuration, memory, logs, and models remain in
`%USERPROFILE%\.xiaomei-brain`. Installing, upgrading, or uninstalling the
Desktop application does not remove that directory.

On first packaged launch, Desktop verifies the archive SHA256 and extracts the
Runtime to `%LOCALAPPDATA%\xiaomei-brain\runtimes\<agent-version>-<hash>`.
This cache is independent of Agent data and can be recreated from the package.

The first packaged release uses a one-click installation for the current
Windows user. It does not request administrator privileges or show an install
scope/directory wizard.

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
2. Installs `xiaomei-brain` and its core dependencies into that runtime.
3. Removes bytecode caches, test suites, Tcl/Tk data, and native development
   headers that are not needed by the packaged Agent.
4. Verifies the pruned Runtime imports.
5. Creates `agent-runtime.zip` and a schema-2 manifest containing its SHA256,
   compressed size, uncompressed size, and file count.
6. Builds the Electron application.
7. Creates an MSI installer under `release/`.

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

The MSI build skips WiX ICE validation because restricted Windows build
sessions may not expose the Windows Installer service to the linker. The
resulting package must still pass an actual `msiexec` install/uninstall smoke
test before release.

The prototype sets `signAndEditExecutable: false`, so it can build without a
Windows code-signing certificate or symlink privileges. Enable executable
editing/signing and configure a certificate before public distribution.

Both `runtime-stage/` and `release/` are generated artifacts and are ignored by
Git.

## Embedding boundary

The Desktop runtime does not include PyTorch, Sentence Transformers, ModelScope,
or model weights. Its curated dependencies are listed in
`runtime-requirements.txt`, and it expects the shared embedding HTTP service
when semantic features are needed. A normal Python package installation keeps
the existing local embedding dependencies.

A later installer phase can download a CPU or CUDA embedding component without
making every Desktop installation carry GPU-specific packages and model files.
