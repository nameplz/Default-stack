# pstack

These skills depend on the pstack plugin and call its skills by reading them. They never copy them.

## Find it

| Host | Path | Read once per session |
|---|---|---|
| Claude Code | `ls -d ~/.claude/plugins/cache/cursor-plugins/pstack/*/ \| sort -V \| tail -1` | `docs/harness/claude-code.md` |
| Codex | `ls -d ~/.codex/plugins/cache/*/pstack/*/ \| sort -V \| tail -1` | `skills/poteto-mode/references/codex-tools.md` |

The version folder changes on every update, so look it up each time. In Claude Code use the official `cursor-plugins` build, not an older community port that may also be cached. If pstack is missing, stop and tell the user to install it first.

"Follow pstack `<name>`" means: read `<pstack>/skills/<name>/SKILL.md` in full and carry out its procedure. Most pstack skills are user-invoked only, so read the file instead of calling a skill tool.

Some skills exist only in one port (Codex has `fix-ci`, `babysit`, `fix-merge-conflicts`; Claude Code does not). When a named skill is missing, do the step directly and say so.
