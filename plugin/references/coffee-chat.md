# coffee-chat

Turn a vague idea into clearer requirements through a loose, casual conversation. Structure is applied only when writing docs at the end.

Read the project's existing docs first (see `docs-convention.md`) so you know the context.

## Conversation

- Let the user think out loud. Take half-formed thoughts, long rambles, typos and changes of mind as they come, and read for intent.
- Keep it a conversation, not an interview. Carry it on naturally and ask only when a question actually helps.
- Don't summarize each message or turn it into a list of questions.
- Offer light opinions, technical pushback, other approaches and related examples where they help.
- Explore ideas that don't need deciding yet. When something is ambiguous, leave it open instead of resolving it now.

## Writing it up

Only when the user ends the chat or asks for a write-up.

1. Sort what came up:

   | Status | Meaning |
   |---|---|
   | Confirmed | The user explicitly chose it |
   | Candidate | Worth considering |
   | Open | A question not yet answered |
   | Discarded | Discussed and not chosen |

   Confirmed means the user said it. Anything you inferred, however likely, is a Candidate until the user confirms it, even if you flag it as an assumption.
2. Write or update docs following `docs-convention.md`:
   - `vision.md`: purpose, the idea, candidates, open questions
   - `decisions.md`: confirmed decisions with rationale, discarded directions with the reason
   - Independent topics in their own docs, linked with relative links
3. No big PRD, no transcript. Keep what a later session needs.
4. Tell the user which docs changed and what they now say, briefly.
