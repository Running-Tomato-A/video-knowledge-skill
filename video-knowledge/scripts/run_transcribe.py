#!/usr/bin/env python3
"""Resolve the managed runtime and model, then run one local transcription."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from runtime_config import (  # noqa: E402
    default_config_path,
    find_workspace,
    resolve_runtime_paths,
)


def redact_sensitive_text(value: str) -> str:
    text = re.sub(
        r"(?i)\b(https?://)([^/\s:@]+):([^@\s/]+)@",
        r"\1***:***@",
        value,
    )
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", "Bearer ***", text)
    text = re.sub(
        r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|password|secret)"
        r"(\s*[:=]\s*)['\"]?([^\s,'\"]{8,})",
        r"\1\2***",
        text,
    )
    text = re.sub(
        r"\b(sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b",
        "***",
        text,
    )
    return text


class RunnerFailure(RuntimeError):
    def __init__(self, code: str, detail: str, suggestions: list[str] | None = None) -> None:
        super().__init__(detail)
        self.payload = {
            "status": "failed",
            "error_code": code,
            "detail": redact_sensitive_text(detail),
            "suggestions": suggestions or [],
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", help="Local video or audio file.")
    parser.add_argument("output_dir", nargs="?", help="Transcript output directory.")
    parser.add_argument("--probe", action="store_true", help="Resolve runtime without transcribing.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--workspace", help="Workspace root used for legacy discovery.")
    parser.add_argument("--config", help="Runtime config JSON.")
    parser.add_argument("--model", help="Exact model snapshot directory override.")
    parser.add_argument("--model-dir", help="Configured model root override.")
    parser.add_argument("--language", default=None)
    parser.add_argument("--prompt", default="")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def managed_python(data_root: Path) -> Path:
    if os.name == "nt":
        return data_root / "runtime" / "venv" / "Scripts" / "python.exe"
    return data_root / "runtime" / "venv" / "bin" / "python"


def import_probe(python: Path, environment: dict[str, str]) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            [str(python), "-c", "import faster_whisper; print('ok')"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    detail = completed.stderr.strip() or completed.stdout.strip()
    return completed.returncode == 0, detail


def resolve_python(workspace: Path, data_root: Path) -> dict[str, Any]:
    base_environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    venv_python = managed_python(data_root)
    if venv_python.is_file():
        ready, detail = import_probe(venv_python, base_environment)
        if ready:
            return {
                "python": venv_python,
                "source": "managed_venv",
                "environment": base_environment,
            }
        raise RunnerFailure(
            "managed_runtime_broken",
            f"Managed runtime exists but cannot import faster-whisper: {detail}",
            ["Rerun setup.py --apply --yes --stage runtime-dependencies."],
        )

    current_python = Path(sys.executable).resolve()
    ready, _ = import_probe(current_python, base_environment)
    if ready:
        return {
            "python": current_python,
            "source": "current_python",
            "environment": base_environment,
        }

    configured = os.environ.get("VIDEO_KNOWLEDGE_PYTHONPATH")
    standalone = (
        Path(configured).expanduser().resolve()
        if configured
        else (workspace / ".codex-tools" / "faster-whisper").resolve()
    )
    if standalone.is_dir():
        environment = dict(base_environment)
        previous = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            str(standalone) if not previous else str(standalone) + os.pathsep + previous
        )
        ready, detail = import_probe(current_python, environment)
        if ready:
            return {
                "python": current_python,
                "source": "legacy_pythonpath",
                "pythonpath": standalone,
                "environment": environment,
            }
        raise RunnerFailure(
            "legacy_runtime_broken",
            f"Legacy package directory exists but import failed: {detail}",
            ["Install the managed runtime stage instead of assembling PYTHONPATH manually."],
        )

    raise RunnerFailure(
        "transcription_runtime_missing",
        "No managed, current, or verified legacy Faster-Whisper runtime was found.",
        ["Run the read-only setup plan, confirm it, then install runtime-dependencies."],
    )


def model_revision() -> tuple[str, str]:
    manifest_path = Path(__file__).resolve().parent.parent / "references" / "model-manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))["default_model"]
    return payload["repo_id"], payload["revision"]


def resolve_model(model_root: Path, exact: str | None) -> dict[str, Any]:
    if exact:
        candidate = Path(exact).expanduser().resolve()
        if (candidate / "model.bin").is_file():
            return {"path": candidate, "source": "explicit"}
        raise RunnerFailure("model_invalid", f"model.bin not found below: {candidate}")

    repo_id, revision = model_revision()
    preferred = [
        model_root / "snapshot",
        model_root / f"models--{repo_id.replace('/', '--')}" / "snapshots" / revision,
    ]
    for candidate in preferred:
        if (candidate / "model.bin").is_file():
            return {"path": candidate.resolve(), "source": "configured_model_root"}

    discovered = sorted({path.parent.resolve() for path in model_root.rglob("model.bin")})
    if len(discovered) == 1:
        return {"path": discovered[0], "source": "single_discovered_snapshot"}
    if not discovered:
        raise RunnerFailure(
            "model_missing",
            f"No model.bin found below configured model root: {model_root}",
            ["Run setup.py --apply --yes --stage model."],
        )
    raise RunnerFailure(
        "model_ambiguous",
        "Multiple model snapshots were found; choose one with --model.",
        [str(path) for path in discovered],
    )


def resolve_runtime(args: argparse.Namespace) -> dict[str, Any]:
    workspace = find_workspace(args.workspace)
    config_path = Path(args.config).expanduser().resolve() if args.config else default_config_path()
    paths, resolved_config = resolve_runtime_paths(
        workspace,
        config_path=config_path,
        overrides={"model_dir": args.model_dir},
    )
    data_root = Path(paths["data_root"]["path"])
    model_root = Path(paths["model_dir"]["path"])
    runtime = resolve_python(workspace, data_root)
    model = resolve_model(model_root, args.model)
    return {
        "workspace": workspace,
        "config_path": resolved_config,
        "data_root": data_root,
        "model_root": model_root,
        "python": runtime,
        "model": model,
    }


def public_resolution(resolution: dict[str, Any]) -> dict[str, Any]:
    python = resolution["python"]
    return {
        "status": "ready",
        "config_path": str(resolution["config_path"]),
        "data_root": str(resolution["data_root"]),
        "python": str(python["python"]),
        "python_source": python["source"],
        "pythonpath": str(python.get("pythonpath")) if python.get("pythonpath") else None,
        "model": str(resolution["model"]["path"]),
        "model_source": resolution["model"]["source"],
    }


def main() -> int:
    args = parse_args()
    try:
        resolution = resolve_runtime(args)
        report = public_resolution(resolution)
        if args.probe:
            print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else report)
            return 0
        if not args.input or not args.output_dir:
            raise RunnerFailure(
                "input_required",
                "input and output_dir are required unless --probe is used.",
            )

        command = [
            str(resolution["python"]["python"]),
            str(Path(__file__).resolve().parent / "transcribe.py"),
            str(Path(args.input).expanduser().resolve()),
            str(resolution["model"]["path"]),
            str(Path(args.output_dir).expanduser().resolve()),
            "--device",
            args.device,
            "--compute-type",
            args.compute_type,
            "--beam-size",
            str(args.beam_size),
        ]
        if args.language:
            command.extend(["--language", args.language])
        if args.prompt:
            command.extend(["--prompt", args.prompt])
        if args.force:
            command.append("--force")

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            env=resolution["python"]["environment"],
        )
        if completed.returncode != 0:
            raise RunnerFailure(
                "transcription_failed",
                completed.stderr.strip() or completed.stdout.strip(),
                ["Run run_transcribe.py --probe --json and repair only the reported component."],
            )
        try:
            transcription = json.loads(completed.stdout)
        except json.JSONDecodeError:
            transcription = {"raw_output": completed.stdout.strip()}
        report.update({"status": "complete", "transcription": transcription})
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else completed.stdout.strip())
        return 0
    except (RunnerFailure, ValueError, OSError, json.JSONDecodeError) as exc:
        payload = exc.payload if isinstance(exc, RunnerFailure) else {
            "status": "failed",
            "error_code": "runtime_resolution_failed",
            "detail": str(exc),
            "suggestions": [],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else payload, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
