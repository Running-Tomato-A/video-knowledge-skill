#!/usr/bin/env python3
"""Probe one local video and extract explicitly requested evidence frames."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def parse_timestamp(value: str) -> float:
    if ":" not in value:
        seconds = float(value)
    else:
        parts = value.split(":")
        if len(parts) > 3:
            raise ValueError(f"Invalid timestamp: {value}")
        numbers = [float(part) for part in parts]
        seconds = 0.0
        for number in numbers:
            seconds = seconds * 60 + number
    if seconds < 0:
        raise ValueError("Timestamp cannot be negative")
    return seconds


def executable(env_name: str, command: str) -> str:
    configured = os.environ.get(env_name)
    resolved = configured or shutil.which(command)
    if not resolved:
        raise RuntimeError(f"{command} not found; set {env_name} or add it to PATH")
    return resolved


def probe(video: Path, ffprobe: str) -> dict[str, object]:
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=index,codec_type,codec_name,width,height",
            "-of",
            "json",
            str(video),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "ffprobe failed")
    return json.loads(completed.stdout)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract selected video frames.")
    parser.add_argument("video")
    parser.add_argument("output_dir")
    parser.add_argument("--times", nargs="+", required=True, help="Seconds or HH:MM:SS.mmm")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    video = Path(args.video).expanduser().resolve()
    output = Path(args.output_dir).expanduser().resolve()
    if not video.is_file():
        print(f"Video not found: {video}", file=sys.stderr)
        return 2
    try:
        times = [parse_timestamp(value) for value in args.times]
        ffmpeg = executable("FFMPEG_PATH", "ffmpeg")
        ffprobe = executable("FFPROBE_PATH", "ffprobe")
        media = probe(video, ffprobe)
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    duration = float(media.get("format", {}).get("duration", 0.0))
    if duration <= 0:
        print("Video duration could not be determined.", file=sys.stderr)
        return 2
    for timestamp in times:
        if timestamp >= duration:
            print(f"Timestamp {timestamp:.3f}s is outside duration {duration:.3f}s.", file=sys.stderr)
            return 2

    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for index, timestamp in enumerate(times, 1):
        destination = output / f"frame-{index:02d}-{timestamp:010.3f}s.jpg"
        if destination.exists() and not args.force:
            print(f"Refusing to overwrite frame; use --force: {destination}", file=sys.stderr)
            return 2
        completed = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y" if args.force else "-n",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(destination),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if completed.returncode != 0 or not destination.is_file():
            print(completed.stderr.strip() or "ffmpeg frame extraction failed", file=sys.stderr)
            return 1
        rows.append(
            {
                "timestamp": timestamp,
                "file": str(destination),
                "bytes": destination.stat().st_size,
            }
        )

    report = {
        "status": "complete",
        "video": str(video),
        "duration": duration,
        "streams": media.get("streams", []),
        "frames": rows,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
