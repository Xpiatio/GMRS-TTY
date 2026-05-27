---
name: continuous-specification
description: Continuous Specification process for writing code by defining specifications before implementing. Use whenever adding any new code, unless the user explicitly asks to skip specs or the code is exploratory/spike. Also known as TDD, but framed around specification rather than testing.
---

# Continuous Specification

Continuous Specification is a code design technique. Design emerges from usage, not speculation. Short feedback loops let you course-correct immediately. The resulting architecture is specifiable by design, not retrofitted. We are not trying to rush towards feature completion — it's important that the code is correct and well-designed. Be thorough and only add what specifications demand.

When starting, announce: "Using Continuous Specification skill in mode: [auto|human]"

MODE (user specifies, default: auto)  

- auto: DO NOT ask for confirmation or approval. Proceed through all steps without stopping.
- human: wait for confirmation at key points

STARTER_CHARACTER = ❗️ when setting an expectation, ✅ when met (green), 🌀 when designing, always followed by a space

## Vocabulary Bridge

CS terminology is the language of this skill. In codebases where "testing" language is established and not being changed, interpret existing terms using this mapping:

| CS Term    | Test Term                 |
|------------|---------------------------|
| Expectation | Test                      |
| Specification | Test Suite, file          |
| Set, unmet | Red, Fail, make it fail   |
| Meet       | Green, Pass, make it pass |
| Design     | Refactor                  |
| Establish  | Arrange                   |
| Execute    | Act                       |
| Expect     | Assert                    |

**When reading existing code:** translate test language into CS terms mentally — a failing test is a Set expectation (that's still unmet), a passing test suite is a Met Specification, etc.

**When writing new code:** always use CS language regardless of what surrounds it. New expectations, new specifications, and new comments use CS vocabulary.

## Core Rules

1. ALL code changes follow Continuous Specification — feature requests mid-stream are NOT exceptions. Set the expectation first, then code.
2. Set only one expectation at a time — focus on the simplest, lowest-hanging fruit behavior.
    + Only write enough of an expectation to be unmet--do not write more than is needed to fail given the current state of the code.
    + Be a stickler on this one! Expecting too much at once can lead to gaps in the specification.
3. Predict failures — state what we expect to fail before running the spec.
4. Two-step red phase:
   - First: make it fail to compile (class/method doesn't exist)
   - Second: make it compile but fail the expectation (return wrong value)
5. Minimal code to meet the expectation — just enough to make it green. 
   + If no expectation requires it, don't write it.
   + Be a stickler on this one! Try to "thwart" the expectation by hard-coding or otherwise implementing *only* what's being expected, not the stated intent of the expectation. This should then cause the expectation to be written better, to be more explicit, and cover more cases.
6. No comments in production code — keep it clean unless specifically asked.
7. Run all expectations in the specification every time — not just the one(s) you're working on.
8. Design at the first opportunity when all expectations are met.
    + Do *not* design/refactor while there are any unmet expectations.
    + Do *not* wait until the end of the implementation to design/refactor. Look for a chance every time expectations are met.
9. Specify behavior, not implementation — check responses or state, not method calls.
10. Push back when something seems wrong or unclear.

## Specification Types

- **Code Specifications**: specify isolated components and units. Written in Establish-Execute-Expect structure.
- **User Specifications**: specify critical paths across the whole system. Validate entire system behavior end to end.

Separate these concerns. Keep Code Specifications focused on a single component's public interface. Write User Specifications for critical user journeys.

## Specification Planning

1. Think about what the code you want to write should do.
2. Plan each expectation as a single-line `[EXPECT]` comment.

    Example:

    ```
    [EXPECT] Zero plus a number is equal to that number
    [EXPECT] Add two positive numbers
    [EXPECT] Add two negative numbers
    [EXPECT] Adds a negative and a positive number
    [EXPECT] Division by zero is not allowed
    ...
    ```
    
3. Check completeness — walk through [ZOMBIES](references/zombies.md) explicitly:
   - Zero/empty cases covered?
   - One item cases covered?
   - Many items cases covered?
   - Boundary transitions covered?
   - Interface clarity verified?
   - Exceptions/errors covered?
4. If MODE is human, wait for confirmation after planning the specification.

## Implementation Phase

1. Replace the next `[EXPECT]` comment directly with a failing expectation. No intermediate markers.
2. Structure expectations in Establish-Execute-Expect with empty lines separating each section (do not add section labels as comments).
3. Name expectations descriptively in natural language. Avoid underscores unless the target language requires them.
4. Use a `describe`/`it` nested structure:
   - `Given` blocks describe preconditions or data state.
   - `When` blocks describe the event or user action.
   - Nest `Given` blocks inside `When` blocks to express the same action under different conditions.
   - Start expectation names with `it should` (or language equivalent).
   - Expectation names should read as complete sentences when combined with their describe blocks.
5. Think through the expected value BEFORE writing the expectation. Trace the logic step by step.
6. Predict what will fail.
7. Run specifications, see compilation error (if the expectation targets something new).
8. Add minimal code to compile.
9. Predict the expectation failure.
10. Run specifications, see expectation failure.
11. Add minimal code to meet the expectation.
12. Predict whether all expectations will be met and why. Run specifications, see green.
13. Simplify. For each line/expression just added, ask: "Does a failing expectation require this?"
    - If no expectation requires it, delete it — or if it's necessary, add an `[EXPECT]` comment for it.
    - Run specifications after each simplification.
    - Repeat until every line is justified by an expectation.
14. Design.
    - Reflect on the domain: is there a missing concept that would make the code more expressive? An object waiting to be extracted? A better way to model the problem?
    - Introduce domain concepts (new abstractions) only — add NO new behavior. All expectations must still be met, and no new code should be added that doesn't have an expectation.
    - Think about improvements to expressiveness, clarity, simplicity.
    - Say `🌀 Starting design stage` and list planned changes.
    - Implement one at a time, run specifications after each.
    - When done (or if none needed), say "🌀 Design complete".
15. Go to step 1 for the next `[EXPECT]` comment. Repeat until all planned expectations are met.

## Specification Design Rules

- Never use mocking frameworks. Use [Nullable infrastructure wrappers](references/nullables.md) to isolate dependencies.
- One execution (act) per expectation.
- One logical assertion per expectation to clarify failures.
- Keep specification setup DRY but explicit.
- Create builders for complex object establishment.
- Write failing expectations before fixing bugs to prevent regression.
- Specify unhappy paths and edge cases, not just the happy path.
- Apply FIRST principles: Fast, Isolated, Repeatable, Self-verifying, Timely.

## Final Evaluation

1. Analyze the code written and think about expectations that might have been missed.
2. If there are any gaps, start the process for the missing expectations from the beginning — starting from `[EXPECT]` comments then following the process until done.
3. Is anything still hardcoded in the code that shouldn't be? Fix it, analyze gaps, and go back to earlier stages if needed.
4. Analyze code expressiveness and quality. If there's anything to improve, go to design phase.
