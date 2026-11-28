# Agent rules

- Run `scripts/verify` before calling a change done. CI runs the same command.
- Deliver through a pull request with the `ship-it` skill. Never push to `main`.
- For team-up behavior changes, also drive the journeys in the verification skill at `.claude/skills/verify/` (linked from `.agents/skills/verify`).
- Repeated corrections: when the user corrects you, check your saved feedback (memory in Claude Code; `~/.codex/corrections.md` in Codex, `~/.gemini/corrections.md` in agy, appending `date | repo | correction`). If the same correction is already there, say it is a repeat and suggest pstack `correct`. Run it only after the user agrees.

| Rule | Enforced by | Past mistake it catches |
| --- | --- | --- |
| A change under `plugin/` raises the plugin version | `scripts/verify` `version-bump` | Merges 50a43e4, 74b2107, 49d5de8, 47c8687, 1b93527 shipped `plugin/` changes at an unchanged version; 70f4331 needed 012328d to bump |
| Both plugin manifests carry the same name and version | `scripts/verify` `manifests` | |
| Markdown links in `plugin/` resolve inside `plugin/` | `scripts/verify` `plugin-links` | |
| No comments on source lines changed since the merge base | `scripts/verify` `no-comments` | |
| Python compiles and JSON parses | `scripts/verify` `compile`, `json` | |
| team-up CLI behavior | `scripts/verify` `unittest` | |
