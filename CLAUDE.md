# Telegram Bot Engineering Constitution

You must follow this file for every task in this repository.

## Non-negotiable mandate

Do not make, present as complete, commit, or recommend pushing any code change until you have:

1. understood the literal request
2. expanded the implied concepts behind the request
3. inspected the relevant code paths and neighboring flows
4. run validation commands
5. run the actual bot or relevant executable flow when possible
6. tested the real behavior end-to-end
7. intentionally tried to break it
8. re-tested after your code change
9. reviewed the code for human-quality structure rather than AI-shaped code

Never claim something is fixed based only on reading code.

Static reasoning, linting, formatting, import checks, syntax checks, and type checks do not count as proof if the feature can actually be run.

## How to interpret my requests

Treat every request as four things at once:

1. the exact literal instruction
2. the product intent behind it
3. the engineering implications around it
4. the likely neighboring issues it could affect

Do not respond narrowly to only the exact words I used.

If I give a concept like:
- make it more human
- make it cleaner
- make it robust
- make it not look AI
- fix the flow
- make it solid
- test it thoroughly

You must expand that concept into concrete requirements before acting.

## Concept expansion rule

Before writing code, translate abstract requests into explicit checks.

Examples:

"Human code" means:
- no obvious AI-shaped redundancy
- no repetitive boilerplate with tiny edits
- no useless abstractions
- no giant helper explosion
- no robotic function names
- no over-commenting obvious logic
- no rewriting unrelated code just to look productive
- no fake cleanliness from splitting logic too much
- structure should match what a skilled human maintainer would actually keep

"Robust" means:
- stale callback handling
- malformed input handling
- empty input handling
- duplicate tap handling
- rapid tap handling
- cancel/back path handling
- interrupted flow handling
- no-data state handling
- partially-filled-data handling
- neighboring shared-flow checks

"Clean" means:
- code is easy to scan
- state transitions are explicit
- helpers exist for a real reason
- duplication is removed only when that truly improves readability
- naming is natural and specific, not robotic
- implementation matches the actual bot behavior rather than generic theory

## Human-code standard

All code must look like it was written by a thoughtful human developer maintaining a real product.

### Required qualities

- Prefer straightforward, idiomatic code over generic abstraction.
- Prefer existing repo patterns unless they are clearly harmful.
- Prefer object-oriented structure for bot modules and flows when adding new architecture.
- Keep changes proportional to the problem.
- Use helpers only when they remove meaningful duplication or make the code easier to understand.
- Keep local reasoning intact so a maintainer can understand the feature without opening too many files.
- Refactor only when it materially improves the changed area.

### Forbidden AI-shaped code

Do not produce:
- repeated near-identical functions with tiny differences
- one-use helper abstractions
- giant generic utility files
- robotic names like `handle_process_user_input_submission`
- verbose comments explaining obvious lines
- broad exception handling without a real reason
- speculative future-proof abstractions
- cosmetic churn across unrelated files
- over-engineered patterns the project does not need
- code that looks organized only for appearances

### Human-code self-review

Before finalizing any change, check all of these:

1. Would an experienced engineer keep this structure?
2. Does this code solve the task directly?
3. Did I introduce abstractions a human would probably delete?
4. Is any remaining duplication clearer than over-abstraction would be?
5. Would a skeptical senior engineer find this diff economical and intentional?
6. Is the final version smaller, more natural, and less AI-shaped than the first draft?

If any answer is no, revise before presenting.

## Scope discipline

Make the smallest safe change that fully solves the real problem.

Do not touch unrelated code unless:
- it is directly part of the bug
- it shares the same broken logic
- it must change to keep the implementation coherent

Do not create cosmetic churn.

## Required workflow for every task

1. Restate the exact user-visible behavior being changed.
2. Expand the request into implied concepts, UX expectations, and engineering consequences.
3. Identify relevant files, handlers, callbacks, menus, state transitions, persistence, and shared utilities.
4. Identify likely adjacent regressions before editing.
5. State what "good" looks like both in UX and in code structure.
6. Run relevant validation commands.
7. Run the actual bot/app flow if possible.
8. Exercise the feature end-to-end.
9. Intentionally try to break it with bad inputs and strange interaction patterns.
10. Only then edit code.
11. Re-run validation after editing.
12. Re-run the actual bot/app flow after editing.
13. Re-test the changed flow and neighboring flows.
14. Perform the human-code self-review.
15. Only then present the change as complete.

## Telegram bot test requirements

For any Telegram bot or menu-driven flow, test all relevant cases:

- happy path
- empty input
- malformed input
- oversized input
- weird punctuation
- duplicate taps
- rapid repeated taps
- stale callback buttons
- cancel path
- back path
- forward then back then forward again
- sibling menu switching
- no-data state
- partially-populated-data state
- editing an existing item
- deleting an item
- interrupted flow resumed from stale state
- repeated submit after success
- old bot messages still being tappable
- shared callback prefix collisions
- DB write then readback verification

If there are buttons, menus, callbacks, or stateful steps, assume they are fragile until proven otherwise.

## Adversarial QA rule

You must act as both:
- the implementer trying to complete the request
- the hostile QA tester trying to prove the implementation is weak

Before finalizing, identify:
- 3 likely failure modes
- 3 weird user behaviors
- 3 adjacent regressions
- 3 reasons the code might still look AI-generated

Test against them where possible. If not tested, label them explicitly as unverified.

## Real execution rule

Prefer real execution over assumption.
Prefer evidence over confidence.

If the environment prevents running the bot or test flow, say that explicitly and do not present the result as verified.

## Done definition

A task is not done unless all of the following are true:

- the changed user flow works in the real running bot
- validation commands passed
- likely adjacent regressions were checked
- edge cases were intentionally attempted
- the code passed the human-code self-review
- the final response includes a concise test report

## Required final report format

Every coding response must end with this exact structure:

Understanding:
- literal request
- expanded concepts inferred from the request

Tested:
- exact commands run
- exact flows exercised
- exact edge cases attempted

Code review:
- why this implementation looks human and maintainable
- what duplication was intentionally kept or removed
- what abstractions were avoided on purpose

Result:
- what passed
- what failed
- what was fixed

Risk:
- anything not tested
- anything still suspicious

## Repo conventions

- Prefer object-oriented design for bot modules and feature flows.
- Preserve existing architecture unless there is a strong reason to change it.
- Explain root cause, not just symptom.
- Keep callbacks, navigation, and state transitions explicit.
- Favor maintainability over cleverness.

## Forbidden shortcuts

Do not say "fixed" if you did not run it.
Do not say "human-like" if you did not review for AI-shaped code.
Do not stop after one successful interaction.
Do not only test the literal path I named.
Do not skip neighboring flows that share handlers, state, or callbacks.
Do not present a refactor as a fix unless it improves the real user-visible problem.
