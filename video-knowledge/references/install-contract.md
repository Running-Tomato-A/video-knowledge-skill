# Installation Contract

Read this reference only when installing, reconfiguring, migrating, upgrading, or troubleshooting the local runtime.

## Plan

`scripts/setup.py --plan` is read-only. It may inspect the real machine and run Doctor, but it must not create directories, write configuration, install packages, download models, move files, delete data, or change the installed Skill.

The plan must separate:

- capabilities that can be reused;
- required actions before local video analysis works;
- optional adapters that do not block local files;
- estimated download/disk use;
- selected data and output locations;
- actions requiring network or administrator approval.

If no required action remains, say that the environment is already ready and do not ask for installation confirmation.

The plan must return `blocked`, set `confirmation_required: false`, and list structured `blockers` when the detected platform, architecture, or Python version has no verified Apply recipe. It must not show an unverified platform as merely waiting for confirmation.

## Platform evidence

The current verified Apply target is Windows x64 with Python 3.12. A different Python minor version must be blocked during Plan if Apply would reject it later.

macOS Apple Silicon is an evidence-gathering target, not a supported Apply target. Before installing anything, run:

```text
python scripts/macos_preflight.py --workspace /absolute/workspace
```

The preflight is read-only and reports architecture, non-sensitive OS information, available Python 3.12, Homebrew, FFmpeg／FFprobe, workspace disk space, and remaining blockers. It must not install Homebrew, Rosetta, Python, FFmpeg, packages, or models. Generate a macOS arm64 lock only after a clean isolated-environment install and transcription/frame-extraction smoke test succeed on real hardware. Intel macOS requires separate evidence and a separate lock.

## Apply

`--apply` is a mutating mode and must not be inferred from `--plan`. Before Apply, show one concise confirmation page and obtain authorization for the stated paths, downloads, and system changes. The caller must pass `--yes`; absence of that flag must leave the filesystem unchanged.

Apply must be idempotent: reuse valid dependencies, models, configuration, videos, and formal outputs. Back up an existing config before changing it. Never delete or overwrite user media or completed analyses as part of setup.

The ordinary post-confirmation entrypoint is `python scripts/setup.py --apply --yes`. It must run the verified stages in order and stop at the first structured failure. A later run resumes by validating and reusing completed state. `--stage` exists for development and targeted repair, not as a normal user workflow.

The current v0.1 Apply implements five stages:

- `runtime-dependencies`: directories, Python 3.12 venv, Windows locked dependencies, configuration, and a stage receipt;
- `model`: prerequisite verification, pinned Hugging Face download, manifest verification, reuse, and a model receipt.
- `ffmpeg`: prerequisite verification, existing FFmpeg／FFprobe reuse, optional Windows Winget recipe, synthetic media probe and frame-wrapper smoke test, and an FFmpeg receipt.
- `skill`: controlled Skill manifest, staged copy, fingerprint verification, whole-directory backup on update, reuse, and a Skill receipt outside the installed Skill directory.
- `verify`: all four prerequisite receipts, pinned-model integrity, installed-Skill fingerprint, full Doctor, a one-second local inference smoke test, and the final installation receipt.

The first four must return `complete_installation: false`. Do not describe the whole installation as complete until Verify returns `complete_installation: true`. Verify may accept `ready_with_warnings` only when no required check is missing; record every optional warning in the final receipt.

The verified Windows lock must pin both exact versions and SHA-256 hashes for the compatible wheels. Runtime Apply must use pip `--require-hashes` and reject an unhashed lock before creating installation directories. Regenerate the lock, license snapshot, vulnerability snapshot, and clean-install evidence together after any dependency change.

Skill backups must remain recoverable but live outside Codex's discoverable `skills/` directory. Otherwise an obsolete backup can be loaded as a duplicate Skill. The default location is `$CODEX_HOME/skill-backups/video-knowledge/<timestamp>/`.

## Verify

Doctor is the acceptance gate:

- `ready`: required checks pass with no warnings;
- `ready_with_warnings`: required checks pass; optional capability or storage warnings remain;
- `blocked`: a required check is missing; setup cannot be called complete.

Save a machine-readable final receipt after Verify. Repeated Verify runs must reuse an identical receipt when the accepted machine state has not changed. Temporary smoke inputs and outputs must be removed. A fluent success message cannot replace a Doctor result.

## Runtime entrypoint

Ordinary analysis must call `scripts/run_transcribe.py`, not choose a Python executable, construct `PYTHONPATH`, search for `model.bin`, or invoke the internal `transcribe.py` worker directly. The runner resolves the user config, prefers the managed venv, reuses the pinned configured model, supports one verified legacy layout, and returns a structured error for missing, broken, or ambiguous components.

Use `run_transcribe.py --probe --json` for read-only resolution. A successful Doctor result that relies on a standalone package directory is not by itself an invocation command; the runner owns the compatibility environment.

If Setup or Doctor fails, read [remediation-protocol.md](remediation-protocol.md). Codex may diagnose and perform bounded repairs; the installer itself must not silently improvise unverified fixes.
