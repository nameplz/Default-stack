# Team-up verification map

Use one entry per user-facing journey. Follow the baseline in [verify](../SKILL.md) and run doctor before each drive.

## Features

| Journey | Recipe | Drive argument |
| --- | --- | --- |
| 1 | [Single Dispatch lifecycle](lifecycle.md) | `lifecycle` |
| 2 | [Ask, answer, and resume](questions.md) | `questions` |
| 3 | [Decision gate and merge dependency](gate.md) | `gate` |
| 4 | [Coordinator instructions and follow-up](instructions.md) | `instructions` |
| 5 | [Review changes in the main checkout](review-main.md) | `review-main` |

## Driving conventions

- Use a new sandbox and evidence directory for every drive. The helper takes IDs and turn numbers from CLI responses.
- Run the worker commands from the assigned checkout using the same explicit DB. Worker-role commands exercise the SQLite CLI interface. Host execution and live model behavior require a separate run.
- Check the action, exit code, status, and Git or DB effect. `reserve` can return JSON `null` with exit 0. A successful exit alone does not prove a Dispatch was allocated.
- Record unreachable end states as FAILING. Keep the command and error or state that demonstrates the failure. Clean up and verify that the evidence still exists.
