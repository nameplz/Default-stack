# explore

Drive the app through its user journeys, find what breaks, and fix each reproduced bug in its own pull request that auto-merges once `verify` passes.

## Preconditions

- A verification skill with a feature map exists (`.claude/skills/verify/` from `apply-stack`). If not, stop and point to `apply-stack`.
- The `ship-it` preconditions hold: auto-merge is on and the default branch requires `verify`.
- Run it per release. The target is the latest release tag, or the default branch head when there are no tags. The user can schedule it in their host's scheduler; this skill does one run.

## Explore

1. Read the verification skill and its feature map. Follow pstack `maintain-verification-skill` first if the map no longer matches the code.
2. For each feature, drive the journey end to end through the verification skill, then push on its edges: unusual and empty input, interrupts and cancel, resize, slow or failing backends, repeated actions, restart and resume.
3. Keep evidence for every finding (transcript, screenshot, state files) outside the repository or in an ignored path.
4. Ask the user before sending input to a paid model or external service.

## Classify

| Finding | Action |
|---|---|
| Bug reproduced twice from a clean start | Fix it (below) |
| Not reproducible, or needs a product decision | Report it, don't fix |
| Journey the feature map lacks | Add it to the map |

## Fix

For each reproduced bug, separately:

1. Branch from the default branch.
2. Write a test that fails for the bug's reason first. Add a check when the bug is a kind that can recur.
3. Fix the root cause with the smallest change. Leave unrelated code alone.
4. Run `verify`.
5. Deliver it with `ship-it`, with the reproduction and evidence in the pull request body.

Open at most 5 pull requests per run. Report the rest.

## Report

Save the report as `work/explore/<date>.md` following `docs-convention.md`: target commit, each feature with result and evidence, each finding with its class and pull request link, and what was not explored.

## Don't

- Weaken tests, checks or journeys to make a run pass.
- Bundle several bugs into one pull request.
- Change product behavior that isn't a bug. Report it instead.
