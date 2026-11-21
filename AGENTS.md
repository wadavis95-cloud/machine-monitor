# Working with Claude (collab mailbox)

**Project purpose: interview prep and learning.** The user must be able to explain every layer of this project. Prefer small, readable changes over clever or sweeping ones. Don't add abstractions, dependencies, or features the task didn't ask for. When working with the user directly, explain what you're doing and why as you go.

The user runs Codex and Claude in separate terminals. Claude plans and reviews. Codex implements. Claude has a small token budget, so keep everything you send it short.

## Mailbox (`.collab/`, gitignored)
- `.collab/to-codex.md`: the latest message from Claude to you. It gets overwritten each time.
- `.collab/to-claude.md`: your reply to Claude. Overwrite it; don't append.
- `.collab/log.md`: append-only history. Append each message you send. Never read it unless asked.

## Headless runs (the usual case)
Claude usually runs you with `codex exec` through a runner script. Your final message is saved to `.collab/to-claude.md` automatically, so don't write that file yourself. Just make your final message follow the reply format below.

## When the user says "check inbox" in an interactive session
1. Read `.collab/to-codex.md` and do the task as written. Respect its scope and its "don't touch" list.
2. Run the tests it lists.
3. Overwrite `.collab/to-claude.md` with this format, max ~150 words:

```
# from: codex | re: <id> | status: done | blocked | question
## Summary
<2-4 bullets: what you did>
## Files changed
<paths only>
## Tests
<exact summary line(s), e.g. "31 passed" / "pass 2 fail 0">
## Concepts
<1-3 bullets: the key concept or technique behind the change, and why you chose it over the alternatives (the user is learning)>
## Open issues / questions
<or "none">
```
4. Append the same block to `.collab/log.md`.
5. Tell the user: "Reply written. Tell Claude to check inbox."

Don't paste file contents or full diffs into the reply. Claude reads `git diff` itself. Don't commit unless the message asks you to.

## Handoff back to Claude
The user works with you directly between brainstorming sessions with Claude. When the user says "handoff to claude", or a work session is wrapping up, overwrite `.collab/handoff.md` with up to 200 words:
- What changed since the last handoff (features, files, commits)
- Decisions made, and why
- Open problems, ideas, and questions for brainstorming
- Current test status (exact summary lines)
Claude reads only this file and `git log --oneline` to catch up, so keep it accurate and short.

## Claude's token budget
Before writing a reply or handoff for Claude, read `.collab/claude-budget.txt`:
- `normal`: use the standard limits (reply ≤180 words, handoff ≤200).
- `low`: reply ≤80 words and handoff ≤100. Only status, files changed, test lines, and blockers. Skip Concepts; the user can ask you directly.
- `critical`: one line only (status + test result). Save any detail to `.collab/details.md` for later.

## Learning log
After each change, append 1-2 rows to `LEARNING.md` for any new concept, in plain words with an everyday analogy and an interview one-liner. Skip concepts that are already listed. The user is a beginner, so keep the wording simple.
