# shall-we

Implement the plan's Steps one at a time with TDD, writing only the code that is needed.

Inputs: `work/<topic>/plan.md`, `problem.md`, `decisions.md` (see `docs-convention.md`). If an is-it-ok report has must-fix items, fix those first. Fix optional items only when the user asks.

## Each Step

1. Re-read the Step's completion criteria and prerequisites.
2. Red: write the smallest tests that express the completion criteria. Run them and confirm they fail for the right reason.
3. Green: write the minimum code that passes.
4. Refactor: improve the code while tests stay green. Don't widen the scope.
5. Check coverage (below).
6. Mark the Step done in the plan and commit, one commit per Step.

## Tests

Test behavior that matters. Don't add meaningless tests to raise counts or coverage.

## Coverage check

80% coverage on changed lines is a check, not a goal.

1. Use the coverage tool the project already has.
2. If there is none, use the language's standard tool to produce an lcov or Cobertura report: `vitest --coverage` or `jest --coverage` (JS/TS), `pytest-cov` (Python), `go test -coverprofile` (Go), `cargo llvm-cov` (Rust).
3. Measure changed lines only with `diff-cover <report> --compare-branch=<base>`.

Below 80%: look at the uncovered lines and why they are uncovered before adding tests. Add a test only where it is meaningful, and note the reason otherwise. If coverage can't be measured, say so.

## Implementation

- Write the minimum that meets the requirement. No over-engineering, no speculative options or abstractions.
- In UI, avoid unnecessary secondary labels and descriptions. Convey information through structure and layout.
- Leave code outside the requirement alone. If fixing the root cause needs changes around it, make them, state why, and verify their impact.

## Unfamiliar features

Don't build from scratch right away. First search GitHub for similar open-source projects that are actively maintained and clearly licensed, and compare implementation ideas, dependencies and known issues. Check:

- Maintenance status
- License
- Compatibility with this project
- Implementation complexity
- Known defects

Don't pick by star count. Don't copy code that is incompatible or of unclear origin. If nothing fits, note why and implement it yourself. Save a substantial comparison to `research/<topic>.md`.

## Stop and ask

If the spec is ambiguous or conflicts with the existing code, stop, explain the conflict and ask. Don't guess.
