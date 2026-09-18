---
name: video-knowledge
description: Turn a user-selected video into evidence-linked Markdown for learning, evaluating claims, applying insights to a project, and grounded follow-up discussion. Use when a user shares a public video URL or local video and wants more than a generic summary. Do not use to auto-find viral videos, imitate copy, or promise why content will go viral.
---

# Video Knowledge

Transform one user-selected video into a durable, checkable knowledge asset. Preserve source evidence, expose uncertainty, and optimize the analysis for the user's intended result: absorb, judge, or apply.

## Route the request

Infer the primary mode from the user's natural language:

- **Absorb**: understand, structure, retain, or connect the video to a knowledge base.
- **Judge**: decide whether claims are true, credible, or worth adopting.
- **Apply**: use the video's ideas in a named project, decision, or next action.

If the result is already clear, proceed without asking the user to select a mode. If the user supplies only a link or says only “analyze this,” ask once:

> What should this analysis mainly help you do? A. Understand and absorb it; B. Judge whether it is credible or worth adopting; C. Apply it to a project. If C, you may also provide the project or relevant note.

When several goals appear, choose the user's final desired outcome as the primary mode. Treat other goals as necessary checks, not separate full reports. If an application depends on disputed claims, perform targeted judgment inside Apply mode.

When the user explains doubts, interests, or desired directions in natural but unstructured language, synthesize an internal analysis brief using [references/analysis-modes.md](references/analysis-modes.md). Do not ask the user to rewrite a formal prompt. If the brief faithfully preserves the request, state the understood purpose in one concise sentence and proceed without confirmation. Ask once only when a missing choice would materially change the mode, evidence burden, scope, or safety boundary.

## Process

1. Read [references/evidence-protocol.md](references/evidence-protocol.md) before acquiring or analyzing the source.
2. Locate and reuse existing local video, metadata, transcript, and frames before downloading or recomputing anything. Read [references/acquisition-contract.md](references/acquisition-contract.md), then prepare either a local file or public share text through `python scripts/process_source.py SOURCE --json`. For Douyin, the single entrypoint prefers its direct anonymous engine and uses the installed collector only as a traceable compatibility fallback; it then probes the verified media, transcribes it, and extracts sparse inspection frames. Do not ask the user to download the video or manually open the collector first.
3. Continue only after preprocessing returns `status: analysis_ready`. Verify the source identity and use its probe, transcript, and duration-adaptive inspection frames to assess audio/visual density and speaker structure. Treat these as orientation frames, not a fixed final quota. Decide whether visuals are negligible, supplementary, or essential; when visuals carry claims, interfaces, demonstrations, changing slides, or source evidence, use the retained media and `scripts/extract_frames.py` to add the specific frames the analysis needs. Choose processing effort internally; do not ask for confirmation merely because the video is long. `scripts/acquire.py` remains the acquisition-only diagnostic entrypoint.
4. Build the shared evidence layer: source, timestamped transcript, conclusion-changing corrections, cited frames, claims/arguments, information-type labels, and uncertainty log.
5. Read [references/analysis-modes.md](references/analysis-modes.md), record the internal analysis brief in the evidence-rich report, then produce only the selected mode's report.
6. Save a concise `analysis.md` and a separate evidence-rich `analysis-完整底稿.md`. Keep generated artifacts human-browsable and reusable.
7. When a concrete next step can materially advance the selected result, offer exactly one optional continuation matched to the mode. Omit it only when no useful continuation exists. The analysis is complete without the user's reply.

For long-running work, report meaningful stages such as acquisition, transcription, correction, verification, and document generation. Do not expose repetitive polling or internal tool noise.

## Runtime readiness

For installation or runtime reconfiguration, read [references/install-contract.md](references/install-contract.md), then run the read-only plan:

```text
python scripts/setup.py --plan
```

Do not infer installation authorization from planning. After the user approves the plan, ordinary installation uses one command: `python scripts/setup.py --apply --yes`. It runs six stages in order: `runtime-dependencies`, `model`, `ffmpeg`, `acquisition`, `skill`, and `verify`. `--stage` is only a developer or recovery override. The first five must return `complete_installation: false`; only Verify may return `true`, after all stage receipts, the installed Skill fingerprint, full Doctor, and a short local model inference pass. Treat `ready_with_warnings` as usable only when every warning is optional.

The acquisition stage creates a separate managed venv from the verified Windows x64 or macOS arm64 Python 3.12 lock, uses pip `--require-hashes`, and reuses a system Chrome／Edge／Chromium executable. It must not download Playwright's bundled browsers or merge acquisition packages into the transcription venv. Use `python scripts/run_acquire.py --probe --json` for a read-only acquisition readiness check.

