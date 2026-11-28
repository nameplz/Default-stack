# Pull request follow-up

The coordinator tracks a delivered PR on hold by default, can arm auto-merge with dedicated user approval, and records checks and merge results.

## Sub-features

- Register with `pr-open` and verify default hold.
- Require a dedicated approved gate for `pr-policy <task> auto` before using `pr-arm`.
- Observe a failed check via `wait --sync-prs` and a merge via `pr-sync`.

## How to get to it (user POV)

Ask the coordinator to watch a delivered PR, approve auto-merge for that PR, then check a reported failure and the eventual merge.

## Driving it with sandbox.py

Run `"$helper" drive "$sandbox" pr-follow-up` after launch and doctor.

1. Deliver a Dispatch and register its PR against the sandbox's fake `gh`. Start the fixture with auto-merge enabled and require registration to disarm it and record hold. Probe `pr-arm` on hold.
2. Reject auto policy with a missing approval and with an approved Task gate. Approve a dedicated PR gate, switch to auto, and require `pr-arm` to target the observed head SHA.
3. Set the fake check to failing. Require `wait <run> --sync-prs 1` to report the failure and the dependent Task to stay blocked. Set the fake PR to merged, run `pr-sync`, and require the merge event and dependent reservation. Inspect `pr-probes.json` and `gh-calls.json`.

## Gotchas

- The fake CLI serves fixture data and rejects unexpected arguments. This journey exercises PR state transitions with no GitHub connection.
- See [PR registration and policy](../../../../plugin/skills/team-up/scripts/team_up.py#L576), [sync and arm](../../../../plugin/skills/team-up/scripts/team_up.py#L763), and [the coordinator guide](../../../../plugin/references/team-up.md#L289).
