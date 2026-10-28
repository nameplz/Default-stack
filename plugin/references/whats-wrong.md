# whats-wrong

Research, then define a niche, clutch problem and split it into Phases and Steps that can be implemented without further guessing.

Inputs: `vision.md`, `decisions.md` and other existing docs (see `docs-convention.md`). If requirements are missing or contradictory, stop and ask.

## 1. Research

1. Size the research to the project. A small feature needs a light check of the existing code, docs and a source or two. A larger or unfamiliar problem needs deep research.
2. Before researching, list the items the research must cover (for example existing solutions, constraints, candidate libraries, known pitfalls).
3. Research and always save the findings with sources to `research/<topic>.md`, even when the research was light. Keep the doc as short as the research was.

## 2. Problem

The problem must be both:

| | |
|---|---|
| Niche | The target, the conditions it occurs under, and the affected user experience or feature are specifically identified |
| Clutch | Solving it directly improves how well the requirements are met, with minimal side work |

Record the problem, goals, non-goals and constraints in `work/<topic>/problem.md`.

## 3. Phases and Steps

- Build Steps around small features that actually work for the user.
- Split Phases only when their purpose or completion criteria differ.
- A Step is the smallest meaningful unit that can be implemented and verified on its own.
- Don't split work only by file or technical layer.
- Give every Step verifiable completion criteria and its prerequisites.
- A small project can be one Phase with one Step.

Record the plan in `work/<topic>/plan.md`.

## Done when

The next stage can start implementing without further guessing, not when the docs are written. Check that every Step has verifiable completion criteria and that no open question blocks it. If something does, resolve it or ask.
