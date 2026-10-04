---
name: test-necessity-review
description: Use when planning, adding, modifying, or reviewing tests in a Discussion, Design, Plan, or Pull Request, especially when a test may encode implementation details, temporary product state, migration results, or coverage targets.
---

# Test Necessity Review

Before adding or modifying a test, decide whether it protects durable behavior.

Commit a permanent test only when it can catch a future regression in a stable
product behavior, public contract, security boundary, or data integrity rule.
Do not add a test merely to prove that the current branch implemented its task.

## When to use

- Before adding or modifying tests during implementation, including simple Issues without a Discussion, Design, or Plan.
- A Discussion, Design, or Plan proposes a test suite, regression test, coverage target, or acceptance test.
- A Pull Request adds or changes tests.
- A change removes UI, renames or moves code, changes seed data, or performs a mechanical refactor and someone requests a new test.

Do not use this to avoid verification. Run the existing tests and perform
proportional temporary checks even when no permanent test is justified.

## Decision

First inspect existing tests for the same behavior. Reuse or extend existing
coverage when sufficient; do not add another test for the same regression
solely because the implementation changed.

For each proposed new test, answer:

> What future regression would this test catch that existing tests would miss?

If existing tests already catch that regression, run them instead of adding a
duplicate. A new case is justified when it covers a distinct failure path or
edge case that the existing suite would miss.

Keep the test when the answer names a durable observable invariant, such as:

- a business rule or important recurring edge case;
- a permission or security boundary;
- a public API or UI behavior relied on by users or other modules;
- a data integrity, persistence, or idempotency requirement;
- a non-trivial bug with a reproducible failure mode.

Use temporary verification instead when the check only proves the current
implementation, migration, seed state, file layout, or one-time acceptance:

- run existing or targeted tests;
- exercise the relevant page or feature;
- run lint, type-check, build, or a focused script;
- inspect the result manually or programmatically and record the evidence in the PR or acceptance notes.

Reject a new permanent test when it only:

- asserts that a deleted button or renamed internal symbol is absent;
- asserts a helper name, module path, file location, or component filename;
- proves that code moved or was mechanically refactored;
- fixes a temporary seed count or one-time migration state;
- exists only to raise coverage or satisfy “every PR must add a test”.

An absence test is still appropriate when absence is the durable contract, for
example a user without permission must not see or invoke a protected action.
Test the permission behavior, not an incidental DOM selector, whenever the
contract can be expressed more directly.

## Concrete cases

| Change | Permanent test | Temporary verification |
| --- | --- | --- |
| Delete a low-risk button | None for DOM absence | Open the page; run existing tests, lint, type-check, and build |
| Fix API authorization | Unauthorized request is rejected and an authorized request still succeeds | Check helper names, seed records, and one-time migration output |
| Move and rename a Vue component | Preserve its existing user-visible behavior; test a public import only if that import is a contract | Check references, old/new paths, lint, type-check, build, and existing tests |

## For Discussion, Design, and Plan

When a test suite is proposed, record the classification for each non-trivial
test group:

1. The durable behavior or invariant it protects.
2. The future regression it is expected to catch.
   For new tests, explain what existing coverage would miss.
3. Any one-time checks that stay out of the permanent suite and how they will be verified.

Do not turn an acceptance checklist, fixed record count, exact model name, or
implementation layout into a permanent test unless it is an explicitly
approved product or public contract.

## For Pull Request review

Review added and modified tests as part of the PR's scope, not as a coverage
score. For each test, verify that its assertion targets behavior rather than
the implementation used to produce it. Report a finding only when the test
creates a concrete maintenance or false-failure risk, locks temporary state,
or violates the approved Issue, Design, or Plan. Otherwise, request temporary
verification or leave the test unflagged.

## Common rationalizations

| Excuse | Correct response |
| --- | --- |
| “The PR must contain a new test.” | Existing tests and targeted verification are valid evidence; do not create a meaningless test. |
| “The change is different, so it needs a test.” | First identify the durable behavior that could regress. A mechanical change may need only existing tests and build checks. |
| “More coverage is always better.” | Coverage is a signal, not a reason to preserve implementation details or temporary state. |
| “The test documents what this PR did.” | Record one-time implementation evidence in the PR or acceptance notes; permanent tests document behavior. |

## Red flags

Stop and re-evaluate when the proposed assertion mentions only:

- a current filename, helper name, module path, or seed count;
- a deleted or renamed element with no durable policy behind it;
- “coverage”, “test count”, or “every PR” as its justification;
- the fact that the current branch changed something.

If no future regression can be named, do not commit the test.
