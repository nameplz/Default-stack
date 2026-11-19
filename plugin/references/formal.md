# formal

Prove a property of the code that tests rarely reach, and keep that proof describing the code that exists.

## Preconditions

- The repository has a `verify` command and CI from `apply-stack`. If not, stop and point to `apply-stack`.

## Choose the mode

- No formal verification skill in the repository: follow pstack `create-formal-verification-skill`.
- One exists: follow pstack `maintain-formal-verification-skill`. It finds the skill by what it does, not by name.
- The user names a flow and wants it seen as states: follow pstack `statechart`.

## Where it lives

- Put the generated skill at `.claude/skills/formal-<area>/` and link it for Codex: `ln -sfn ../../.claude/skills/formal-<area> .agents/skills/formal-<area>`.
- Keep models, harnesses and property files in the repository next to the skill, not in a temp directory.

## Gate it

- Add the check's command to the repository's `verify` when it finishes in about two minutes. CI then runs it in the required `verify` job.
- If it is slower, add it as a separate command (such as `verify:formal`) and a scheduled CI workflow, and write in `AGENTS.md` which code changes must run it before shipping.
- Install the checker's toolchain in CI with pinned versions (for example Java and TLA+ tools for TLC).
- Add a row to the rule-to-enforcement table in `AGENTS.md`: the property, the command, the past bug it would have caught if there is one.

## Prove it

Before handing off, break the property with a scratch change to the real code and show the check fails. Drop the scratch change and show the check is back where it started. A check that was never seen failing is a draft.

## Finish

- Report what is verified, the tool and why, the bounds, what it found in plain words, how to run it, and what it does not cover.
- A property that fails on the current code is a finding. Report it. Don't weaken the property or the model to pass.
- Don't commit. Suggest `ship-it` to deliver the change.
