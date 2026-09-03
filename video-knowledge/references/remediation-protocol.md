# Runtime Remediation Protocol

Read this reference only after Setup or Doctor returns a structured failure, or when the user explicitly asks to repair an installation.

## Responsibility split

- Setup performs only known deterministic installation steps.
- Doctor verifies required capabilities and returns structured diagnostics.
- Codex interprets diagnostics, consults official sources when needed, proposes one supported fix, obtains authorization for material system changes, applies it, and reruns Doctor.

Do not put an open-ended autonomous troubleshooting loop inside Python.

## Required diagnostic fields

Every failed installation step should return JSON containing:

- `error_code`;
- `component`;
- `platform` and architecture;
- attempted command or operation;
- exit code;
- concise stderr tail;
- current attempt number;
- supported fixes known to the installer;
- paths created or changed in the current attempt.

Never replace the original error with a generic “installation failed.”

## Remediation loop

1. Confirm the exact failed component; do not reinstall unrelated working components.
2. Read the relevant official project documentation, package index, or OS package-manager record. Use third-party discussion only to locate an official fix, not as the final authority.
3. Choose one fix supported by the observed platform and architecture.
4. Explain the concrete change and obtain authorization if it installs system software, changes permissions, installs Homebrew or Rosetta, downgrades Python/packages, or writes outside the approved data root.
5. Apply only the selected fix.
6. Rerun the failed step, then rerun Doctor.
7. If Doctor passes, record the fix in the installation receipt.

## Retry and stop conditions

- At most two focused repair attempts per component.
- If the same error recurs without new evidence, stop instead of trying another random command.
- A different error starts a new diagnosis only when the previous component genuinely progressed.
- Never use `curl | sh`, arbitrary mirrors, unverified binaries, or commands copied from search snippets.
- Never delete user videos, models, formal analyses, or a working environment to make a check pass.
- Preserve complete downloads and valid caches for reuse after interruption.
- If no verified compatible path exists, return `blocked` with the exact missing capability and the safest manual next step.

## macOS strategy

Detect `Darwin` plus `arm64` or `x86_64` before selecting a recipe.

Preferred order:

1. Reuse a compatible Python and FFmpeg already on PATH.
2. Create a project venv and install the platform wheel selected by pip.
3. For FFmpeg, use an existing Homebrew installation; if Homebrew or FFmpeg is absent, ask before installing either.
4. Download the pinned model using the same model manifest and HTTP fallback used on Windows.
5. Run a short model load, transcription, FFprobe, and frame extraction smoke test.

Do not silently install Rosetta, compile CTranslate2 from source, downgrade Python, or switch model revisions. These require an explicit diagnosis and user approval.

Intel and Apple Silicon must keep separate lock/evidence records. Until both receive real-machine tests, report macOS as unverified rather than supported.

## Successful repair

A command succeeding is not the final condition. Repair succeeds only when:

- the intended component works;
- unrelated working components remain intact;
- Doctor returns `ready` or `ready_with_warnings`;
- the receipt records what changed and what remains optional.
