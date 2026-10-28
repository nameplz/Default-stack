# is-it-ok

Verify the implementation in a separate session and report a verdict backed by evidence.

## Separate session

Spawn a subagent to do the verification. Pass it these inputs explicitly; don't assume it can see this conversation:

- Paths to the problem definition and plan (`work/<topic>/`)
- Paths to related docs (`vision.md`, `decisions.md`, `research/`)
- The git diff range to review (`<base>..HEAD`)
- Test and coverage results, with the commands used

If subagents aren't available, verify from these inputs alone and say so in the report.

## Checks

| Area | What to check |
|---|---|
| Spec | Each completion criterion met, non-goals not violated, nothing unnecessary or overbuilt |
| Structure | Design and code quality problems |
| Execution | Run tests and the build. If the code can be run, run it and check the result |

Also check for changes that weaken tests: added `.skip`/`.only`, deleted tests, loosened assertions, and lint or type-check suppression comments.

## Verdict

- Each item is PASS, FAIL or UNVERIFIED.
- PASS requires concrete evidence (command output, `file:line`). Without evidence it is UNVERIFIED.
- Keep what you actually checked separate from what you could not check.
- Low-severity style preferences are not defects and never cause FAIL.

Overall: FAIL if any must-fix item fails. Otherwise UNVERIFIED if a completion criterion is unverified. Otherwise PASS.

## Findings

For each problem report:

- File and location
- How to reproduce
- Expected impact
- Must-fix or optional

Save the report to `work/<topic>/verification.md` (update it if it exists).
