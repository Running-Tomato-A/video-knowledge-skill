# Acquisition Contract

Read this reference when the user provides a local media path, a public share URL, or share text that must be saved before analysis.

## Promise

The acquisition layer turns one user-selected source into one verified local media path. Analysis begins only after this boundary succeeds.

Supported input kinds:

- an existing local video file;
- one public Douyin video through the direct anonymous adapter;
- public Douyin or Xiaohongshu share text handled by the installed collector compatibility bridge;
- future public-video adapters that implement the same result schema.

Acquisition does not search for content, bypass access controls, use private-account cookies by default, download paid or private media, or imply that every platform URL is supported.

## Result schema

A successful adapter returns JSON with:

- `status: ready`;
- `input_kind`: `local_file` or `public_url`;
- `platform`;
- `source_url` when applicable;
- `media_path`: the verified local video file;
- `metadata_path` when a sidecar exists;
- `sha256` and `bytes`;
- `existing`: whether a previous saved copy was reused;
- `acquisition_method`.

For Douyin, `--adapter auto` first uses the direct engine in `scripts/douyin_adapter.py`. A direct work URL is looked up by work ID before Playwright is invoked. Otherwise `scripts/run_acquire.py` resolves the separate managed acquisition venv and a system Chrome／Edge／Chromium executable, then opens exactly one public work in an isolated anonymous context, captures its public media requests, saves a verified video, and closes the context. It never loads the user's normal browser profile or persistent cookies.

The legacy compatibility bridge calls the existing local material collector at `http://127.0.0.1:3210`. It first reuses a healthy service. Otherwise it starts an installed adapter from explicit configuration or the current workspace, waits for bounded health readiness, performs the save, and stops only the process started for that request. It never stops a collector that was already running. Automatic routing records a direct-engine failure when it falls back to this bridge.

Adapter discovery order for automatic startup:

1. an explicit command supplied by the caller;
2. `VIDEO_KNOWLEDGE_COLLECTOR_COMMAND` as a JSON string array;
3. `acquisition.collector.command` in `~/.video-knowledge/config.json`;
4. an explicit/environment/configured collector root;
5. `tools/douyin-collector` under the detected workspace.

The configured compatibility root must contain `app.py` and its own `.venv` Python. Automatic startup is limited to loopback HTTP addresses. Startup logs go to the configured Video Knowledge cache unless a test or caller supplies a separate state directory.

## Trust boundary

Treat an adapter response as untrusted until all checks pass:

1. Every returned local path resolves inside the declared download root.
2. The result is a regular, non-empty supported video file.
3. The path is hashed before downstream processing.
4. Direct media URLs must be HTTP(S), reject non-public literal IP addresses, and stay below the bounded size limit.
5. A newly saved video must contain readable audio; separately captured streams are merged before the final path is published.
6. Galleries and other non-video media return a structured unsupported-kind result instead of entering video transcription.
7. The collector bridge additionally requires its health response to declare the same download root.

Never delete or overwrite an existing saved work as part of acquisition. Reuse is allowed only when the adapter reports a valid existing file. Direct acquisition may remove only its own incomplete `.part` files. Lifecycle cleanup may terminate only the exact child process created by the current request; it must not kill a service discovered through health probing.

## Downstream handoff

For ordinary use, run `scripts/process_source.py SOURCE --json`. After acquisition succeeds, it uses `media_path` for FFprobe inspection, the managed transcription runner, and sparse inspection-frame extraction. It preserves `acquisition.json`, `probe.json`, timestamped transcript assets, `source.md`, and `processing.json` in the evidence directory. Inspection frames live in the configured cache; only frames actually cited by the final analysis should be copied into the durable `frames/` directory.

The deterministic entrypoint stops at `status: analysis_ready`. The Skill must then apply the selected Absorb／Judge／Apply evidence protocol and create `analysis.md` plus `analysis-完整底稿.md`; preprocessing must not claim to have performed judgment or knowledge integration.
