# Default-stack

Skills for Claude Code and Codex: shape a vague idea in casual chat, then set repositories up so checks, not instructions, hold agents to the work and changes merge themselves once `verify` passes.

```
coffee-chat
apply-stack → ship-it ← formal, explore
```

| Skill | Does |
|---|---|
| `coffee-chat` | Casual chat that shapes the idea, written up as docs at the end |
| `apply-stack` | One-time repo setup: a single verify command, CI, a verification skill, recurring mistakes blocked by checks, auto-merge gated on `verify` |
| `ship-it` | Deliver a change as a pull request that merges itself once `verify` passes |
| `formal` | Formally verify the riskiest property, keep the proof in line with the code, gate merges on it |
| `explore` | Drive a release through the feature map and ship a fix PR for each reproduced bug |

Every skill runs only when you invoke it. Docs go to existing project docs when they fit, otherwise to `docs/default-stack/`.

## Install

Every skill except `coffee-chat` reads skills from pstack. Install it first: in Claude Code from [cursor/plugins](https://github.com/cursor/plugins/tree/main/pstack) (`/plugin marketplace add cursor/plugins`, then `/plugin install pstack@cursor-plugins`), in Codex from the port [michael-denyer/pstack-claude](https://github.com/michael-denyer/pstack-claude).

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
