# Default-stack

A light harness for Claude Code and Codex that takes a vague idea for a small-to-medium personal project from casual chat to a verified implementation.

```
coffee-chat → whats-wrong → shall-we ⇄ is-it-ok
└──────────────── just-do-it ────────────────┘
```

| Skill | Does |
|---|---|
| `coffee-chat` | Casual chat that shapes the idea, written up as docs at the end |
| `whats-wrong` | Research, problem definition, Phase/Step plan |
| `shall-we` | TDD implementation, one commit per Step |
| `is-it-ok` | Verification in a separate session: PASS / FAIL / UNVERIFIED |
| `just-do-it` | All of the above in order, with at most 3 fix rounds |

Every skill runs only when you invoke it. Docs go to existing project docs when they fit, otherwise to `docs/default-stack/`.

## Install

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

## License

MIT
