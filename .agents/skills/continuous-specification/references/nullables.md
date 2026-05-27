# Nullable Infrastructure Wrappers

Nullable infrastructure wrappers isolate specifications from external dependencies (HTTP, files, databases, clocks, random numbers) without mocking frameworks.

The `nullables` skill provides the full pattern. Load it when writing specifications that involve infrastructure dependencies.

## Core idea

Wrap infrastructure behind an interface. Provide a real implementation and a Null implementation. The Null implementation returns configurable, predictable values — no mock framework needed.

## Anti-patterns to avoid

- Never use `mock()`, `stub()`, `spy()`, or `patch()` in specifications.
- Never verify that a method was called — specify the observable outcome instead.
- Never reach into implementation details to satisfy a specification.
