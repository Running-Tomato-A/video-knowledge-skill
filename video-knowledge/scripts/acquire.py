#!/usr/bin/env python3
"""Resolve a local video or material-collector share link to a verified media path."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

sys.dont_write_bytecode = True

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from collector_lifecycle import CollectorLifecycleError, ensure_collector
from douyin_adapter import (
    DouyinAdapterError,
    extract_source_url as extract_douyin_source_url,
    find_existing_video as find_existing_douyin_video,
    work_id_from_url as douyin_work_id_from_url,
)
from run_acquire import AcquisitionRunnerError, run_managed_acquisition
from runtime_config import find_workspace, resolve_runtime_paths

DEFAULT_COLLECTOR_URL = "http://127.0.0.1:3210"
SUPPORTED_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
URL_PATTERN = re.compile(r"https?://[^\s<>\]\[\"']+", re.IGNORECASE)


class AcquisitionError(RuntimeError):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        supported_fixes: list[str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.payload = {
            "schema_version": 1,
            "tool": "video-knowledge-acquire",
            "status": "failed",
            "error_code": code,
            "detail": detail,
            "supported_fixes": supported_fixes or [],
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Existing local video path or public share text／URL.")
    parser.add_argument(
        "--adapter",
        choices=("auto", "direct", "collector"),
        default=os.environ.get("VIDEO_KNOWLEDGE_ACQUISITION_ADAPTER", "auto"),
        help="Use the direct Douyin engine, the legacy collector bridge, or automatic routing.",
    )
    parser.add_argument("--download-dir", help="Direct-adapter download root override.")
    parser.add_argument("--browser-path", help="Chrome, Edge, or Chromium executable override.")
    parser.add_argument("--workspace", help="Workspace used for runtime path discovery.")
    parser.add_argument(
        "--collector-url",
        default=os.environ.get("VIDEO_KNOWLEDGE_COLLECTOR_URL", DEFAULT_COLLECTOR_URL),
        help="Material collector service root.",
    )
    parser.add_argument("--timeout", type=float, default=120.0, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--collector-start-timeout",
        type=float,
        default=35.0,
        help="Maximum seconds to wait for an automatically started collector.",
    )
    parser.add_argument(
        "--collector-root",
        help="Explicit installed collector directory; otherwise use config or workspace discovery.",
    )
    parser.add_argument(
        "--collector-state-dir",
        help="Collector startup log directory; defaults to the configured Video Knowledge cache.",
    )
    parser.add_argument(
        "--no-auto-start",
        action="store_true",
        help="Require the collector service to be running already.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def extract_url(value: str) -> str | None:
    match = URL_PATTERN.search(value)
    if not match:
        return None
    return match.group(0).rstrip(".,;:!?)，。；：！？）")


def platform_for_url(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower()
    if hostname == "douyin.com" or hostname.endswith(".douyin.com"):
        return "douyin"
    if hostname in {"xiaohongshu.com", "xhslink.cn", "xhslink.com"}:
        return "xiaohongshu"
    if hostname.endswith(".xiaohongshu.com"):
        return "xiaohongshu"
    raise AcquisitionError(
        "unsupported_url_host",
        f"No installed acquisition adapter supports host: {hostname or 'unknown'}.",
        supported_fixes=["Provide a supported public Douyin／Xiaohongshu link or a local video file."],
    )


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=body,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        try:
            response_body = exc.read().decode("utf-8", errors="replace")[-2000:]
        except OSError:
            response_body = ""
        raise AcquisitionError(
            "collector_http_error",
            f"Collector returned HTTP {exc.code}: {response_body or exc.reason}",
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise AcquisitionError(
            "collector_unavailable",
            f"Material collector is unavailable at {url}: {exc}",
            supported_fixes=[
                "Start the installed material collector, or install the packaged acquisition adapter when available."
            ],
        ) from exc
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcquisitionError("collector_invalid_json", "Collector did not return valid JSON.") from exc
    if not isinstance(decoded, dict):
        raise AcquisitionError("collector_invalid_response", "Collector JSON root must be an object.")
    return decoded


def validate_media(path: Path, *, root: Path | None) -> Path:
    resolved = path.expanduser().resolve()
    if root is not None and not inside(resolved, root.expanduser().resolve()):
        raise AcquisitionError(
            "collector_path_outside_download_root",
            "Collector returned a path outside its declared download directory.",
        )
    if not resolved.is_file():
        raise AcquisitionError("media_missing", f"Acquired media file does not exist: {resolved}")
    if resolved.suffix.lower() not in SUPPORTED_VIDEO_SUFFIXES:
        raise AcquisitionError(
            "unsupported_media_file",
            f"Acquired file is not a supported video: {resolved.name}",
        )
    size = resolved.stat().st_size
    if size <= 0:
        raise AcquisitionError("empty_media_file", f"Acquired media file is empty: {resolved}")
    return resolved


def local_result(path: Path) -> dict[str, Any]:
    media = validate_media(path, root=None)
    return {
        "schema_version": 1,
        "tool": "video-knowledge-acquire",
        "status": "ready",
        "input_kind": "local_file",
        "platform": "local",
        "source_url": None,
        "media_path": str(media),
        "metadata_path": None,
        "sha256": sha256(media),
        "bytes": media.stat().st_size,
        "existing": True,
        "acquisition_method": "local-file",
    }


def direct_douyin_result(
    source: str,
    *,
    download_dir: str | os.PathLike[str] | None = None,
    browser_path: str | os.PathLike[str] | None = None,
    workspace: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    resolved_workspace = find_workspace(str(workspace) if workspace is not None else None)
    try:
        runtime_paths, _ = resolve_runtime_paths(resolved_workspace)
    except ValueError as exc:
        raise AcquisitionError("runtime_config_invalid", str(exc)) from exc
    root = (
        Path(download_dir).expanduser().resolve()
        if download_dir is not None
        else Path(runtime_paths["download_dir"]["path"]).resolve()
    )
    try:
        source_url = extract_douyin_source_url(source)
        work_id = douyin_work_id_from_url(source_url)
        saved = find_existing_douyin_video(root, work_id) if work_id else None
        if saved is not None:
            saved["acquisition_method"] = "anonymous-douyin-direct-existing"
        else:
            saved = run_managed_acquisition(
                source,
                download_dir=root,
                browser_path=browser_path,
                workspace=str(resolved_workspace),
            )
    except (DouyinAdapterError, AcquisitionRunnerError) as exc:
        raise AcquisitionError(
            exc.code,
            exc.detail,
            supported_fixes=exc.supported_fixes,
        ) from exc
    raw_media = saved.get("media_path")
    if not isinstance(raw_media, str) or not raw_media:
        raise AcquisitionError("direct_adapter_missing_media_path", "Direct adapter returned no media path.")
    media = validate_media(Path(raw_media), root=root)
    metadata = saved.get("metadata_path")
    return {
        "schema_version": 1,
        "tool": "video-knowledge-acquire",
        "status": "ready",
        "input_kind": "public_url",
        "platform": "douyin",
        "source_url": saved.get("source_url") or extract_url(source),
        "media_path": str(media),
        "metadata_path": str(metadata) if metadata else None,
        "sha256": sha256(media),
        "bytes": media.stat().st_size,
        "existing": bool(saved.get("existing")),
        "acquisition_method": saved.get("acquisition_method") or "anonymous-douyin-direct",
        "title": saved.get("title"),
        "author": saved.get("author"),
        "work_id": saved.get("work_id"),
        "resolver": saved.get("resolver"),
    }


def collector_result(
    source: str,
    *,
    collector_url: str,
    timeout: float,
    auto_start: bool = True,
    collector_start_timeout: float = 35.0,
    collector_root: str | os.PathLike[str] | None = None,
    collector_command: list[str] | None = None,
    lifecycle_state_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    source_url = extract_url(source)
    if not source_url:
        raise AcquisitionError(
            "invalid_source",
            "Source is neither an existing local video nor text containing an HTTP(S) URL.",
        )
    expected_platform = platform_for_url(source_url)
    root_url = collector_url.rstrip("/")
    lease = None
    if auto_start:
        try:
            lease = ensure_collector(
                root_url,
                start_timeout=collector_start_timeout,
                collector_root=collector_root,
                collector_command=collector_command,
                state_dir=lifecycle_state_dir,
            )
        except CollectorLifecycleError as exc:
            raise AcquisitionError(
                exc.code,
                exc.detail,
                supported_fixes=exc.supported_fixes,
            ) from exc
    try:
        health = request_json(f"{root_url}/health", timeout=min(timeout, 10.0))
        raw_download_root = health.get("download_dir")
        if not isinstance(raw_download_root, str) or not raw_download_root.strip():
            raise AcquisitionError(
                "collector_missing_download_root",
                "Collector health response did not declare download_dir.",
            )
        download_root = Path(raw_download_root).expanduser().resolve()
        saved = request_json(
            f"{root_url}/api/save",
            method="POST",
            payload={"text": source},
            timeout=timeout,
        )
        if not saved.get("ok"):
            raise AcquisitionError("collector_save_failed", "Collector did not report a successful save.")
        actual_platform = str(saved.get("platform") or expected_platform)
        if actual_platform != expected_platform:
            raise AcquisitionError(
                "collector_platform_mismatch",
                f"Collector returned platform {actual_platform} for a {expected_platform} source.",
            )
        kind = str(saved.get("kind") or "")
        if kind != "video":
            raise AcquisitionError(
                "unsupported_media_kind",
                f"Video Knowledge transcription currently requires a video; collector returned {kind or 'unknown'}.",
                supported_fixes=["Keep the saved gallery for a future image-analysis adapter."],
            )
        raw_saved_to = saved.get("saved_to")
        if not isinstance(raw_saved_to, str) or not raw_saved_to.strip():
            raise AcquisitionError("collector_missing_media_path", "Collector response did not include saved_to.")
        media = validate_media(Path(raw_saved_to), root=download_root)
        metadata = media.parent / "source.json"
        result = {
            "schema_version": 1,
            "tool": "video-knowledge-acquire",
            "status": "ready",
            "input_kind": "public_url",
            "platform": actual_platform,
            "source_url": source_url,
            "media_path": str(media),
            "metadata_path": str(metadata) if metadata.is_file() else None,
            "sha256": sha256(media),
            "bytes": media.stat().st_size,
            "existing": bool(saved.get("existing")),
            "acquisition_method": "material-collector-http",
            "title": saved.get("title"),
            "author": saved.get("author"),
        }
    finally:
        lifecycle = lease.close() if lease is not None else None
    if lifecycle is not None:
        result["collector_lifecycle"] = lifecycle
    return result


def acquire(
    source: str,
    *,
    collector_url: str,
    timeout: float,
    auto_start: bool = True,
    collector_start_timeout: float = 35.0,
    collector_root: str | os.PathLike[str] | None = None,
    collector_command: list[str] | None = None,
    lifecycle_state_dir: str | os.PathLike[str] | None = None,
    adapter: str = "auto",
    download_dir: str | os.PathLike[str] | None = None,
    browser_path: str | os.PathLike[str] | None = None,
    workspace: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    candidate = Path(source).expanduser()
    if candidate.is_file():
        return local_result(candidate)
    source_url = extract_url(source)
    if not source_url:
        raise AcquisitionError(
            "invalid_source",
            "Source is neither an existing local video nor text containing an HTTP(S) URL.",
        )
    platform = platform_for_url(source_url)
    if adapter not in {"auto", "direct", "collector"}:
        raise AcquisitionError("acquisition_adapter_invalid", f"Unknown acquisition adapter: {adapter}")
    if adapter == "direct" and platform != "douyin":
        raise AcquisitionError(
            "direct_adapter_unsupported_platform",
            "The direct acquisition engine currently supports public Douyin videos only.",
        )

    direct_failure: AcquisitionError | None = None
    if platform == "douyin" and adapter in {"auto", "direct"}:
        try:
            return direct_douyin_result(
                source,
                download_dir=download_dir,
                browser_path=browser_path,
                workspace=workspace,
            )
        except AcquisitionError as exc:
            if adapter == "direct":
                raise
            direct_failure = exc

    try:
        result = collector_result(
            source,
            collector_url=collector_url,
            timeout=timeout,
            auto_start=auto_start,
            collector_start_timeout=collector_start_timeout,
            collector_root=collector_root,
            collector_command=collector_command,
            lifecycle_state_dir=lifecycle_state_dir,
        )
    except AcquisitionError as collector_failure:
        if direct_failure is None:
            raise
        raise AcquisitionError(
            "acquisition_adapters_failed",
            "Direct Douyin acquisition failed "
            f"({direct_failure.payload['error_code']}), then the collector bridge failed "
            f"({collector_failure.payload['error_code']}).",
            supported_fixes=list(
                dict.fromkeys(
                    (direct_failure.payload.get("supported_fixes") or [])
                    + (collector_failure.payload.get("supported_fixes") or [])
                )
            ),
        ) from collector_failure
    if direct_failure is not None:
        result["adapter_fallback"] = {
            "from": "direct-douyin",
            "error_code": direct_failure.payload["error_code"],
        }
    return result


def main() -> int:
    args = parse_args()
    try:
        result = acquire(
            args.source,
            collector_url=args.collector_url,
            timeout=args.timeout,
            auto_start=not args.no_auto_start,
            collector_start_timeout=args.collector_start_timeout,
            collector_root=args.collector_root,
            lifecycle_state_dir=args.collector_state_dir,
            adapter=args.adapter,
            download_dir=args.download_dir,
            browser_path=args.browser_path,
            workspace=args.workspace,
        )
    except AcquisitionError as exc:
        result = exc.payload
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Acquisition failed: {result['error_code']}", file=sys.stderr)
            print(result["detail"], file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["media_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
