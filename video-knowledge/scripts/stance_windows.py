#!/usr/bin/env python3
"""Find transcript windows whose grammatical scope makes stance attribution risky."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


CUES = (
    (
        "zh_reported_condition",
        re.compile(r"(?:如果|假如|倘若).{0,48}(?:有人|别人|其他人|某人).{0,32}(?:告诉|说|认为|觉得|主张|要求|劝)"),
    ),
    (
        "zh_reported_speech",
        re.compile(r"(?:有人|别人|很多人|有些人|他们).{0,28}(?:说|认为|告诉|觉得|主张)"),
    ),
    (
        "zh_contrast_scope",
        re.compile(r"(?:不是.{0,48}而是|并不代表|不等于|你以为.{0,48}(?:其实|实际上)|虽然.{0,48}(?:但是|但|却))"),
    ),
    (
        "zh_rejection_response",
        re.compile(r"(?:别信|不要信|不能信|直接把.{0,12}拉黑|可以把.{0,12}拉黑|不赞同|我反对)"),
    ),
    (
        "en_reported_condition",
        re.compile(r"\bif\s+(?:someone|anyone|people)\b.{0,80}\b(?:says?|tells?|claims?|argues?)\b", re.I),
    ),
    (
        "en_reported_or_contrast",
        re.compile(r"\b(?:some people say|people claim|not .{0,60} but|you may think .{0,60} (?:but|however))\b", re.I),
    ),
)


def load_segments(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    segments = payload.get("segments") if isinstance(payload, dict) else None
    if not isinstance(segments, list):
        raise ValueError("Transcript JSON must contain a segments list.")
    cleaned: list[dict[str, Any]] = []
    for index, item in enumerate(segments):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        cleaned.append(
            {
                "index": index,
                "start": float(item.get("start") or 0.0),
                "end": float(item.get("end") or item.get("start") or 0.0),
                "text": text,
            }
        )
    return cleaned


def scan_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_candidates: list[dict[str, Any]] = []
    for index in range(len(segments)):
        lookahead = segments[index : min(len(segments), index + 6)]
        joined = " ".join(str(item["text"]) for item in lookahead)
        cue_ids = [cue_id for cue_id, pattern in CUES if pattern.search(joined)]
        if not cue_ids:
            continue
        start_index = max(0, index - 1)
        end_index = min(len(segments) - 1, index + 6)
        raw_candidates.append(
            {
                "start_index": start_index,
                "end_index": end_index,
                "cues": cue_ids,
            }
        )

    merged: list[dict[str, Any]] = []
    for item in raw_candidates:
        if merged and item["start_index"] <= merged[-1]["end_index"]:
            merged[-1]["end_index"] = max(merged[-1]["end_index"], item["end_index"])
            merged[-1]["cues"] = sorted(set(merged[-1]["cues"]) | set(item["cues"]))
        else:
            merged.append(dict(item))

    results: list[dict[str, Any]] = []
    for item in merged:
        window = segments[item["start_index"] : item["end_index"] + 1]
        results.append(
            {
                "start": window[0]["start"],
                "end": window[-1]["end"],
                "cues": item["cues"],
                "segments": window,
            }
        )
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript_json")
    parser.add_argument("--output", default=None)
    parser.add_argument("--json", action="store_true", help="Print JSON (default output format).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = Path(args.transcript_json).expanduser().resolve()
    segments = load_segments(source)
    payload = {
        "schema_version": 1,
        "tool": "video-knowledge-stance-windows",
        "source": str(source),
        "candidates": scan_segments(segments),
        "note": (
            "Candidates are scope-risk windows, not automatic stance judgments. "
            "Review only candidates that could materially change the requested result."
        ),
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
