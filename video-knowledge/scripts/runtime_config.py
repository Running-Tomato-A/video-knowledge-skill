"""Shared, standard-library-only runtime path configuration."""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any


ENV_PREFIX = "VIDEO_KNOWLEDGE_"
CONFIG_FILENAME = "config.json"


def default_config_path() -> Path:
    override = os.environ.get(f"{ENV_PREFIX}CONFIG")
    if override:
        return _expand_path(override, Path.cwd())
    return Path.home() / ".video-knowledge" / CONFIG_FILENAME


def fixed_drive_roots() -> list[Path]:
    if os.name != "nt":
        return [Path("/")]
    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
    except (AttributeError, OSError):
        return []
    roots: list[Path] = []
    for index, letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        if not bitmask & (1 << index):
            continue
        root = Path(f"{letter}:\\")
        if get_drive_type(str(root)) == 3:  # DRIVE_FIXED
            roots.append(root)
    return roots


def recommended_data_root() -> Path:
    if os.name == "nt":
        system_drive = os.environ.get("SystemDrive", "C:").rstrip("\\/").upper()
        candidates: list[tuple[int, Path]] = []
        for root in fixed_drive_roots():
            drive = str(root).rstrip("\\/").upper()
            if drive == system_drive:
                continue
            try:
                free = shutil.disk_usage(root).free
            except OSError:
                continue
            candidates.append((free, root))
        if candidates:
            _, best = max(candidates, key=lambda item: item[0])
            return best / "CodexData" / "video-knowledge"
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return local / "video-knowledge" / "data"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "video-knowledge"
    return Path.home() / ".local" / "share" / "video-knowledge"


def find_workspace(explicit: str | None = None) -> Path:
    if explicit:
        return _expand_path(explicit, Path.cwd())

    configured = os.environ.get(f"{ENV_PREFIX}WORKSPACE")
    if configured:
        return _expand_path(configured, Path.cwd())

    candidates: list[Path] = []
    for seed in (Path.cwd().resolve(), Path(__file__).resolve().parent):
        candidates.append(seed)
        candidates.extend(seed.parents)
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate))
        if key in seen:
            continue
        seen.add(key)
        if (candidate / ".codex-tools").is_dir() or (
            candidate / "tools" / "douyin-collector"
        ).is_dir():
            return candidate
    return Path.cwd().resolve()


def load_config(path: Path | None = None) -> tuple[dict[str, Any], Path]:
    config_path = (path or default_config_path()).expanduser().resolve()
    if not config_path.is_file():
        return {}, config_path
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid runtime config {config_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid runtime config {config_path}: root must be an object")
    schema_version = payload.get("schema_version", 1)
    if schema_version != 1:
        raise ValueError(f"Unsupported runtime config schema_version: {schema_version}")
    return payload, config_path


def _expand_path(value: str | os.PathLike[str], base: Path) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(str(value)))
    path = Path(expanded)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def resolve_runtime_paths(
    workspace: Path,
    *,
    config_path: Path | None = None,
    overrides: dict[str, str | None] | None = None,
) -> tuple[dict[str, dict[str, Any]], Path]:
    config, resolved_config = load_config(config_path)
    overrides = overrides or {}

    if overrides.get("data_root"):
        data_root = _expand_path(overrides["data_root"], workspace)
        data_source = "argument"
    elif os.environ.get(f"{ENV_PREFIX}DATA_ROOT"):
        data_root = _expand_path(os.environ[f"{ENV_PREFIX}DATA_ROOT"], workspace)
        data_source = f"environment:{ENV_PREFIX}DATA_ROOT"
    elif config.get("data_root"):
        data_root = _expand_path(config["data_root"], workspace)
        data_source = f"config:{resolved_config}"
    else:
        data_root = recommended_data_root().resolve()
        data_source = "recommended-default"

    defaults = {
        "model_dir": data_root / "models",
        "download_dir": data_root / "downloads",
        "cache_dir": data_root / "cache",
        "output_dir": workspace / "video-knowledge",
    }
    resolved: dict[str, dict[str, Any]] = {
        "data_root": {"path": data_root, "source": data_source}
    }
    for key, fallback in defaults.items():
        env_name = f"{ENV_PREFIX}{key.upper()}"
        if overrides.get(key):
            value = overrides[key]
            source = "argument"
        elif os.environ.get(env_name):
            value = os.environ[env_name]
            source = f"environment:{env_name}"
        elif config.get(key):
            value = config[key]
            source = f"config:{resolved_config}"
        else:
            value = fallback
            source = "derived-default"
        resolved[key] = {"path": _expand_path(value, workspace), "source": source}
    return resolved, resolved_config
