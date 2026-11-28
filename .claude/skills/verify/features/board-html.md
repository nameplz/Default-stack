# HTML board and watch

The coordinator can write an HTML board to share Run progress. A watch rewrites the page until the Run finishes and leaves a final page without refresh.

## Sub-features

- Write the default HTML page beside the State DB.
- Watch a supplied path at a positive interval.
- Observe watcher exit and retain the final page without a refresh directive.

## How to get to it (user POV)

Ask for the Run board as a page and keep it open while the worker completes its assignment.

## Driving it with sandbox.py

Run `"$helper" drive "$sandbox" board-html` after launch and doctor.

1. Start a Task and run `board <run> --html`. Verify the default path and escaped Task goal.
2. Start `board <run> --html <path> --watch 1` and capture the live page with refresh and an occupied slot.
3. Report successful worker exit and deliver the result. Require the watcher to exit successfully and the page to show the delivered Task, zero occupied slots, and no refresh directive. Check `html-default.html`, `html-live.html`, and `html-final.html`.

## Gotchas

- Delivery moves the Task from review to done. The watcher finishes once all Tasks are in the done group.
- See [HTML writing and watch](../../../../plugin/skills/team-up/scripts/team_up.py#L1722) and [the coordinator guide](../../../../plugin/references/team-up.md#L304).
