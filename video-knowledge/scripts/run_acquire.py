#!/usr/bin/env python3
"""Run direct Douyin acquisition through the managed acquisition environment."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from douyin_adapter import DouyinAdapterError, resolve_browser_executable
from runtime_config import default_config_path, find_workspace, resolve_runtime_paths


class AcquisitionRunnerError(RuntimeError):
    def __init__(self, code: str, detail: str, *, supported_fixes: list[str] | None = None) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.supported_fixes = supported_fixes or []


def venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def resolve_acquisition_runtime(
    *, workspace: str | None = None, config: str | None = None
) -> dict[str, Any]:
    workspace_path = find_workspace(workspace)
    config_path = Path(config).expanduser().resolve() if config else default_config_path()
    try:
        paths, _ = resolve_runtime_paths(workspace_path, config_path=config_path)
    except ValueError as exc:
        raise AcquisitionRunnerError("runtime_config_invalid", str(exc)) from exc
    acquisition_root = Path(paths["data_root"]["path"]) / "acquisition"
    python = venv_python(acquisition_root / "venv")
    if not python.is_file():
        raise AcquisitionRunnerError(
            "acquisition_runtime_missing",
            f"Managed acquisition Python does not exist: {python}",
            supported_fixes=["Run the verified acquisition Setup stage after reviewing its plan."],
        )
    completed = subprocess.run(
        [str(python), "-c", "import playwright; print('ready')"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise AcquisitionRunnerError(
            "acquisition_runtime_broken",
            (completed.stderr or completed.stdout or "Playwright import failed.").strip()[-2000:],
            supported_fixes=["Rerun the acquisition Setup stage to verify the locked packages."],
        )
    try:
        browser, browser_source = resolve_browser_executable()
    except DouyinAdapterError as exc:
        raise AcquisitionRunnerError(exc.code, exc.detail, supported_fixes=exc.supported_fixes) from exc
    return {
        "workspace": workspace_path,
        "config_path": config_path,
        "download_dir": Path(paths["download_dir"]["path"]),
        "acquisition_root": acquisition_root,
        "python": python,
        "browser": browser,
        "browser_source": browser_source,
    }


def run_managed_acquisition(
    source: str,
    *,
    download_dir: str | os.PathLike[str] | None = None,
    browser_path: str | os.PathLike[str] | None = None,
    workspace: str | None = None,
    config: str | None = None,
) -> dict[str, Any]:
    runtime = resolve_acquisition_runtime(workspace=workspace, config=config)
    destination = Path(download_dir).expanduser().resolve() if download_dir else runtime["download_dir"]
    browser = Path(browser_path).expanduser().resolve() if browser_path else runtime["browser"]
    command = [
        str(runtime["python"]),
        str(SCRIPTS_DIR / "douyin_adapter.py"),
        source,
        "--download-dir",
        str(destination),
        "--browser-path",
        str(browser),
        "--json",
    ]
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["VIDEO_KNOWLEDGE_CONFIG"] = str(runtime["config_path"])
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    stream = completed.stdout if completed.returncode == 0 else completed.stderr or completed.stdout
    try:
        payload = json.loads(stream)
    except json.JSONDecodeError as exc:
        raise AcquisitionRunnerError(
            "acquisition_runtime_invalid_json",
            stream.strip()[-2000:] or "Managed acquisition returned no JSON.",
        ) from exc
    if completed.returncode != 0 or payload.get("status") != "ready":
        raise AcquisitionRunnerError(
            str(payload.get("error_code") or "managed_acquisition_failed"),
            str(payload.get("detail") or "Managed acquisition failed."),
            supported_fixes=payload.get("supported_fixes") or [],
        )
    payload["acquisition_runtime"] = {
        "python": str(runtime["python"]),
        "browser": str(browser),
        "browser_source": runtime["browser_source"],
    }
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--download-dir")
    parser.add_argument("--browser-path")
    parser.add_argument("--workspace")
    parser.add_argument("--config")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        runtime = resolve_acquisition_runtime(workspace=args.workspace, config=args.config)
        if args.probe:
            result = {
                "schema_version": 1,
                "tool": "video-knowledge-run-acquire",
                "status": "ready",
                "python": str(runtime["python"]),
                "browser": str(runtime["browser"]),
                "browser_source": runtime["browser_source"],
                "download_dir": str(runtime["download_dir"]),
            }
        else:
            if not args.source:
                raise AcquisitionRunnerError("source_required", "source is required unless --probe is used.")
            result = run_managed_acquisition(
                args.source,
                download_dir=args.download_dir,
                browser_path=args.browser_path,
                workspace=args.workspace,
                config=args.config,
            )
    except (AcquisitionRunnerError, OSError, ValueError) as exc:
        if isinstance(exc, AcquisitionRunnerError):
            code, detail, fixes = exc.code, exc.detail, exc.supported_fixes
        else:
            code, detail, fixes = "acquisition_runner_failed", str(exc), []
        result = {"status": "failed", "error_code": code, "detail": detail, "supported_fixes": fixes}
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else detail, file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
