#!/usr/bin/env python3
"""Fast, standard-library validation for a Video Knowledge release candidate."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

SEMVER = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
LOCK_LINE = re.compile(
    r"^[A-Za-z0-9_.-]+==[^\s]+ --hash=sha256:[0-9a-f]{64}$"
)
FORBIDDEN_EXTENSIONS = {
    ".pyc", ".pyo", ".exe", ".dll", ".bin", ".mp4", ".mov", ".mkv",
    ".mp3", ".wav", ".srt", ".db", ".sqlite", ".pem", ".key",
}
FORBIDDEN_PARTS = {"__pycache__", ".venv", "venv", "models", "downloads", "runtime"}
PERSONAL_PATTERNS = (
    "C:" + "\\Users\\",
    "D:" + "\\",
    "黑" + "鬼",
    "obsidian" + " codex",
    "xwechat" + "_files",
)
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~-]{12,}", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def files_below(root: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(root).parts
        ),
        key=lambda p: p.as_posix(),
    )


def tree_fingerprint(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path)
        for path in files_below(root)
        if path.name != "RELEASE-MANIFEST.json"
    }


def require_files(root: Path, errors: list[str]) -> None:
    required = [
        "README.md", "LICENSE", "PRIVACY.md", "THIRD_PARTY_NOTICES.md",
        "DEPENDENCY_LICENSES.md", "DEPENDENCY_VULNERABILITIES.md", "VERSION",
        "CHANGELOG.md", "UPGRADING.md", "video-knowledge/SKILL.md",
        "video-knowledge/VERSION", "video-knowledge/requirements-windows-py312.lock",
        "video-knowledge/scripts/setup.py", "video-knowledge/scripts/run_transcribe.py",
        "video-knowledge/scripts/macos_preflight.py",
    ]
    for relative in required:
        if not (root / relative).is_file():
            errors.append(f"required file missing: {relative}")


def validate_versions(root: Path, errors: list[str]) -> str:
    root_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    skill_version = (root / "video-knowledge" / "VERSION").read_text(encoding="utf-8").strip()
    if root_version != skill_version:
        errors.append(f"version mismatch: root={root_version}, skill={skill_version}")
    if not SEMVER.fullmatch(root_version):
        errors.append(f"invalid SemVer: {root_version!r}")
    return root_version


def validate_skill_frontmatter(root: Path, errors: list[str]) -> None:
    text = (root / "video-knowledge" / "SKILL.md").read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        errors.append("SKILL.md YAML frontmatter is missing")
        return
    parts = text.split("---", 2)
    frontmatter = parts[1] if len(parts) > 2 else ""
    if not re.search(r"(?m)^name:\s*video-knowledge\s*$", frontmatter):
        errors.append("SKILL.md name is missing or changed")
    match = re.search(r"(?m)^description:\s*(.+)$", frontmatter)
    if not match or len(match.group(1).strip()) < 40:
        errors.append("SKILL.md description is missing or too short")


def validate_lock(root: Path, errors: list[str]) -> int:
    path = root / "video-knowledge" / "requirements-windows-py312.lock"
    packages = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not LOCK_LINE.fullmatch(line):
            errors.append(f"unhashed or invalid lock entry: {line}")
            continue
        name = line.split("==", 1)[0].lower().replace("_", "-").replace(".", "-")
        packages.append(name)
    if len(packages) != 25:
        errors.append(f"expected 25 locked packages, found {len(packages)}")
    if len(packages) != len(set(packages)):
        errors.append("duplicate package names in lock")
    return len(packages)


def validate_files(root: Path, errors: list[str]) -> None:
    for path in files_below(root):
        relative = path.relative_to(root)
        if path.suffix.lower() in FORBIDDEN_EXTENSIONS:
            errors.append(f"forbidden artifact: {relative.as_posix()}")
        if any(part in FORBIDDEN_PARTS for part in relative.parts):
            errors.append(f"forbidden runtime directory: {relative.as_posix()}")
        if path.stat().st_size > 5 * 1024 * 1024:
            errors.append(f"unexpected file larger than 5 MiB: {relative.as_posix()}")
        if path.suffix == ".py":
            try:
                ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError) as exc:
                errors.append(f"Python syntax error in {relative.as_posix()}: {exc}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in PERSONAL_PATTERNS:
            if pattern in text:
                errors.append(f"personal path marker {pattern!r} in {relative.as_posix()}")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"secret-like value in {relative.as_posix()}")


def validate_markdown_links(root: Path, errors: list[str]) -> None:
    link_pattern = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
    for path in root.rglob("*.md"):
        for target in link_pattern.findall(path.read_text(encoding="utf-8")):
            if "://" in target or target.startswith("#"):
                continue
            local = path.parent / target.split("#", 1)[0]
            if not local.exists():
                errors.append(f"broken Markdown link: {path.relative_to(root)} -> {target}")


def validate_manifest(root: Path, version: str, errors: list[str]) -> None:
    path = root / "RELEASE-MANIFEST.json"
    if not path.is_file():
        errors.append("RELEASE-MANIFEST.json is missing")
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("release_version") != version:
        errors.append("release manifest version mismatch")
    listed = {}
    for item in payload.get("files", []):
        listed[item["path"]] = item
        candidate = root / item["path"]
        if not candidate.is_file():
            errors.append(f"manifest file missing: {item['path']}")
            continue
        if candidate.stat().st_size != item["bytes"] or sha256(candidate) != item["sha256"]:
            errors.append(f"manifest hash mismatch: {item['path']}")
    actual = tree_fingerprint(root)
    if set(listed) != set(actual):
        errors.append("manifest file set does not match candidate")


def run_setup_contract(root: Path, errors: list[str]) -> dict[str, Any]:
    setup = root / "video-knowledge" / "scripts" / "setup.py"
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    before = tree_fingerprint(root)
    plan = subprocess.run(
        [sys.executable, str(setup), "--plan", "--simulate-empty", "--json"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=environment,
    )
    try:
        plan_payload = json.loads(plan.stdout)
    except json.JSONDecodeError:
        plan_payload = {}
        errors.append(f"setup plan did not return JSON: {plan.stderr or plan.stdout}")
    if plan.returncode not in (0, 2):
        errors.append(f"setup plan exit code: {plan.returncode}")
    if plan_payload.get("status") != "confirmation_required" or not plan_payload.get("confirmation_required"):
        errors.append("blank setup plan did not require confirmation")
    if before != tree_fingerprint(root):
        errors.append("read-only setup plan changed the candidate tree")

    mac_plan = subprocess.run(
        [
            sys.executable,
            str(setup),
            "--plan",
            "--simulate-empty",
            "--simulate-platform",
            "Darwin",
            "--simulate-architecture",
            "arm64",
            "--simulate-python-version",
            "3.13.13",
            "--json",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=environment,
    )
    try:
        mac_payload = json.loads(mac_plan.stdout)
    except json.JSONDecodeError:
        mac_payload = {}
        errors.append(f"macOS setup plan did not return JSON: {mac_plan.stderr or mac_plan.stdout}")
    mac_codes = {item.get("code") for item in mac_payload.get("blockers", [])}
    if mac_plan.returncode != 2:
        errors.append(f"macOS setup plan exit code: {mac_plan.returncode}")
    if mac_payload.get("status") != "blocked" or mac_payload.get("confirmation_required"):
        errors.append("unverified macOS plan was not blocked")
    if {"platform_not_verified", "python_version_not_verified"} - mac_codes:
        errors.append("macOS plan did not report platform and Python blockers")

    windows_python_plan = subprocess.run(
        [
            sys.executable,
            str(setup),
            "--plan",
            "--simulate-empty",
            "--simulate-platform",
            "Windows",
            "--simulate-architecture",
            "AMD64",
            "--simulate-python-version",
            "3.13.1",
            "--json",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=environment,
    )
    try:
        windows_python_payload = json.loads(windows_python_plan.stdout)
    except json.JSONDecodeError:
        windows_python_payload = {}
        errors.append(
            "Windows Python-mismatch plan did not return JSON: "
            f"{windows_python_plan.stderr or windows_python_plan.stdout}"
        )
    windows_codes = {
        item.get("code") for item in windows_python_payload.get("blockers", [])
    }
    if windows_python_plan.returncode != 2:
        errors.append(f"Windows Python-mismatch plan exit code: {windows_python_plan.returncode}")
    if windows_python_payload.get("status") != "blocked":
        errors.append("Windows Python 3.13 plan was not blocked")
    if "python_version_not_verified" not in windows_codes:
        errors.append("Windows Python 3.13 plan did not report the version blocker")
    if "platform_not_verified" in windows_codes:
        errors.append("verified Windows x64 was incorrectly marked as an unsupported platform")
    if before != tree_fingerprint(root):
        errors.append("simulated platform plans changed the candidate tree")

    with tempfile.TemporaryDirectory(prefix="video-knowledge-ci-") as temporary:
        blocked_root = Path(temporary) / "unauthorized"
        denied = subprocess.run(
            [
                sys.executable, str(setup), "--apply", "--json",
                "--workspace", str(root),
                "--config", str(blocked_root / "config.json"),
                "--data-root", str(blocked_root / "data"),
                "--output-dir", str(blocked_root / "output"),
                "--skill-target", str(blocked_root / "skills" / "video-knowledge"),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env=environment,
        )
        try:
            denied_payload = json.loads(denied.stdout)
        except json.JSONDecodeError:
            denied_payload = {}
        if denied.returncode != 1 or denied_payload.get("error_code") != "authorization_required":
            errors.append("unauthorized Apply did not fail structurally")
        if blocked_root.exists():
            errors.append("unauthorized Apply created files")
    return {
        "plan_status": plan_payload.get("status"),
        "plan_estimate_mb": (plan_payload.get("estimate") or {}).get("new_disk_mb"),
    }


def main() -> int:
    args = parse_args()
    root = Path(args.root).expanduser().resolve()
    errors: list[str] = []
    require_files(root, errors)
    if errors:
        print(json.dumps({"status": "failed", "errors": errors}, indent=2))
        return 1
    version = validate_versions(root, errors)
    validate_skill_frontmatter(root, errors)
    package_count = validate_lock(root, errors)
    validate_files(root, errors)
    validate_markdown_links(root, errors)
    validate_manifest(root, version, errors)
    setup = run_setup_contract(root, errors)
    report = {
        "status": "complete" if not errors else "failed",
        "version": version,
        "files": len(files_below(root)),
        "locked_packages": package_count,
        **setup,
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
