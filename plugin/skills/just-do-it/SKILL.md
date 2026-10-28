---
name: just-do-it
description: Runs the whole default-stack flow, coffee-chat to whats-wrong to shall-we to is-it-ok, with a bounded fix loop. Run only when the user invokes it.
disable-model-invocation: true
---

# just-do-it

Run the full workflow by following each reference in order. Don't invoke the other skills, and don't restate their rules. Paths are relative to this file, and every stage also follows `../../references/docs-convention.md`.

1. coffee-chat: `../../references/coffee-chat.md`. Chat with the user. After the write-up, show the docs and wait for the user to confirm them.
2. After confirmation, continue without pausing:
   1. whats-wrong: `../../references/whats-wrong.md`
   2. shall-we: `../../references/shall-we.md`
   3. is-it-ok: `../../references/is-it-ok.md`
3. If is-it-ok reports FAIL, fix the must-fix items with shall-we and run is-it-ok again. Allow at most 3 fix rounds.
4. If it still fails after 3 rounds, stop and report the unresolved items.

Stop conditions inside each reference, such as shall-we's stop-and-ask, still apply.
