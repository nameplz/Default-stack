# Docs convention

Shared by every default-stack skill. Docs exist so a later session can restore context from them alone.

## Before writing

1. Look at the project's existing docs and directory layout first (README, `docs/`, planning or notes folders).
2. If a suitable doc already exists, update it.
3. Only when nothing fits, use `docs/default-stack/` as the base path and create just the files you need.

## Layout

| Path | Holds |
|---|---|
| `index.md` | Links between docs |
| `vision.md` | Purpose of the project and the idea |
| `decisions.md` | Confirmed decisions and their rationale |
| `research/<topic>.md` | Technical research, with sources |
| `work/<topic>/` | Problem definition, Phase/Step plan, verification results |

## Rules

- Create a doc only when needed. Prefer updating an existing one.
- Split out only independent topics. Link related docs with relative links.
- Don't repeat content across docs; link to it.
- Don't restructure existing docs unless the task requires it.
- Update `index.md` whenever you add or remove a doc.
- Write docs in the user's language.
