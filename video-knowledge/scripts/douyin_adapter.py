#!/usr/bin/env python3
"""Minimal anonymous adapter for one user-selected public Douyin video."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

sys.dont_write_bytecode = True

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from runtime_config import load_config


DOUYIN_HOSTS = {"douyin.com", "www.douyin.com", "v.douyin.com"}
URL_PATTERN = re.compile(r"https?://[^\s<>\]\[\"']+", re.IGNORECASE)
WORK_ID_PATTERN = re.compile(r"(?:/video/|/note/|aweme_id=)(\d{12,24})")
MAX_FILE_BYTES = 1_500_000_000


class DouyinAdapterError(RuntimeError):
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


def inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def extract_source_url(value: str) -> str:
    for match in URL_PATTERN.finditer(value):
        candidate = match.group(0).rstrip(".,;:!?)，。；：！？）")
        host = (urlparse(candidate).hostname or "").lower()
        if host in DOUYIN_HOSTS or host.endswith(".douyin.com"):
            return candidate
    raise DouyinAdapterError(
        "douyin_url_missing",
        "The source text does not contain a supported public Douyin URL.",
    )


def work_id_from_url(value: str) -> str | None:
    match = WORK_ID_PATTERN.search(value)
    return match.group(1) if match else None


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def validate_existing_video(path: Path, *, download_root: Path) -> Path | None:
    resolved_root = download_root.expanduser().resolve()
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return None
    if not inside(resolved, resolved_root):
        return None
    if not resolved.is_file() or resolved.suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}:
        return None
    try:
        return resolved if resolved.stat().st_size > 0 else None
    except OSError:
        return None


def find_existing_video(download_root: Path, work_id: str) -> dict[str, Any] | None:
    root = download_root.expanduser().resolve()
    if not root.is_dir():
        return None
    for metadata_path in root.glob("*/source.json"):
        resolved_metadata = metadata_path.resolve()
        if not inside(resolved_metadata, root):
            continue
        metadata = load_json(resolved_metadata)
        if not metadata or str(metadata.get("work_id") or "") != work_id:
            continue
        if metadata.get("platform") not in {None, "douyin"} or metadata.get("kind") not in {None, "video"}:
            continue
        names = [metadata.get("filename"), "视频.mp4", "video.mp4"]
        candidates: list[Path] = []
        for name in names:
            if isinstance(name, str) and name.strip():
                candidates.append(resolved_metadata.parent / name)
        candidates.extend(
            path for path in resolved_metadata.parent.iterdir()
            if path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
        )
        seen: set[str] = set()
        for candidate in candidates:
            key = os.path.normcase(str(candidate))
            if key in seen:
                continue
            seen.add(key)
            video = validate_existing_video(candidate, download_root=root)
            if video is not None:
                return {
                    "platform": "douyin",
                    "source_url": str(metadata.get("source_url") or f"https://www.douyin.com/video/{work_id}"),
                    "work_id": work_id,
                    "title": metadata.get("title"),
                    "author": metadata.get("author"),
                    "media_path": str(video),
                    "metadata_path": str(resolved_metadata),
                    "existing": True,
                    "resolver": metadata.get("resolver"),
                }
    return None


def _configured_browser_path() -> str | None:
    try:
        config, _ = load_config()
    except ValueError as exc:
        raise DouyinAdapterError("runtime_config_invalid", str(exc)) from exc
    acquisition = config.get("acquisition") or {}
    if not isinstance(acquisition, dict):
        raise DouyinAdapterError("acquisition_config_invalid", "acquisition config must be an object.")
    douyin = acquisition.get("douyin") or {}
    if not isinstance(douyin, dict):
        raise DouyinAdapterError("acquisition_config_invalid", "acquisition.douyin must be an object.")
    value = douyin.get("browser_path")
    return str(value) if value else None


def browser_candidates() -> list[tuple[Path, str]]:
    candidates: list[tuple[Path, str]] = []
    configured = os.environ.get("VIDEO_KNOWLEDGE_BROWSER") or _configured_browser_path()
    if configured:
        candidates.append((Path(os.path.expandvars(configured)).expanduser(), "configured"))

    for name in ("chrome", "google-chrome", "msedge", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            candidates.append((Path(found), f"path:{name}"))

    if os.name == "nt":
        bases = {
            "program-files": os.environ.get("PROGRAMFILES"),
            "program-files-x86": os.environ.get("PROGRAMFILES(X86)"),
            "local-app-data": os.environ.get("LOCALAPPDATA"),
        }
        relatives = (
            Path("Google/Chrome/Application/chrome.exe"),
            Path("Microsoft/Edge/Application/msedge.exe"),
            Path("Chromium/Application/chrome.exe"),
        )
        for label, base in bases.items():
            if base:
                for relative in relatives:
                    candidates.append((Path(base) / relative, label))
    elif sys.platform == "darwin":
        candidates.extend(
            [
                (Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"), "macos-applications"),
                (Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"), "macos-applications"),
                (Path("/Applications/Chromium.app/Contents/MacOS/Chromium"), "macos-applications"),
            ]
        )

    unique: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for candidate, source in candidates:
        resolved = candidate.resolve()
        key = os.path.normcase(str(resolved))
        if key not in seen:
            seen.add(key)
            unique.append((resolved, source))
    return unique


def resolve_browser_executable(explicit: str | os.PathLike[str] | None = None) -> tuple[Path, str]:
    if explicit is not None:
        candidate = Path(explicit).expanduser().resolve()
        if candidate.is_file():
            return candidate, "argument"
        raise DouyinAdapterError("browser_missing", f"Configured browser does not exist: {candidate}")
    for candidate, source in browser_candidates():
        if candidate.is_file():
            return candidate, source
    raise DouyinAdapterError(
        "browser_missing",
        "No supported Chrome, Edge, or Chromium executable was found.",
        supported_fixes=[
            "Install a supported Chromium browser.",
            "Set VIDEO_KNOWLEDGE_BROWSER or acquisition.douyin.browser_path.",
        ],
    )


def safe_fragment(value: Any, fallback: str, limit: int) -> str:
    text = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip(" .")
    return (text or fallback)[:limit].rstrip(" .")


def created_date(timestamp: Any) -> str:
    try:
        return datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError, OverflowError):
        return datetime.now().strftime("%Y-%m-%d")


def folder_name(date_value: str, author: str, work_id: str, title: str) -> str:
    return f"{date_value}_{safe_fragment(author, '未知作者', 32)}_{work_id}_{safe_fragment(title, '未命名作品', 64)}"


def validate_public_media_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise DouyinAdapterError("media_url_invalid", "Resolver returned an invalid media URL.")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise DouyinAdapterError("media_url_unsafe", "Resolver returned a non-public media address.")
    return value


def _extract_first_url(value: Any) -> str | None:
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    if isinstance(value, list):
        for item in value:
            found = _extract_first_url(item)
            if found:
                return found
    if isinstance(value, dict):
        for key in ("urlList", "url_list", "url", "src"):
            found = _extract_first_url(value.get(key))
            if found:
                return found
    return None


def _all_urls(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in values:
        found = _extract_first_url(item)
        if found and found not in result:
            result.append(found)
    return result


def _best_live_url(video: Any) -> str | None:
    if not isinstance(video, dict):
        return None
    ranked: list[tuple[tuple[int, int, int], str]] = []
    rates = video.get("bitRate") or video.get("bit_rate") or []
    if isinstance(rates, list):
        for entry in rates:
            if not isinstance(entry, dict):
                continue
            url = _extract_first_url(entry.get("playAddr") or entry.get("play_addr"))
            if not url:
                continue
            ranked.append(
                (
                    (
                        min(int(entry.get("width") or 0), int(entry.get("height") or 0)),
                        int(entry.get("width") or 0) * int(entry.get("height") or 0),
                        int(entry.get("bitRate") or entry.get("bit_rate") or 0),
                    ),
                    url,
                )
            )
    if ranked:
        return max(ranked, key=lambda item: item[0])[1]
    for key in (
        "playAddrH264",
        "play_addr_h264",
        "playAddr265",
        "play_addr_265",
        "playAddr",
        "play_addr",
        "downloadAddr",
        "download_addr",
    ):
        url = _extract_first_url(video.get(key))
        if url:
            return url
    return None


def _walk_for_detail(value: Any, work_id: str) -> dict[str, Any] | None:
    if isinstance(value, dict):
        aweme = value.get("aweme")
        if isinstance(aweme, dict):
            detail = aweme.get("detail")
            if isinstance(detail, dict) and str(detail.get("awemeId")) == work_id:
                return detail
        detail = value.get("detail")
        if isinstance(detail, dict) and str(detail.get("awemeId")) == work_id:
            return detail
        for child in value.values():
            found = _walk_for_detail(child, work_id)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _walk_for_detail(child, work_id)
            if found:
                return found
    return None


def _detail_from_pace(entries: Any, work_id: str) -> dict[str, Any] | None:
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, list) or len(entry) < 2 or not isinstance(entry[1], str):
            continue
        payload = entry[1]
        if work_id not in payload:
            continue
        for line in payload.splitlines():
            if ":" not in line:
                continue
            try:
                parsed = json.loads(line.split(":", 1)[1])
            except (TypeError, ValueError):
                continue
            found = _walk_for_detail(parsed, work_id)
            if found:
                return found
    return None


def _gallery_from_detail(detail: dict[str, Any]) -> list[dict[str, Any]]:
    raw_images = detail.get("images") or []
    result: list[dict[str, Any]] = []
    if not isinstance(raw_images, list):
        return result
    for raw in raw_images:
        if not isinstance(raw, dict):
            continue
        urls = _all_urls(raw.get("urlList") or raw.get("url_list"))
        urls.sort(key=lambda url: (".jpeg" not in url.lower() and ".jpg" not in url.lower()))
        if urls:
            result.append(
                {
                    "urls": urls,
                    "width": int(raw.get("width") or 0),
                    "height": int(raw.get("height") or 0),
                    "live_url": _best_live_url(raw.get("video")),
                }
            )
    return result


def _captured_media_candidate(response: Any) -> tuple[str, dict[str, Any]] | None:
    try:
        content_type = response.headers.get("content-type", "").lower()
        url = response.url
        host = (urlparse(url).hostname or "").lower()
        if host.endswith(("douyinstatic.com", "byteimg.com", "bytedance.com")):
            return None
        resource_type = response.request.resource_type
        is_video = (
            content_type.startswith("video/")
            or "mime_type=video" in url
            or "/video/tos/" in url
            or "/tos-cn-ve-" in url
            or ".mp4" in url.lower()
        )
        is_audio = (
            content_type.startswith("audio/")
            or "mime_type=audio" in url
            or "media-audio" in url
            or "/audio/tos/" in url
            or "/tos-cn-a-" in url
        )
        is_media_request = resource_type == "media" or host.endswith(
            ("zjcdn.com", "douyinvod.com", "bytecdn.cn", "bytecdn.com")
        )
        if response.status not in {200, 206} or not (is_video or is_audio or is_media_request):
            return None
        content_range = response.headers.get("content-range", "")
        total_match = re.search(r"/(\d+)$", content_range)
        candidate = {
            "url": validate_public_media_url(url),
            "status": response.status,
            "content_type": content_type,
            "content_length": int(response.headers.get("content-length") or 0),
            "total_size": int(total_match.group(1)) if total_match else 0,
            "headers": response.request.all_headers(),
        }
        return ("audio" if is_audio else "video"), candidate
    except Exception:
        return None


def resolve_public_douyin(
    source_url: str,
    *,
    browser_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise DouyinAdapterError(
            "playwright_missing",
            "The direct Douyin adapter requires Playwright in its acquisition runtime.",
            supported_fixes=["Install the locked acquisition dependencies when they are available."],
        ) from exc

    executable_path, browser_source = resolve_browser_executable(browser_path)
    video_candidates: list[dict[str, Any]] = []
    audio_candidates: list[dict[str, Any]] = []

    try:
        with sync_playwright() as playwright:
            launch_args = [
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
                "--window-size=1365,768",
                "--no-first-run",
                "--no-default-browser-check",
                "--autoplay-policy=no-user-gesture-required",
            ]
            if os.name == "nt":
                launch_args.append("--window-position=-32000,-32000")
            browser = playwright.chromium.launch(
                executable_path=str(executable_path),
                headless=False,
                args=launch_args,
            )
            try:
                context = browser.new_context(
                    locale="zh-CN",
                    viewport={"width": 1365, "height": 768},
                    service_workers="block",
                )
                try:
                    context.add_init_script(
                        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                    )
                    page = context.new_page()

                    def remember_media(response: Any) -> None:
                        candidate = _captured_media_candidate(response)
                        if not candidate:
                            return
                        kind, value = candidate
                        (audio_candidates if kind == "audio" else video_candidates).append(value)

                    page.on("response", remember_media)
                    page.goto(source_url, wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_timeout(3_000)
                    canonical = page.evaluate(
                        "document.querySelector('link[rel=canonical]')?.href || location.href"
                    )
                    canonical = extract_source_url(str(canonical))
                    work_id = work_id_from_url(canonical) or work_id_from_url(page.url)
                    if not work_id:
                        raise DouyinAdapterError(
                            "douyin_work_id_missing",
                            "The anonymous browser opened the page but did not find a work ID.",
                        )

                    detail: dict[str, Any] | None = None
                    gallery: list[dict[str, Any]] = []
                    for _ in range(18):
                        detail = _detail_from_pace(page.evaluate("self.__pace_f || []"), work_id)
                        gallery = _gallery_from_detail(detail or {})
                        if gallery:
                            break
                        page.wait_for_timeout(1_000)

                    description = page.evaluate(
                        "document.querySelector('meta[name=description]')?.content || ''"
                    )
                    title = (detail or {}).get("desc") or description or page.title()
                    title = re.sub(r"\s+-\s+[^-]+于\d{8}发布在抖音.*$", "", str(title)).strip()
                    if title.endswith(" - 抖音"):
                        title = title[:-5].strip()
                    author = "未知作者"
                    detail_author = (detail or {}).get("authorInfo")
                    if isinstance(detail_author, dict) and detail_author.get("nickname"):
                        author = str(detail_author["nickname"]).strip()
                    published_match = re.search(r"于(\d{8})发布在抖音", str(description))
                    create_time = (detail or {}).get("createTime")
                    if not create_time and published_match:
                        create_time = int(datetime.strptime(published_match.group(1), "%Y%m%d").timestamp())
                    cookies = {item["name"]: item["value"] for item in context.cookies()}
                    common_headers = {
                        "Accept": "*/*",
                        "Referer": canonical,
                        "User-Agent": page.evaluate("navigator.userAgent"),
                    }

                    if gallery:
                        return {
                            "platform": "douyin",
                            "type": "image",
                            "work_id": work_id,
                            "source_url": canonical,
                            "title": title or f"抖音图集 {work_id}",
                            "author": author,
                            "create_time": create_time,
                            "resolver": "anonymous_chromium_page_data",
                            "browser_source": browser_source,
                        }
                    if "/note/" in page.url or "/slides/" in page.url:
                        raise DouyinAdapterError(
                            "douyin_gallery_incomplete",
                            "The page is a gallery, but its complete image list did not load.",
                        )

                    try:
                        page.wait_for_selector("video", state="attached", timeout=60_000)
                    except Exception:
                        pass
                    try:
                        page.locator("video").first.evaluate(
                            "video => { video.muted = true; return video.play().catch(() => null); }"
                        )
                    except Exception:
                        pass
                    page.wait_for_timeout(12_000)
                    if not video_candidates:
                        page.reload(wait_until="domcontentloaded", timeout=60_000)
                        page.wait_for_timeout(12_000)
                    if not video_candidates:
                        raise DouyinAdapterError(
                            "douyin_media_not_captured",
                            f"The work page opened, but no video media request was captured: {title or work_id}",
                        )

                    video_candidates.sort(
                        key=lambda item: (item["total_size"], item["status"] == 200, item["content_length"]),
                        reverse=True,
                    )
                    selected = video_candidates[0]
                    headers = {
                        key: value
                        for key, value in selected["headers"].items()
                        if key.lower() in {"accept", "accept-language", "referer", "user-agent"}
                    }
                    audio_data = None
                    if audio_candidates:
                        audio_candidates.sort(
                            key=lambda item: (item["total_size"], item["status"] == 200, item["content_length"]),
                            reverse=True,
                        )
                        selected_audio = audio_candidates[0]
                        audio_data = {
                            "url": selected_audio["url"],
                            "headers": {
                                key: value
                                for key, value in selected_audio["headers"].items()
                                if key.lower() in {"accept", "accept-language", "referer", "user-agent"}
                            },
                        }
                    return {
                        "platform": "douyin",
                        "type": "video",
                        "work_id": work_id,
                        "source_url": canonical,
                        "title": title or f"抖音作品 {work_id}",
                        "author": author,
                        "create_time": create_time,
                        "video_url": selected["url"],
                        "headers": headers or common_headers,
                        "cookies": cookies,
                        "audio": audio_data,
                        "resolver": "anonymous_chromium",
                        "browser_source": browser_source,
                    }
                finally:
                    context.close()
            finally:
                browser.close()
    except DouyinAdapterError:
        raise
    except Exception as exc:
        raise DouyinAdapterError(
            "douyin_browser_failed",
            f"Anonymous Douyin browser acquisition failed: {type(exc).__name__}: {exc}",
            supported_fixes=["Retry once, then use the installed collector compatibility bridge."],
        ) from exc


def resolve_executable(env_name: str, command: str) -> str:
    configured = os.environ.get(env_name)
    resolved = configured or shutil.which(command)
    if not resolved:
        raise DouyinAdapterError(
            f"{command}_missing",
            f"{command} is required by the direct Douyin adapter; set {env_name} or repair the runtime.",
        )
    return resolved


def file_has_audio(path: Path, *, ffprobe: str | None = None) -> bool:
    executable = ffprobe or resolve_executable("FFPROBE_PATH", "ffprobe")
    completed = subprocess.run(
        [
            executable,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return completed.returncode == 0 and bool(completed.stdout.strip())


def download_stream(
    url: str,
    destination: Path,
    *,
    headers: dict[str, Any] | None = None,
    cookies: dict[str, Any] | None = None,
) -> int:
    validate_public_media_url(url)
    allowed_headers = {"accept", "accept-language", "referer", "user-agent", "range"}
    request_headers = {
        str(key): str(value)
        for key, value in (headers or {}).items()
        if str(key).lower() in allowed_headers and value is not None
    }
    if cookies:
        request_headers["Cookie"] = "; ".join(
            f"{key}={value}" for key, value in cookies.items() if key and value is not None
        )
    request = Request(url, headers=request_headers)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    written = 0
    try:
        with urlopen(request, timeout=90) as response, destination.open("xb") as stream:
            validate_public_media_url(response.geturl())
            content_length = int(response.headers.get("Content-Length") or 0)
            if content_length > MAX_FILE_BYTES:
                raise DouyinAdapterError(
                    "media_too_large",
                    f"Media exceeds the {MAX_FILE_BYTES}-byte acquisition limit.",
                )
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_FILE_BYTES:
                    raise DouyinAdapterError(
                        "media_too_large",
                        f"Media exceeded the {MAX_FILE_BYTES}-byte acquisition limit while downloading.",
                    )
                stream.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if written <= 0:
        destination.unlink(missing_ok=True)
        raise DouyinAdapterError("media_download_empty", "The media download returned an empty file.")
    return written


def merge_audio_video(
    video_path: Path,
    audio_path: Path,
    destination: Path,
    *,
    ffmpeg: str | None = None,
) -> None:
    executable = ffmpeg or resolve_executable("FFMPEG_PATH", "ffmpeg")
    destination.unlink(missing_ok=True)
    completed = subprocess.run(
        [
            executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(destination),
        ],
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    if completed.returncode != 0 or not destination.is_file() or destination.stat().st_size <= 0:
        destination.unlink(missing_ok=True)
        raise DouyinAdapterError(
            "ffmpeg_merge_failed",
            (completed.stderr or "FFmpeg did not create the merged video.").strip()[-2000:],
        )


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def save_resolved_video(
    resolved: dict[str, Any],
    *,
    download_root: Path,
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
) -> dict[str, Any]:
    if resolved.get("type") != "video":
        raise DouyinAdapterError(
            "unsupported_media_kind",
            "Video Knowledge currently requires a video; the selected Douyin work is a gallery.",
            supported_fixes=["Keep the gallery for a future image-analysis adapter."],
        )
    work_id = safe_fragment(resolved.get("work_id"), "unknown", 24)
    if work_id == "unknown":
        raise DouyinAdapterError("douyin_work_id_missing", "Resolver did not return a Douyin work ID.")
    root = download_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    existing = find_existing_video(root, work_id)
    if existing:
        existing["acquisition_method"] = "anonymous-douyin-direct-existing"
        return existing

    author = safe_fragment(resolved.get("author"), "未知作者", 32)
    title = safe_fragment(resolved.get("title"), "未命名作品", 64)
    source_url = extract_source_url(str(resolved.get("source_url") or ""))
    created = created_date(resolved.get("create_time"))
    work_dir = (root / folder_name(created, author, work_id, title)).resolve()
    if not inside(work_dir, root):
        raise DouyinAdapterError("download_path_unsafe", "Resolved work directory escaped the download root.")
    work_dir.mkdir(parents=True, exist_ok=True)
    final_path = work_dir / "video.mp4"
    metadata_path = work_dir / "source.json"
    if final_path.exists():
        if file_has_audio(final_path, ffprobe=ffprobe):
            return {
                "platform": "douyin",
                "source_url": source_url,
                "work_id": work_id,
                "title": title,
                "author": author,
                "media_path": str(final_path),
                "metadata_path": str(metadata_path) if metadata_path.is_file() else None,
                "existing": True,
                "resolver": resolved.get("resolver"),
                "acquisition_method": "anonymous-douyin-direct-existing",
            }
        raise DouyinAdapterError(
            "existing_video_invalid",
            f"An existing target video has no readable audio stream: {final_path}",
        )

    video_url = validate_public_media_url(str(resolved.get("video_url") or ""))
    video_part = work_dir / ".video.part"
    audio_part = work_dir / ".audio.part"
    merged_part = work_dir / ".merged.part.mp4"
    try:
        download_stream(
            video_url,
            video_part,
            headers=resolved.get("headers") if isinstance(resolved.get("headers"), dict) else None,
            cookies=resolved.get("cookies") if isinstance(resolved.get("cookies"), dict) else None,
        )
        audio = resolved.get("audio")
        if isinstance(audio, dict) and audio.get("url"):
            download_stream(
                validate_public_media_url(str(audio["url"])),
                audio_part,
                headers=audio.get("headers") if isinstance(audio.get("headers"), dict) else None,
                cookies=resolved.get("cookies") if isinstance(resolved.get("cookies"), dict) else None,
            )
            merge_audio_video(video_part, audio_part, merged_part, ffmpeg=ffmpeg)
            if not file_has_audio(merged_part, ffprobe=ffprobe):
                raise DouyinAdapterError("merged_video_missing_audio", "Merged video has no readable audio stream.")
            merged_part.replace(final_path)
        else:
            if not file_has_audio(video_part, ffprobe=ffprobe):
                raise DouyinAdapterError(
                    "captured_video_missing_audio",
                    "Captured video has no audio and the resolver did not return a separate audio stream.",
                )
            video_part.replace(final_path)
    finally:
        video_part.unlink(missing_ok=True)
        audio_part.unlink(missing_ok=True)
        merged_part.unlink(missing_ok=True)

    metadata = {
        "platform": "douyin",
        "source_url": source_url,
        "author": author,
        "title": title,
        "work_id": work_id,
        "create_date": created,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "filename": final_path.name,
        "kind": "video",
        "summary": "视频",
        "resolver": resolved.get("resolver") or "anonymous_chromium",
        "browser_source": resolved.get("browser_source"),
    }
    atomic_write_json(metadata_path, metadata)
    return {
        "platform": "douyin",
        "source_url": source_url,
        "work_id": work_id,
        "title": title,
        "author": author,
        "media_path": str(final_path),
        "metadata_path": str(metadata_path),
        "existing": False,
        "resolver": metadata["resolver"],
        "acquisition_method": "anonymous-douyin-direct",
    }


def acquire_douyin(
    source: str,
    *,
    download_root: str | os.PathLike[str],
    browser_path: str | os.PathLike[str] | None = None,
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
) -> dict[str, Any]:
    source_url = extract_source_url(source)
    root = Path(download_root).expanduser().resolve()
    work_id = work_id_from_url(source_url)
    if work_id:
        existing = find_existing_video(root, work_id)
        if existing:
            existing["acquisition_method"] = "anonymous-douyin-direct-existing"
            return existing
    resolved = resolve_public_douyin(source_url, browser_path=browser_path)
    return save_resolved_video(
        resolved,
        download_root=root,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("--download-dir", required=True)
    parser.add_argument("--browser-path")
    parser.add_argument("--ffmpeg")
    parser.add_argument("--ffprobe")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = acquire_douyin(
            args.source,
            download_root=args.download_dir,
            browser_path=args.browser_path,
            ffmpeg=args.ffmpeg,
            ffprobe=args.ffprobe,
        )
    except (DouyinAdapterError, OSError, ValueError) as exc:
        if isinstance(exc, DouyinAdapterError):
            code = exc.code
            detail = exc.detail
            supported_fixes = exc.supported_fixes
        else:
            code = "douyin_adapter_failed"
            detail = str(exc)
            supported_fixes = []
        payload = {
            "schema_version": 1,
            "tool": "video-knowledge-douyin-adapter",
            "status": "failed",
            "error_code": code,
            "detail": detail,
            "supported_fixes": supported_fixes,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else detail, file=sys.stderr)
        return 1
    payload = {"schema_version": 1, "tool": "video-knowledge-douyin-adapter", "status": "ready", **result}
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else result["media_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
