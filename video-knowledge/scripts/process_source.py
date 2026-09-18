#!/usr/bin/env python3
"""Acquire one video and prepare reusable evidence assets for Video Knowledge analysis."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Sequence

sys.dont_write_bytecode = True

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from acquire import AcquisitionError, acquire
from runtime_config import find_workspace, resolve_runtime_paths


class ProcessingError(RuntimeError):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        supported_fixes: list[str] | None = None,
        stage: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.payload = {
            "schema_version": 1,
            "tool": "video-knowledge-process-source",
            "status": "failed",
            "stage": stage,
            "error_code": code,
            "detail": detail,
            "supported_fixes": supported_fixes or [],
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Existing local video path or public share text／URL.")
    parser.add_argument("--output-dir", help="Evidence output directory for this source.")
    parser.add_argument("--workspace", help="Workspace root used for runtime/output discovery.")
    parser.add_argument("--language", default=None, help="Transcription language; omit for detection.")
    parser.add_argument("--prompt", default="", help="Optional transcription vocabulary prompt.")
    parser.add_argument(
        "--frame-count",
        type=int,
        default=None,
        help="Initial inspection frames (0-12); omit for duration-adaptive sampling.",
    )
    parser.add_argument("--force", action="store_true", help="Replace generated evidence files.")
    parser.add_argument(
        "--adapter",
        choices=("auto", "direct", "collector"),
        default=os.environ.get("VIDEO_KNOWLEDGE_ACQUISITION_ADAPTER", "auto"),
    )
    parser.add_argument("--download-dir", help="Direct-adapter download root override.")
    parser.add_argument("--browser-path", help="Chrome, Edge, or Chromium executable override.")
    parser.add_argument("--collector-url", default=os.environ.get("VIDEO_KNOWLEDGE_COLLECTOR_URL", "http://127.0.0.1:3210"))
    parser.add_argument("--collector-start-timeout", type=float, default=35.0)
    parser.add_argument("--collector-root")
    parser.add_argument("--collector-state-dir")
    parser.add_argument("--no-auto-start", action="store_true")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser.parse_args()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def source_metadata(acquisition: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    raw_path = acquisition.get("metadata_path")
    if isinstance(raw_path, str) and raw_path:
        loaded = load_json(Path(raw_path))
        if loaded:
            metadata.update(loaded)
    for key in ("platform", "source_url", "title", "author"):
        if acquisition.get(key) is not None:
            metadata[key] = acquisition[key]
    metadata.setdefault("platform", acquisition.get("platform"))
    metadata.setdefault("source_url", acquisition.get("source_url"))
    return metadata


def slug(value: str, *, fallback: str = "video") -> str:
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "-", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-")
    return (cleaned[:72].rstrip(" .-") or fallback)


def choose_output_dir(
    acquisition: dict[str, Any],
    metadata: dict[str, Any],
    *,
    explicit: str | None,
    workspace: Path,
) -> tuple[Path, Path]:
    try:
        runtime_paths, _ = resolve_runtime_paths(workspace)
    except ValueError as exc:
        raise ProcessingError("runtime_config_invalid", str(exc), stage="output") from exc
    cache_root = Path(runtime_paths["cache_dir"]["path"])
    if explicit:
        output = Path(explicit).expanduser().resolve()
    else:
        output_root = Path(runtime_paths["output_dir"]["path"])
        label_parts = [str(metadata.get("author") or ""), str(metadata.get("title") or "")]
        label = "-".join(part for part in label_parts if part).strip("-")
        if not label:
            label = Path(str(acquisition["media_path"])).stem
        output = output_root / f"{slug(label)}-{str(acquisition['sha256'])[:10].lower()}"
    inspection = cache_root / "source-processing" / str(acquisition["sha256"])[:16].lower()
    return output.resolve(), inspection.resolve()


def executable(env_name: str, command: str) -> str:
    resolved = os.environ.get(env_name) or shutil.which(command)
    if not resolved:
        raise ProcessingError(
            f"{command}_missing",
            f"{command} is not available; set {env_name} or repair the verified runtime.",
            stage="probe",
        )
    return resolved


def run_json_command(command: Sequence[str], *, stage: str) -> dict[str, Any]:
    completed = subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        check=False,
    )
    stream = completed.stdout if completed.returncode == 0 else completed.stderr or completed.stdout
    try:
        payload = json.loads(stream)
    except json.JSONDecodeError:
        payload = None
    if completed.returncode != 0:
        detail = ""
        if isinstance(payload, dict):
            detail = str(payload.get("detail") or payload.get("error_code") or "")
        if not detail:
            detail = stream.strip()[-3000:] or f"Command exited with code {completed.returncode}."
        raise ProcessingError(
            f"{stage}_failed",
            detail,
            stage=stage,
            supported_fixes=[f"Inspect the structured {stage} failure and repair only that component."],
        )
    if not isinstance(payload, dict):
        raise ProcessingError(
            f"{stage}_invalid_json",
            f"{stage} did not return a JSON object.",
            stage=stage,
        )
    return payload


def probe_media(media: Path) -> dict[str, Any]:
    ffprobe = executable("FFPROBE_PATH", "ffprobe")
    return run_json_command(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration,format_name,size:stream=index,codec_type,codec_name,width,height,sample_rate,channels",
            "-of",
            "json",
            str(media),
        ],
        stage="probe",
    )


def media_duration(probe: dict[str, Any]) -> float:
    try:
        duration = float((probe.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    if duration <= 0:
        raise ProcessingError(
            "media_duration_missing",
            "ffprobe did not return a positive media duration.",
            stage="probe",
        )
    return duration


def has_stream(probe: dict[str, Any], kind: str) -> bool:
    streams = probe.get("streams") or []
    return any(isinstance(item, dict) and item.get("codec_type") == kind for item in streams)


def transcript_is_reusable(output: Path, media: Path) -> bool:
    transcript_json = load_json(output / "transcript.json")
    if not transcript_json:
        return False
    try:
        recorded = Path(str(transcript_json.get("input") or "")).expanduser().resolve()
    except OSError:
        return False
    required = [output / "transcript.srt", output / "transcript.txt", output / "transcript.json"]
    return recorded == media.resolve() and all(path.is_file() and path.stat().st_size > 0 for path in required)


def transcribe_media(
    media: Path,
    output: Path,
    *,
    language: str | None,
    prompt: str,
    force: bool,
) -> tuple[str, dict[str, Any]]:
    if transcript_is_reusable(output, media) and not force:
        return "reused", load_json(output / "transcript.json") or {}
    command = [sys.executable, str(SCRIPTS_DIR / "run_transcribe.py"), str(media), str(output), "--json"]
    if language:
        command.extend(["--language", language])
    if prompt:
        command.extend(["--prompt", prompt])
    if force:
        command.append("--force")
    report = run_json_command(command, stage="transcription")
    return "created", report


def write_transcript_markdown(output: Path, *, force: bool = False) -> Path:
    destination = output / "transcript.md"
    if destination.is_file() and not force:
        return destination
    transcript = load_json(output / "transcript.json")
    if not transcript or not isinstance(transcript.get("segments"), list):
        raise ProcessingError(
            "transcript_assets_missing",
            "Transcription completed without a reusable transcript.json segment list.",
            stage="transcription",
        )
    lines = ["# Transcript", ""]
    for item in transcript["segments"]:
        if not isinstance(item, dict):
            continue
        start = float(item.get("start") or 0)
        minutes, seconds = divmod(start, 60)
        hours, minutes = divmod(int(minutes), 60)
        stamp = f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"
        lines.append(f"- [{stamp}] {str(item.get('text') or '').strip()}")
    atomic_write_text(destination, "\n".join(lines).rstrip() + "\n")
    return destination


def inspection_times(duration: float, count: int) -> list[float]:
    if count < 0 or count > 12:
        raise ProcessingError(
            "frame_count_invalid",
            "frame-count must be between 0 and 12.",
            stage="frames",
        )
    if count == 0:
        return []
    return [round(duration * index / (count + 1), 3) for index in range(1, count + 1)]


def adaptive_inspection_frame_count(duration: float, *, has_video_stream: bool) -> int:
    """Choose orientation frames by duration; analysis still selects final evidence frames."""
    if not has_video_stream:
        return 0
    if duration <= 180:
        return 3
    if duration <= 600:
        return 5
    if duration <= 1800:
        return 8
    if duration <= 3600:
        return 10
    return 12


def extract_inspection_frames(
    media: Path,
    probe: dict[str, Any],
    inspection_dir: Path,
    *,
    count: int,
    force: bool,
) -> tuple[str, dict[str, Any] | None]:
    times = inspection_times(media_duration(probe), count)
    if not times or not has_stream(probe, "video"):
        return "skipped", None
    frames_dir = inspection_dir / "frames"
    expected = [frames_dir / f"frame-{index:02d}-{timestamp:010.3f}s.jpg" for index, timestamp in enumerate(times, 1)]
    if not force and all(path.is_file() and path.stat().st_size > 0 for path in expected):
        return "reused", {
            "status": "complete",
            "video": str(media),
            "duration": media_duration(probe),
            "frames": [
                {"timestamp": timestamp, "file": str(path), "bytes": path.stat().st_size}
                for timestamp, path in zip(times, expected)
            ],
        }
    resume_partial = not force and any(path.exists() for path in expected)
    command = [
        sys.executable,
        str(SCRIPTS_DIR / "extract_frames.py"),
        str(media),
        str(frames_dir),
        "--times",
        *[f"{timestamp:.3f}" for timestamp in times],
    ]
    if force or resume_partial:
        command.append("--force")
    return "created", run_json_command(command, stage="frames")


def yaml_string(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def write_source_markdown(
    output: Path,
    acquisition: dict[str, Any],
    metadata: dict[str, Any],
    probe: dict[str, Any],
) -> Path:
    fields = {
        "analysis_date": date.today().isoformat(),
        "source_date": metadata.get("create_date"),
        "author": metadata.get("author"),
        "title": metadata.get("title") or Path(str(acquisition["media_path"])).stem,
        "source_url": metadata.get("source_url"),
        "work_id": metadata.get("work_id"),
        "platform": metadata.get("platform") or acquisition.get("platform"),
        "media_path": acquisition.get("media_path"),
        "media_sha256": acquisition.get("sha256"),
        "acquisition_method": acquisition.get("acquisition_method"),
    }
    frontmatter = ["---"]
    for key, value in fields.items():
        frontmatter.append(f"{key}: {yaml_string(value)}")
    frontmatter.extend(["---", "", "# Source", ""])
    frontmatter.append(f"- Duration: {media_duration(probe):.3f} seconds")
    frontmatter.append(f"- Bytes: {acquisition.get('bytes')}")
    frontmatter.append(f"- Reused saved copy: {str(bool(acquisition.get('existing'))).lower()}")
    destination = output / "source.md"
    atomic_write_text(destination, "\n".join(frontmatter) + "\n")
    return destination


def process_source(args: argparse.Namespace) -> dict[str, Any]:
    # Reject invalid work before acquisition can start a service or download media.
    if args.frame_count is not None:
        inspection_times(1.0, args.frame_count)
    workspace = find_workspace(args.workspace)
    try:
        acquisition = acquire(
            args.source,
            collector_url=args.collector_url,
            timeout=120.0,
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
        raise ProcessingError(
            exc.payload["error_code"],
            exc.payload["detail"],
            supported_fixes=exc.payload.get("supported_fixes") or [],
            stage="acquisition",
        ) from exc

    metadata = source_metadata(acquisition)
    output, inspection = choose_output_dir(
        acquisition,
        metadata,
        explicit=args.output_dir,
        workspace=workspace,
    )
    output.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output / "acquisition.json", acquisition)

    media = Path(str(acquisition["media_path"])).resolve()
    probe = probe_media(media)
    duration = media_duration(probe)
    video_present = has_stream(probe, "video")
    resolved_frame_count = (
        adaptive_inspection_frame_count(duration, has_video_stream=video_present)
        if args.frame_count is None
        else args.frame_count
    )
    atomic_write_json(output / "probe.json", probe)
    source_path = write_source_markdown(output, acquisition, metadata, probe)

    transcription_state, transcription = transcribe_media(
        media,
        output,
        language=args.language,
        prompt=args.prompt,
        force=args.force,
    )
    transcript_markdown = write_transcript_markdown(output, force=args.force)
    frame_state, frames = extract_inspection_frames(
        media,
        probe,
        inspection,
        count=resolved_frame_count,
        force=args.force,
    )
    result = {
        "schema_version": 1,
        "tool": "video-knowledge-process-source",
        "status": "analysis_ready",
        "source": args.source,
        "media_path": str(media),
        "output_dir": str(output),
        "inspection_dir": str(inspection),
        "acquisition": acquisition,
        "probe": {
            "duration": duration,
            "has_audio": has_stream(probe, "audio"),
            "has_video": video_present,
            "path": str(output / "probe.json"),
        },
        "transcription": {
            "state": transcription_state,
            "report": transcription,
            "markdown": str(transcript_markdown),
        },
        "frames": {
            "state": frame_state,
            "report": frames,
            "initial_policy": "duration_adaptive" if args.frame_count is None else "explicit",
            "initial_count": resolved_frame_count,
            "final_evidence_policy": (
                "Inspect visual importance, then extract additional targeted frames from the retained "
                "source when they materially support the analysis. Only cited frames are durable output."
            ),
        },
        "source_markdown": str(source_path),
        "next_stage": "Apply the selected Absorb／Judge／Apply evidence protocol and write analysis.md plus analysis-完整底稿.md.",
    }
    atomic_write_json(output / "processing.json", result)
    return result


def main() -> int:
    args = parse_args()
    try:
        result = process_source(args)
    except (ProcessingError, OSError, ValueError) as exc:
        payload = exc.payload if isinstance(exc, ProcessingError) else ProcessingError(
            "processing_failed", str(exc)
        ).payload
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else payload, file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result["output_dir"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