Valid stages and downloads must be reused after interruption or on repeat installation. Store version backups outside the discoverable `skills/` directory so Codex cannot load an obsolete copy as a second Skill.

When Setup or Doctor returns a structured failure, read [references/remediation-protocol.md](references/remediation-protocol.md). Diagnose only the failed component, prefer official sources, keep repairs bounded, and obtain authorization for system-level changes.

macOS Apple Silicon with native Python 3.12 is a verified Apply target. On Darwin 25.6.0 arm64 with CPython 3.12.13, the complete six-stage installation, failure resume, full Doctor, second-run receipt reuse, pinned-model inference, Homebrew FFmpeg／FFprobe, anonymous Douyin acquisition, adaptive frames, transcription, and two-document analysis all passed. Intel macOS remains unsupported. Run the read-only preflight only when the target Mac lacks equivalent environment evidence or needs diagnosis:

```text
python scripts/macos_preflight.py --workspace /absolute/workspace
```

Do not treat a successful preflight or acquisition probe as installation authorization. Return the report for review before installing Homebrew, Rosetta, Python, FFmpeg, or transcription runtime packages. Do not ask a tester to repeat already valid evidence.

Run the read-only full Doctor after installation, on first use, after storage/model changes, or while troubleshooting:

```text
python scripts/doctor.py
```

For ordinary processing, reuse a recent successful full check and perform only a lightweight preflight for the capabilities needed by the current source. Use `python scripts/doctor.py --quick --json` when an explicit machine-readable preflight is useful. Doctor must not install dependencies, download models, create storage directories, move files, or delete data; setup and migration require separate user authorization.

Use the paths resolved by Doctor or the user runtime config. Do not assume models, downloads, or cache live inside the current workspace. Keep formal Markdown output in the current workspace unless the user config or request specifies another destination.

For ordinary transcription, use the single runtime entrypoint below instead of calling `transcribe.py` directly or assembling a Python executable, `PYTHONPATH`, and model snapshot path by hand:

```text
python scripts/run_transcribe.py INPUT OUTPUT_DIR --language zh --json
```

Use `python scripts/run_transcribe.py --probe --json` for a read-only resolution check. The runner must prefer the managed venv, reuse the configured pinned model, support a verified legacy layout, and fail structurally when the runtime or model is missing or ambiguous. `transcribe.py` is the internal worker, not the agent-facing entrypoint.

## Output contract

Use a user-provided destination when available. Otherwise create the sample under `video-knowledge/` in the current workspace.

```text
{author}-{short-title}/
├─ source.md
├─ transcript.md
├─ transcript.srt          # when available
├─ analysis.md             # about 3–5 minutes to read
├─ analysis-完整底稿.md
└─ frames/                 # only frames cited by the analysis
```

Use consistent metadata where known: `analysis_date`, `source_date`, `author`, `title`, `source_url`, `work_id`, `mode`, `status`, `one_line_conclusion`, and `tags`. Keep caches, temporary audio, and uncited frame dumps outside the formal deliverable.

## Follow-up conversation

After a video has been processed, support continued discussion without re-downloading, retranscribing, or regenerating the full report.

- In the same conversation, answer from the existing evidence and prior discussion.
- In a later conversation, locate the sample by work ID, source URL, author/title, or user-provided analysis directory. Read `analysis.md` first, then consult `analysis-完整底稿.md`, `transcript.md`/SRT, cited frames, or external sources only as needed.
- Allow clarification, challenge, comparison, knowledge connection, and open-ended discussion. Do not force every follow-up into a new full analysis mode.
- State whether an answer comes from the video, external evidence, or the analyst's own inference.
- If the user challenges the report, re-open the relevant timestamp or source and update the judgment when warranted.
- The “one optional continuation” rule limits the Skill's unsolicited closing suggestion, not the number of follow-up questions the user may ask.

## Boundaries

- Do not auto-discover or batch-analyze viral content.
- Do not imitate, rewrite, or launder another creator's content into the user's voice.
- Do not claim a single causal explanation for virality.
- Do not scan or rewrite an entire knowledge base unless the user explicitly expands scope.
- Do not turn a video's claims directly into a new skill or permanent user belief.
- Do not claim universal speaker diarization, perfect transcription, or fully automatic fact checking.
- Do not force a conclusion when evidence is absent. State what is unknown and what evidence would change the judgment.

The skill defines analysis decisions and evidence quality. Reuse the environment's existing video acquisition, transcription, frame extraction, browsing, and Markdown capabilities; do not install or rebuild them unless the user separately asks.
