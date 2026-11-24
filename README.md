# Default-stack

Skills for Claude Code, Codex, and Antigravity (agy): shape a vague idea in casual chat, then set repositories up so checks, not instructions, hold agents to the work and changes merge themselves once `verify` passes.

```
coffee-chat
apply-stack → ship-it ← team-up, formal, explore
```

| Skill | Does |
|---|---|
| `coffee-chat` | Casual chat that shapes the idea, written up as docs at the end |
| `apply-stack` | One-time repo setup: a single verify command, CI, a verification skill, recurring mistakes blocked by checks, auto-merge gated on `verify` |
| `ship-it` | Deliver a change as a pull request that merges itself once `verify` passes |
| `formal` | Formally verify the riskiest property, keep the proof in line with the code, gate merges on it |
| `explore` | Drive a release through the feature map and ship a fix PR for each reproduced bug |
| `team-up` | Coordinate Claude and Codex workers in separate Git worktrees from Claude Code, with Run state in SQLite |

Every skill runs only when you invoke it. Docs go to existing project docs when they fit, otherwise to `docs/default-stack/`.

## Install

`apply-stack`, `ship-it`, `formal`, and `explore` read skills from pstack. Install it first: in Claude Code from [cursor/plugins](https://github.com/cursor/plugins/tree/main/pstack) (`/plugin marketplace add cursor/plugins`, then `/plugin install pstack@cursor-plugins`), in Codex and agy from the port [michael-denyer/pstack-claude](https://github.com/michael-denyer/pstack-claude).

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

Invoke with `/default-stack:coffee-chat`. `team-up` needs Claude Code and does not run in agy.

## Team-up

Run `/default-stack:team-up` in the Claude desktop app's Code tab or the Claude Code CLI. Install Python 3 and the CLI for each external worker type you use. See the [coordinator guide](plugin/references/team-up.md).

Run the state CLI tests from the repository root with a Python build that includes SQLite's WAL-reset fix.

```sh
python3 -B -m unittest discover -s plugin/skills/team-up/scripts/tests -v
```

## License

MIT
