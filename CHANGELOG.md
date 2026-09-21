# Changelog

This project follows Semantic Versioning for public preview releases. The technical Skill identifier remains `video-knowledge`; a future public brand or IP name may change the display layer without changing this identifier.

## 0.2.1 — 2026-09-21

### Added

- Runtime Skill provenance in formal analysis metadata, with fail-closed behavior when an explicitly requested version does not match the loaded Skill.
- Lightweight Chinese／English stance-risk window scanning based only on the Python standard library.
- Immutable proposition IDs, explicit owner／stance／modality records, and claim-matrix links back to the proposition ledger.

### Fixed

- Reported, rejected, hypothetical, or conditional propositions no longer become creator claims merely because their middle fragment appears in the transcript.
- Related but distinct propositions may not be merged only because they share a topic; rejecting an entry requirement remains separate from recommending a related practice.
- Suggestions, preferences, possibilities, and self-reported experience may not be upgraded to universal necessities, guarantees, or exclusion rules during summarization.
- Scope-sensitive burned captions require consecutive attribution／proposition／resolution frames when they materially affect the result.
- Final consistency review now checks proposition identity and modal strength in addition to owner and stance.
- Read-only Setup planning now compares the candidate and installed Skill fingerprints; a changed Skill is reported as an update instead of being silently reused merely because the target directory exists.

### Verified

- Three deterministic scanner tests cover a split Chinese reported condition, an ordinary unflagged claim, and an English reported condition.
- Three deterministic Skill-plan tests cover same-fingerprint reuse, changed-fingerprint update, and missing-Skill installation.
- A clean independent forward test produced 12 proposition-ledger entries, 9 claim-matrix rows, 15 cited frames with no missing or unreferenced formal frame, and consistent concise／evidence-rich conclusions.
- The known reported-speech regression was resolved without hard-coding its topic or expected answer.

## 0.2.1-preview.2 — 2026-09-21

### Fixed

- Proposition IDs now remain distinct across transcript, ledger, claim matrix, and reports; related claims may not be merged solely because they share a topic.
- Modal strength is preserved from source to conclusion: a preference, suggestion, or daily-practice recommendation cannot be upgraded to a universal necessity or entry requirement.
- Final consistency review now checks proposition identity and modality in addition to owner and stance, after a forward test correctly rejected an embedded claim but later reintroduced a stronger synthesized version.

## 0.2.1-preview.1 — 2026-09-21

### Added

- Runtime Skill provenance in the evidence-rich report; an explicitly requested version mismatch now stops before processing.
- Lightweight, standard-library stance-window scanning for reported speech, conditionals, contrast, and rejection cues in Chinese and English transcripts.
- A mandatory stance ledger and cross-document owner／stance consistency check for conclusion-changing propositions.

### Fixed

- Embedded propositions such as “If someone tells you P, reject them” may no longer be promoted into the creator's position without resolving the attribution cue and response window.
- Burned-caption claims that span multiple screen states now require consecutive attribution／proposition／resolution frames when they materially affect the result.

### Regression evidence

- The scanner flags the previously missed 02:19–02:25 reported-condition window while leaving an ordinary standalone product-matching claim unflagged.
- Three deterministic unit tests cover a split Chinese reported condition, an ordinary unflagged claim, and an English reported condition.

## 0.2.0 — 2026-09-18

### Added

- Direct anonymous acquisition for one user-selected public Douyin video.
- Managed acquisition runner, separate four-package SHA-256 lock, system-browser discovery, and six-stage Setup／Verify receipt chain.
- Single `process_source.py` entrypoint from share text or local video to verified media, probe, transcript, and inspection frames.
- Acquisition dependency license snapshot and privacy boundary.
- Duration-adaptive inspection frames with only cited evidence frames retained in formal output.
- Verified macOS Apple Silicon／Python 3.12 installation and runtime support alongside Windows x64／Python 3.12.

### Fixed

- Reprocessing preserves a human-curated `transcript.md` unless `--force` is explicit.
- Model Setup reuses a fully verified Hugging Face cache snapshot instead of duplicating 486 MB into a second layout.
- macOS Verify preserves managed-venv executable symlinks instead of resolving them to the base interpreter.
- Doctor no longer warns about `yt-dlp`, which is not an implemented 0.2.0 acquisition adapter.

### Verified

- Previously unseen Douyin short link saved through the independent acquisition venv, then transcribed, framed, and analyzed.
- Repeat processing reused media, transcript, and frames without changing curated Markdown files.
- macOS six-stage failure resume, full Doctor, inference smoke test, real-link analysis, and all-receipt second-run reuse.

## 0.1.0-preview.6 — 2026-09-04

### Fixed

- Setup Plan now blocks unverified platforms and Python versions instead of asking for confirmation that Apply cannot honor.
- Windows Plan and Apply now agree on the verified Python 3.12 requirement.
- Human and JSON plans expose structured platform blockers and safe next steps.

### Added

- Read-only Apple Silicon preflight for Python 3.12, Homebrew, FFmpeg／FFprobe, disk space, and privacy-safe platform evidence.
- Direct README links to the installation contract and remediation protocol.

## 0.1.0-preview.5 — 2026-09-04

### Changed

- README now records the project collaboration between Running-Tomato-A and OpenAI Codex.

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
