# Upgrade and rollback

## Check the installed version

The canonical version is stored in `video-knowledge/VERSION`. The first preview candidate is `0.1.0-preview.1`.

## Upgrade

Use a newly downloaded or updated repository checkout as the source. Do not edit the copy inside the user Skill directory and then overwrite it in place.

1. Read [CHANGELOG.md](CHANGELOG.md) for behavior or dependency changes.
2. Run the read-only plan:

   ```text
   python video-knowledge/scripts/setup.py --plan
   ```

3. Review paths, downloads, and system changes. After confirmation:

   ```text
   python video-knowledge/scripts/setup.py --apply --yes
   ```

4. Accept completion only when final Verify reports `complete_installation: true` and Doctor has no required missing item.

Valid models, videos, caches, formal analyses, and matching dependencies are reused. Updating the Skill does not require deleting or redownloading them.

## Automatic backup

When the installed Skill differs from the new source, Setup moves the complete old Skill into a non-discoverable version backup:

```text
$CODEX_HOME/skill-backups/video-knowledge/<UTC timestamp>/
```

Backups stay outside the scanned `skills/` directory, so Codex does not load an obsolete version as a duplicate Skill.

## Roll back only the Skill

First stop active Video Knowledge work and choose the exact backup after inspecting its `SKILL.md` and optional `VERSION`.

From a trusted current repository checkout, run the Skill stage with that backup as the source:

```text
python video-knowledge/scripts/setup.py --apply --yes --stage skill --skill-source "<exact backup directory>"
```

The installer stages and fingerprints the backup before replacing the current Skill; the current version is itself backed up. Then run:

```text
python video-knowledge/scripts/doctor.py
```

Older backups may show `unversioned` because they predate the `VERSION` file.

## Runtime compatibility

A Skill-only rollback does not downgrade Python packages, FFmpeg, or the model. If the chosen old Skill requires a different runtime, stop after Doctor reports the mismatch and use the matching tagged repository version's read-only plan. Do not guess dependency downgrades or delete the current model.

## User data

Upgrade and Skill rollback do not delete downloaded videos, cache, model files, formal Markdown analyses, or Obsidian notes. Any future uninstall workflow must keep those categories separate and require explicit confirmation before data removal.
