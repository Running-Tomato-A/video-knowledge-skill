#!/usr/bin/env python3
"""Collect privacy-bounded macOS evidence without installing or downloading artifacts."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

PLAYWRIGHT_PACKAGES = {
    "playwright": "1.62.0",
    "greenlet": "3.5.4",
    "pyee": "13.0.1",
    "typing-extensions": "4.11.0",
}
MODEL_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
DEFAULT_DOUYIN_URL = "https://v.douyin.com/7BZ2hAr7ePc/"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".", help="Existing directory used only for disk checks.")
    parser.add_argument(
        "--douyin-url",
        default=DEFAULT_DOUYIN_URL,
        help="One user-selected public Douyin URL for a small read-only access probe.",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    return parser.parse_args()


def display_path(path: Path) -> str:
    resolved = path.expanduser().resolve()
    home = Path.home().resolve()
    try:
        relative = resolved.relative_to(home)
    except ValueError:
        return str(resolved)
    return "~/" + relative.as_posix() if relative.parts else "~"


def command_version(command: str, arguments: list[str]) -> dict[str, Any]:
    resolved = shutil.which(command)
    if not resolved:
        return {"command": command, "status": "missing", "path": None, "version": None}
    try:
        completed = subprocess.run(
            [resolved, *arguments],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        lines = (completed.stdout.strip() or completed.stderr.strip()).splitlines()
        return {
            "command": command,
            "status": "pass" if completed.returncode == 0 else "warning",
            "path": display_path(Path(resolved)),
            "version": lines[0] if lines else None,
            "exit_code": completed.returncode,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "command": command,
            "status": "warning",
            "path": display_path(Path(resolved)),
            "version": None,
            "detail": f"{type(exc).__name__}: {exc}",
        }


def python_details(command: str) -> dict[str, Any]:
    resolved = shutil.which(command)
    if not resolved:
        return {"command": command, "status": "missing"}
    code = (
        "import importlib.util,json,platform,sys;"
        "print(json.dumps({'version':platform.python_version(),'machine':platform.machine(),"
        "'implementation':platform.python_implementation(),'executable':sys.executable,"
        "'playwright_installed':importlib.util.find_spec('playwright') is not None}))"
    )
    try:
        completed = subprocess.run(
            [resolved, "-c", code], capture_output=True, text=True, timeout=15, check=False
        )
        payload = json.loads(completed.stdout) if completed.returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return {"command": command, "status": "warning", "detail": f"{type(exc).__name__}: {exc}"}
    payload.update(
        {
            "command": command,
            "status": "pass" if completed.returncode == 0 else "warning",
            "executable": display_path(Path(payload["executable"])) if payload.get("executable") else None,
        }
    )
    return payload


def browser_inventory() -> list[dict[str, Any]]:
    candidates = [
        ("Google Chrome", Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")),
        ("Microsoft Edge", Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")),
        ("Chromium", Path("/Applications/Chromium.app/Contents/MacOS/Chromium")),
    ]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name, path in candidates:
        key = str(path)
        seen.add(key)
        rows.append({"name": name, "status": "pass" if path.is_file() else "missing", "path": str(path)})
    for command in ("google-chrome", "microsoft-edge", "chromium", "chromium-browser"):
        found = shutil.which(command)
        if found and found not in seen:
            rows.append({"name": command, "status": "pass", "path": display_path(Path(found))})
            seen.add(found)
    return rows


def free_gb(path: Path) -> float | None:
    current = path.expanduser().resolve()
    while not current.exists() and current != current.parent:
        current = current.parent
    try:
        return round(shutil.disk_usage(current).free / (1024**3), 2)
    except OSError:
        return None


def small_get(
    url: str,
    *,
    timeout: float,
    accept: str = "application/json",
    range_request: bool = True,
) -> tuple[bytes, str, int]:
    headers = {
        "Accept": accept,
        "User-Agent": "video-knowledge-macos-preflight/2",
    }
    if range_request:
        headers["Range"] = "bytes=0-4095"
    request = urllib.request.Request(
        url,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(1024 * 1024), response.geturl(), int(response.status)


def endpoint_probe(label: str, url: str, *, timeout: float) -> dict[str, Any]:
    try:
        raw, final_url, status = small_get(url, timeout=timeout, accept="*/*")
        return {
            "label": label,
            "status": "pass" if 200 <= status < 400 else "warning",
            "http_status": status,
            "bytes_read": len(raw),
            "final_url": final_url,
        }
    except urllib.error.HTTPError as exc:
        return {
            "label": label,
            "status": "warning",
            "http_status": exc.code,
            "detail": str(exc.reason),
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"label": label, "status": "missing", "detail": f"{type(exc).__name__}: {exc}"}


def wheel_matches(filename: str, package: str, *, python_minor: int) -> bool:
    normalized = filename.lower().replace("-", "_")
    if package == "playwright":
        return normalized.endswith(("macosx_11_0_arm64.whl", "macosx_11_0_universal2.whl"))
    if package == "greenlet":
        return f"cp3{python_minor}" in normalized and normalized.endswith("macosx_11_0_universal2.whl")
    return normalized.endswith("py3_none_any.whl")


def wheel_availability(package: str, version: str, *, timeout: float) -> dict[str, Any]:
    url = f"https://pypi.org/pypi/{package}/{version}/json"
    try:
        raw, _, status = small_get(url, timeout=timeout, range_request=False)
        payload = json.loads(raw.decode("utf-8"))
        filenames = [item.get("filename", "") for item in payload.get("urls", [])]
        py312 = sorted(name for name in filenames if wheel_matches(name, package, python_minor=12))
        py313 = sorted(name for name in filenames if wheel_matches(name, package, python_minor=13))
        return {
            "package": package,
            "version": version,
            "status": "pass" if status == 200 and py312 else "missing",
            "python312_arm64_wheels": py312,
            "python313_arm64_wheels": py313,
        }
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "package": package,
            "version": version,
            "status": "unknown",
            "detail": f"{type(exc).__name__}: {exc}",
        }


def proxy_presence() -> dict[str, bool]:
    keys = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
    return {key.lower(): bool(os.environ.get(key) or os.environ.get(key.lower())) for key in keys}


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).expanduser().resolve()
    system = platform.system()
    architecture = platform.machine()
    apple_silicon = system == "Darwin" and architecture.lower() in ("arm64", "aarch64")
    commands = [
        command_version("python3.12", ["--version"]),
        command_version("python3", ["--version"]),
        command_version("conda", ["--version"]),
        command_version("brew", ["--version"]),
        command_version("ffmpeg", ["-version"]),
        command_version("ffprobe", ["-version"]),
        command_version("git", ["--version"]),
    ]
    by_name = {item["command"]: item for item in commands}
    pythons = [python_details("python3.12"), python_details("python3")]
    browsers = browser_inventory()
    wheels = [
        wheel_availability(package, version, timeout=args.timeout)
        for package, version in PLAYWRIGHT_PACKAGES.items()
    ]
    network = [
        endpoint_probe(
            "huggingface_model",
            "https://huggingface.co/Systran/faster-whisper-small/resolve/"
            f"{MODEL_REVISION}/config.json",
            timeout=args.timeout,
        ),
        endpoint_probe("douyin_public_link", args.douyin_url, timeout=args.timeout),
    ]
    blockers: list[dict[str, Any]] = []
    if not apple_silicon:
        blockers.append(
            {
                "code": "platform_not_targeted",
                "detail": f"This evidence pass targets macOS arm64; detected {system} {architecture}.",
            }
        )
    if by_name["python3.12"]["status"] == "missing":
        blockers.append({"code": "python312_missing", "detail": "No Python 3.12 interpreter was found on PATH."})
    if by_name["ffmpeg"]["status"] == "missing" or by_name["ffprobe"]["status"] == "missing":
        blockers.append({"code": "ffmpeg_missing", "detail": "FFmpeg and FFprobe are not available on PATH."})
    if not any(item["status"] == "pass" for item in browsers):
        blockers.append({"code": "browser_missing", "detail": "No supported system Chromium browser was found."})
    missing_wheels = [item["package"] for item in wheels if item["status"] != "pass"]
    if missing_wheels:
        blockers.append(
            {
                "code": "acquisition_wheel_evidence_missing",
                "detail": "Python 3.12 macOS arm64 wheel evidence is missing or unknown: "
                + ", ".join(missing_wheels),
            }
        )
    failed_endpoints = [item["label"] for item in network if item["status"] != "pass"]
    if failed_endpoints:
        blockers.append(
            {
                "code": "network_evidence_missing",
                "detail": "Read-only endpoint checks did not pass: " + ", ".join(failed_endpoints),
            }
        )

    report = {
        "schema_version": 2,
        "tool": "video-knowledge-macos-preflight",
        "read_only": True,
        "support_status": "evidence_collected" if apple_silicon else "blocked",
        "platform": {
            "system": system,
            "release": platform.release(),
            "machine": architecture,
            "python_running_probe": platform.python_version(),
        },
        "workspace": display_path(workspace),
        "workspace_free_gb": free_gb(workspace),
        "commands": commands,
        "python_details": pythons,
        "browsers": browsers,
        "acquisition_wheels": wheels,
        "network": network,
        "environment_presence": {
            "conda_active": bool(os.environ.get("CONDA_PREFIX")),
            "proxy_variables": proxy_presence(),
        },
        "blockers": blockers,
        "next_steps": [
            "Return this complete JSON report to the Video Knowledge maintainer.",
            "Do not run setup.py --apply on macOS yet.",
            "Do not install Homebrew, Rosetta, Python, FFmpeg, Playwright, or browsers during this evidence pass.",
            "After review, reuse the verified macOS arm64 acquisition lock and separately test the transcription runtime, FFmpeg, pinned model, and frame extraction before any supported Apply recipe.",
        ],
        "privacy": (
            "No serial number, hardware UUID, hostname, account token, proxy value, browser profile, "
            "cookie, model, or video is collected or downloaded."
        ),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if apple_silicon else 2


if __name__ == "__main__":
    raise SystemExit(main())
