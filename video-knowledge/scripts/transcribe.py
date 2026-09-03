#!/usr/bin/env python3
"""Transcribe one local media file into timestamped reusable assets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True


def srt_time(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe local video or audio.")
    parser.add_argument("input")
    parser.add_argument("model")
    parser.add_argument("output_dir")
    parser.add_argument("--language", default=None, help="Language code; omit for detection.")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = Path(args.input).expanduser().resolve()
    model_path = Path(args.model).expanduser().resolve()
    output = Path(args.output_dir).expanduser().resolve()
    if not source.is_file():
        print(f"Input file not found: {source}", file=sys.stderr)
        return 2
    if not model_path.is_dir():
        print(f"Model directory not found: {model_path}", file=sys.stderr)
        return 2

    expected = [output / "transcript.srt", output / "transcript.txt", output / "transcript.json"]
    existing = [path for path in expected if path.exists()]
    if existing and not args.force:
        print("Refusing to overwrite existing transcript outputs; use --force.", file=sys.stderr)
        return 2
    output.mkdir(parents=True, exist_ok=True)

    from faster_whisper import WhisperModel

    model = WhisperModel(
        str(model_path),
        device=args.device,
        compute_type=args.compute_type,
    )
    segments, info = model.transcribe(
        str(source),
        language=args.language,
        beam_size=args.beam_size,
        vad_filter=True,
        condition_on_previous_text=True,
        initial_prompt=args.prompt or None,
    )

    rows: list[dict[str, object]] = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            rows.append({"start": segment.start, "end": segment.end, "text": text})

    with expected[0].open("w", encoding="utf-8-sig") as stream:
        for index, row in enumerate(rows, 1):
            stream.write(
                f"{index}\n{srt_time(float(row['start']))} --> "
                f"{srt_time(float(row['end']))}\n{row['text']}\n\n"
            )

    with expected[1].open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(f"[{srt_time(float(row['start']))[:-4]}] {row['text']}\n")

    payload = {
        "input": str(source),
        "model": str(model_path),
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "device": args.device,
        "compute_type": args.compute_type,
        "segments": rows,
    }
    expected[2].write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "complete",
                "language": info.language,
                "duration": info.duration,
                "segments": len(rows),
                "output_dir": str(output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
