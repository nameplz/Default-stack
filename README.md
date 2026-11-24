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
| `formal` | Formally verify the riskiest property, keep the proof in line with the code, gate merges on it when it runs in about two minutes, otherwise run it on a schedule |
| `explore` | Drive a release through the feature map and ship a fix PR for each bug reproduced twice, at most 5 per run |
| `team-up` | Coordinate Claude, Codex, and agy workers in separate Git worktrees, or assign read-only reviews of the main checkout, from Claude Code, Codex CLI, or agy, with Run state in SQLite |

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

Run `/default-stack:team-up` in the Claude desktop app's Code tab, the Claude Code CLI, or an interactive agy session, or invoke `$default-stack:team-up` in an interactive Codex CLI session. Install Python 3 with SQLite's WAL-reset fix (SQLite 3.51.3+, or the 3.44.6+/3.50.7+ backports; `init` and `status` warn otherwise) and the CLI for each external worker type you use (Claude, Codex, or agy). See the [coordinator guide](plugin/references/team-up.md).

Run state uses schema v4. Running `init` upgrades a v3 DB in place (pass the same `--db` if you use a custom path); other commands on a v3 DB ask for `init` first. v2 and older DBs need a new `--db` path; keep the old DB for its Run history.

Run the state CLI tests from the repository root:

```sh
python3 -B -m unittest discover -s plugin/skills/team-up/scripts/tests -v
```

## License

MIT
