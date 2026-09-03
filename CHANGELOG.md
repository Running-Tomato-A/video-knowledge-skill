# Changelog

This project follows Semantic Versioning for public preview releases. The technical Skill identifier remains `video-knowledge`; a future public brand or IP name may change the display layer without changing this identifier.

## 0.1.0-preview.4 — 2026-09-04

### Fixed

- Repository text files now keep LF line endings on every checkout so release-manifest hashes remain reproducible on Windows runners.
- GitHub Actions enables Python UTF-8 mode so setup-plan JSON can include non-ASCII paths and messages.

## 0.1.0-preview.3 — 2026-09-04

### Fixed

- GitHub Actions now resolves the available Python 3.12 toolchain on the current Windows runner instead of requesting an unavailable patch release.
- Release validation ignores Git metadata created by local repositories and GitHub Actions checkouts.

## 0.1.0-preview.2 — 2026-08-31

### Added

- Internal analysis brief: converts detailed but unstructured user doubts and desired directions into a primary mode, neutral hypotheses, bounded questions, evidence standard, scope boundaries, and a completion condition without requiring the user to rewrite a formal prompt.
- The evidence-rich report records the brief for later intent-versus-execution review.

### Verified

- Judge regression on a 12-minute sleep video combining measurable sleep phenomena, historical anecdotes, causal overreach, and metaphysical claims.
- Conclusion-changing video stance, N1 insight evidence, DMN transition evidence, adult sleep duration, polyphasic-sleep guidance, and quantum zero-point-field boundaries were independently spot-checked.

## 0.1.0-preview.1 — 2026-08-31

First local-install preview candidate.

### Added

- Absorb, Judge, and Apply analysis modes with evidence-linked Markdown output.
- Persistent transcript, cited frames, full evidence dossier, and grounded follow-up discussion.
- Conclusion-changing transcription corrections and source／stance attribution gate.
- Windows x64／Python 3.12 managed runtime, pinned Faster-Whisper Small model, FFmpeg checks, Doctor, and final Verify.
- One-confirmation complete installer with resumable stage receipts and non-discoverable Skill backups.
- Unified transcription runner for managed and verified legacy environments.
- Exact Windows wheel versions plus SHA-256 hash enforcement.
- Local release builder, license snapshot, OSV vulnerability snapshot, privacy boundary, and minimal CI contract.

### Fixed

- Skill backups now use microsecond-resolution UTC identifiers, preventing collisions during immediate rollback and restore sequences.

### Verified boundaries

- Windows x64 CPU `int8` clean installation and repeated reuse.
- Local video analysis without optional platform adapters.
- macOS and a real Windows machine missing FFmpeg remain unverified.
