#!/usr/bin/env python3
"""Bounded lifecycle support for the local material-collector adapter."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

sys.dont_write_bytecode = True

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from runtime_config import default_config_path, find_workspace, load_config, resolve_runtime_paths


class CollectorLifecycleError(RuntimeError):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        supported_fixes: list[str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.supported_fixes = supported_fixes or []


def _health_url(collector_url: str) -> str:
    return f"{collector_url.rstrip('/')}/health"


def _require_local_url(collector_url: str) -> None:
    parsed = urlparse(collector_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise CollectorLifecycleError(
            "collector_autostart_requires_loopback",
            "Automatic collector startup is limited to an HTTP loopback address.",
            supported_fixes=[
                "Use http://127.0.0.1:<port>, or start and manage the remote adapter separately."
            ],
        )


def probe_health(collector_url: str, *, timeout: float = 1.0) -> dict[str, Any] | None:
    request = Request(_health_url(collector_url), headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
        decoded = json.loads(raw.decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(decoded, dict) or decoded.get("ok") is not True:
        return None
    download_dir = decoded.get("download_dir")
    if not isinstance(download_dir, str) or not download_dir.strip():
        return None
    return decoded


def _command_from_json(value: str, *, source: str) -> list[str]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise CollectorLifecycleError(
            "collector_command_invalid",
            f"Collector command from {source} is not valid JSON: {exc}",
        ) from exc
    if not isinstance(decoded, list) or not decoded or not all(
        isinstance(item, str) and item for item in decoded
    ):
        raise CollectorLifecycleError(
            "collector_command_invalid",
            f"Collector command from {source} must be a non-empty JSON array of strings.",
        )
    return decoded


def _configured_collector() -> tuple[dict[str, Any], Path]:
    try:
        config, config_path = load_config()
    except ValueError as exc:
        raise CollectorLifecycleError("runtime_config_invalid", str(exc)) from exc
    acquisition = config.get("acquisition") or {}
    if acquisition and not isinstance(acquisition, dict):
        raise CollectorLifecycleError(
            "collector_config_invalid",
            f"acquisition in {config_path} must be an object.",
        )
    collector = acquisition.get("collector") or {}
    if collector and not isinstance(collector, dict):
        raise CollectorLifecycleError(
            "collector_config_invalid",
            f"acquisition.collector in {config_path} must be an object.",
        )
    return collector, config_path


def resolve_collector_launch(
    *,
    collector_root: str | os.PathLike[str] | None = None,
    collector_command: Sequence[str] | None = None,
    workspace: Path | None = None,
) -> tuple[list[str], Path, str]:
    collector_config, config_path = _configured_collector()
    workspace = (workspace or find_workspace()).resolve()

    if collector_root is not None:
        root = Path(collector_root).expanduser().resolve()
        root_source = "argument"
    elif os.environ.get("VIDEO_KNOWLEDGE_COLLECTOR_ROOT"):
        root = Path(os.path.expandvars(os.environ["VIDEO_KNOWLEDGE_COLLECTOR_ROOT"]))
        root = root.expanduser().resolve()
        root_source = "environment:VIDEO_KNOWLEDGE_COLLECTOR_ROOT"
    elif collector_config.get("root"):
        root = Path(os.path.expandvars(str(collector_config["root"]))).expanduser().resolve()
        root_source = f"config:{config_path}"
    else:
        root = (workspace / "tools" / "douyin-collector").resolve()
        root_source = "workspace-discovery"

    if collector_command is not None:
        command = [str(item) for item in collector_command]
        command_source = "argument"
    elif os.environ.get("VIDEO_KNOWLEDGE_COLLECTOR_COMMAND"):
        command = _command_from_json(
            os.environ["VIDEO_KNOWLEDGE_COLLECTOR_COMMAND"],
            source="VIDEO_KNOWLEDGE_COLLECTOR_COMMAND",
        )
        command_source = "environment:VIDEO_KNOWLEDGE_COLLECTOR_COMMAND"
    elif collector_config.get("command") is not None:
        configured = collector_config["command"]
        if not isinstance(configured, list) or not configured or not all(
            isinstance(item, str) and item for item in configured
        ):
            raise CollectorLifecycleError(
                "collector_command_invalid",
                f"acquisition.collector.command in {config_path} must be a non-empty array of strings.",
            )
        command = [os.path.expandvars(item) for item in configured]
        command_source = f"config:{config_path}"
    else:
        app_path = root / "app.py"
        if os.name == "nt":
            python_path = root / ".venv" / "Scripts" / "python.exe"
        else:
            python_path = root / ".venv" / "bin" / "python"
        if not root.is_dir() or not app_path.is_file() or not python_path.is_file():
            raise CollectorLifecycleError(
                "collector_adapter_not_found",
                f"No startable material collector was found at {root}.",
                supported_fixes=[
                    "Install the acquisition adapter in tools/douyin-collector.",
                    "Set acquisition.collector.root/command in the Video Knowledge config.",
                    "Set VIDEO_KNOWLEDGE_COLLECTOR_ROOT or VIDEO_KNOWLEDGE_COLLECTOR_COMMAND.",
                ],
            )
        command = [str(python_path), str(app_path)]
        command_source = root_source

    if not command or not command[0].strip():
        raise CollectorLifecycleError("collector_command_invalid", "Collector command is empty.")
    return command, root, command_source


def default_state_dir(workspace: Path | None = None) -> Path:
    workspace = (workspace or find_workspace()).resolve()
    try:
        paths, _ = resolve_runtime_paths(workspace)
    except ValueError as exc:
        raise CollectorLifecycleError("runtime_config_invalid", str(exc)) from exc
    return Path(paths["cache_dir"]["path"]) / "collector-runtime"


def _tail(path: Path, limit: int = 2000) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    return raw[-limit:].decode("utf-8", errors="replace").strip()


@dataclass
class CollectorLease:
    collector_url: str
    state: str
    health: dict[str, Any]
    command_source: str | None = None
    process: subprocess.Popen[bytes] | None = field(default=None, repr=False)
    stdout_path: Path | None = field(default=None, repr=False)
    stderr_path: Path | None = field(default=None, repr=False)
    _stdout: Any = field(default=None, repr=False)
    _stderr: Any = field(default=None, repr=False)
    stopped: bool = False

    @property
    def started_by_request(self) -> bool:
        return self.process is not None

    def close(self, *, timeout: float = 8.0) -> dict[str, Any]:
        if self.process is None:
            return self.summary()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=timeout)
        self.stopped = True
        for stream in (self._stdout, self._stderr):
            if stream is not None:
                stream.close()
        self._stdout = None
        self._stderr = None
        return self.summary()

    def summary(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "started_by_request": self.started_by_request,
            "stopped_after_request": self.stopped,
            "pid": self.process.pid if self.process is not None else None,
            "collector_url": self.collector_url,
            "command_source": self.command_source,
        }

    def __enter__(self) -> "CollectorLease":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def ensure_collector(
    collector_url: str,
    *,
    start_timeout: float = 35.0,
    collector_root: str | os.PathLike[str] | None = None,
    collector_command: Sequence[str] | None = None,
    state_dir: str | os.PathLike[str] | None = None,
    workspace: Path | None = None,
) -> CollectorLease:
    health = probe_health(collector_url)
    if health is not None:
        return CollectorLease(collector_url=collector_url, state="reused", health=health)

    _require_local_url(collector_url)
    command, root, command_source = resolve_collector_launch(
        collector_root=collector_root,
        collector_command=collector_command,
        workspace=workspace,
    )
    if not root.is_dir():
        raise CollectorLifecycleError(
            "collector_working_directory_missing",
            f"Collector working directory does not exist: {root}",
        )

    runtime_dir = Path(state_dir).expanduser().resolve() if state_dir else default_state_dir(workspace)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = runtime_dir / "collector.stdout.log"
    stderr_path = runtime_dir / "collector.stderr.log"
    stdout = stdout_path.open("ab")
    stderr = stderr_path.open("ab")
    environment = os.environ.copy()
    environment.setdefault("PYTHONUTF8", "1")
    environment.setdefault("VIDEO_KNOWLEDGE_CONFIG", str(default_config_path()))
    creationflags = 0
    popen_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        popen_kwargs["start_new_session"] = True

    try:
        process = subprocess.Popen(
            command,
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
            **popen_kwargs,
        )
    except OSError as exc:
        stdout.close()
        stderr.close()
        raise CollectorLifecycleError(
            "collector_start_failed",
            f"Could not start the material collector: {exc}",
        ) from exc

    deadline = time.monotonic() + max(0.1, start_timeout)
    health = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        health = probe_health(collector_url)
        if health is not None:
            return CollectorLease(
                collector_url=collector_url,
                state="started",
                health=health,
                command_source=command_source,
                process=process,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                _stdout=stdout,
                _stderr=stderr,
            )
        time.sleep(0.2)

    timed_out = process.poll() is None
    if timed_out:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    stdout.close()
    stderr.close()
    log_tail = _tail(stderr_path) or _tail(stdout_path)
    detail = "Material collector did not become healthy before the startup deadline."
    if log_tail:
        detail += f" Log tail: {log_tail}"
    raise CollectorLifecycleError(
        "collector_start_timeout" if timed_out else "collector_exited_during_startup",
        detail,
        supported_fixes=[
            "Inspect the collector runtime log and repair only the reported missing dependency or port conflict."
        ],
    )
