#!/usr/bin/env python3
"""Download and verify the pinned Faster-Whisper model."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download and verify a pinned model.")
    parser.add_argument("--model-root", required=True, help="Hugging Face cache root.")
    parser.add_argument(
        "--manifest",
        default=str(Path(__file__).resolve().parent.parent / "references" / "model-manifest.json"),
        help="Model manifest JSON.",
    )
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("default_model"), dict):
        raise ValueError("Unsupported or invalid model manifest")
    return payload["default_model"]


def verify_snapshot(snapshot: Path, model: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for expected in model["files"]:
        path = snapshot / expected["name"]
        if not path.is_file():
            raise RuntimeError(f"Required model file is missing: {expected['name']}")
        actual_size = path.stat().st_size
        if actual_size != expected["bytes"]:
            raise RuntimeError(
                f"Size mismatch for {expected['name']}: {actual_size} != {expected['bytes']}"
            )
        actual_hash = sha256(path)
        if actual_hash != expected["sha256"].upper():
            raise RuntimeError(f"SHA-256 mismatch for {expected['name']}")
        results.append(
            {
                "name": expected["name"],
                "bytes": actual_size,
                "sha256": actual_hash,
            }
        )
    return results


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest).expanduser().resolve()
    model_root = Path(args.model_root).expanduser().resolve()
    if not manifest_path.is_file():
        print(f"Model manifest not found: {manifest_path}", file=sys.stderr)
        return 2
    model = load_manifest(manifest_path)

    snapshot_dir = model_root / "snapshot"
    os.environ.setdefault("HF_HOME", str(model_root / ".hf-home"))
    os.environ.setdefault("HF_HUB_CACHE", str(model_root / ".hf-home" / "hub"))
    os.environ.setdefault("HF_XET_CACHE", str(model_root / ".hf-home" / "xet"))

    from huggingface_hub import snapshot_download

    model_root.mkdir(parents=True, exist_ok=True)
    snapshot_path = Path(
        snapshot_download(
            repo_id=model["repo_id"],
            revision=model["revision"],
            local_dir=str(snapshot_dir),
            allow_patterns=[item["name"] for item in model["files"]],
            local_files_only=args.local_files_only,
        )
    ).resolve()
    verified = verify_snapshot(snapshot_path, model)
    report = {
        "status": "verified",
        "repo_id": model["repo_id"],
        "revision": model["revision"],
        "license": model["license"],
        "model_root": str(model_root),
        "snapshot_path": str(snapshot_path),
        "files": verified,
        "total_bytes": sum(item["bytes"] for item in verified),
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"Model verified: {model['repo_id']}@{model['revision']} "
            f"({report['total_bytes'] / 1024**2:.1f} MB)"
        )
        print(f"Snapshot: {snapshot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
