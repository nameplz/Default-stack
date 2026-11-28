# Default-stack

Skills for Claude Code, Codex, and Antigravity (agy): shape a vague idea in casual chat, then set repositories up so checks, not instructions, hold agents to the work and changes merge themselves once `verify` passes.

```
coffee-chat
apply-stack → ship-it ← team-up, formal, explore
```

| Skill | Does |
|---|---|
| `coffee-chat` | Casual chat that shapes the idea, written up as docs at the end |
| `apply-stack` | One-time repo setup: a single verify command, CI, a verification skill, recurring mistakes blocked by checks, auto-merge gated on `verify` (branch protection is set, with your approval, before the pull request that adds CI) |
| `ship-it` | Deliver a change as a pull request that merges itself once `verify` passes |
| `formal` | Formally verify the riskiest property, keep the proof in line with the code, gate merges on it when it runs in about two minutes, otherwise run it on a schedule |
| `explore` | Drive a release through the feature map and ship a fix PR for each bug reproduced twice, at most 5 per run |
| `team-up` | Coordinate Claude and Codex workers in separate Git worktrees, or assign read-only reviews of the main checkout, from Claude Code, Codex CLI, or interactive agy, with Run state in SQLite |

Every skill runs only when you invoke it. Docs go to existing project docs when they fit, otherwise to `docs/default-stack/`.

## Install

`apply-stack`, `ship-it`, `formal`, and `explore` read skills from pstack. Install it first: in Claude Code from [cursor/plugins](https://github.com/cursor/plugins/tree/main/pstack) (`/plugin marketplace add cursor/plugins`, then `/plugin install pstack@cursor-plugins`), in Codex and agy from the port [michael-denyer/pstack-claude](https://github.com/michael-denyer/pstack-claude).

Optional: pstack is a Cursor plugin, and some skills its workflows use come from the `cursor-team-kit` plugin instead. They are not bundled for other harnesses. Everything still works without them. To add them, link them from [cursor/plugins](https://github.com/cursor/plugins): Claude Code uses `deslop`, `control-ui`, and `control-cli`, and Codex and agy use `control-ui` and `control-cli`. The commands use the Claude Code marketplace copy if it exists, otherwise a clone at `~/.cursor-plugins`. Run them once; the Claude Code copy updates with `claude plugin marketplace update`, the clone with `git -C ~/.cursor-plugins pull`.

macOS and Linux:

```sh
root=~/.claude/plugins/marketplaces/cursor-plugins
[ -d "$root" ] || { root=~/.cursor-plugins; [ -d "$root" ] || git clone https://github.com/cursor/plugins "$root"; }
src=$root/cursor-team-kit/skills
mkdir -p ~/.claude/skills ~/.agents/skills
for s in deslop control-ui control-cli; do ln -sfn "$src/$s" ~/.claude/skills/$s; done
for s in control-ui control-cli; do ln -sfn "$src/$s" ~/.agents/skills/$s; done
```

Windows (PowerShell; directory junctions need no administrator rights):

```powershell
$root = "$HOME\.claude\plugins\marketplaces\cursor-plugins"
if (-not (Test-Path $root)) { $root = "$HOME\.cursor-plugins"; if (-not (Test-Path $root)) { git clone https://github.com/cursor/plugins $root } }
$src = "$root\cursor-team-kit\skills"
New-Item -ItemType Directory -Force "$HOME\.claude\skills", "$HOME\.agents\skills" | Out-Null
foreach ($s in 'deslop', 'control-ui', 'control-cli') { New-Item -ItemType Junction -Force -Path "$HOME\.claude\skills\$s" -Target "$src\$s" | Out-Null }
foreach ($s in 'control-ui', 'control-cli') { New-Item -ItemType Junction -Force -Path "$HOME\.agents\skills\$s" -Target "$src\$s" | Out-Null }
```

Claude Code:

```
/plugin marketplace add nameplz/Default-stack
/plugin install default-stack@default-stack
```

Invoke with `/default-stack:coffee-chat`.

Codex:

```
codex plugin marketplace add nameplz/Default-stack
codex plugin add default-stack@default-stack
```

Invoke by mentioning the skill with `$` (registered as `default-stack:coffee-chat`; list with `/skills`).

Antigravity (agy), from a checkout of this repository:

```
agy plugin install ./plugin
```

Invoke with `/default-stack:coffee-chat`.

## Update

Claude Code, in your shell (then restart Claude Code):

```
claude plugin marketplace update default-stack
claude plugin update default-stack@default-stack
```

Codex:

```
codex plugin marketplace upgrade default-stack
codex plugin add default-stack@default-stack
```

agy: pull this repository, then rerun `agy plugin install ./plugin`.

## Team-up

Run `/default-stack:team-up` in the Claude desktop app's Code tab, the Claude Code CLI, or an interactive agy session you start directly, or invoke `$default-stack:team-up` in an interactive Codex CLI session. Install Python 3 with SQLite's WAL-reset fix (SQLite 3.51.3+, or the 3.44.6+/3.50.7+ backports; `init` and `status` warn otherwise) and the CLI for each external worker type you use (Claude or Codex). See the [coordinator guide](plugin/references/team-up.md).

agy worker dispatch is disabled. Google's [Antigravity terms §6](https://antigravity.google/terms) and [FAQ](https://antigravity.google/docs/faq) prohibit third-party agent orchestration with consumer sign-in. team-up does not distinguish authentication types, so it disables agy worker dispatch for all accounts. Existing agy records remain available for inspection, shutdown reconciliation, result delivery, and cleanup; see [existing agy records](plugin/references/team-up.md#existing-agy-records).

What you see and control:

| Command | Does |
|---|---|
| `board <run>` | Tasks grouped as 내 차례, 진행 중, 검토 대기, 머지 중, 막힘, 완료, with worker progress, worktree diff stats, and stalls after 30 minutes. `--json` for data |
| `board <run> --html [PATH] [--watch N]` | A self-contained HTML board that refreshes itself. With `--watch`, it rewrites the page every N seconds without the coordinator and leaves a final page when the Run finishes |
| `progress <dispatch> --turn N [--step k/n] <text>` | A worker reports its plan step. The board updates; the coordinator is not woken |
| Run notes | Shared notes scoped to one Run, passed to each worker's next turn |
| `pr-open`, `pr-policy`, `pr-arm`, `pr-sync`, `wait --sync-prs` | Follow up on pull requests after delivery. Policy is `hold` by default; `auto` needs its own approved gate |

Fix turns occupy a worker slot, like first turns.

Run state uses schema v5. Running `init` upgrades a v3 or v4 DB in place (pass the same `--db` if you use a custom path); other commands on an older DB ask for `init` first. v2 and older DBs need a new `--db` path; keep the old DB for its Run history.

## Development

Run the checks CI runs before you call a change done:

```sh
scripts/verify
```

It runs the unit tests and blocks `plugin/` changes without a version bump, links from `plugin/` to files outside it, and new comments. Pull requests to `main` merge only after `verify` passes. The verification skill that drives team-up end to end is in [`.claude/skills/verify/`](.claude/skills/verify/SKILL.md). Agent rules are in [AGENTS.md](AGENTS.md).

## License

MIT
