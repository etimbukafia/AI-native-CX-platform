# Instructions

These instructions capture the project decisions and constraints that matter when working in this repository.

## Writing

Always talk in ASD-STE100 Issue 9 Simplified Technical English.

### Key rules

- Use approved words only. The standard gives a word list. Each word has one meaning.
- Use one word for one idea. Do not use two words for the same thing.
- Write short sentences. Use 20 words or less for instructions.
- Use active voice.
- Write short paragraphs. Keep one topic in each paragraph.

The goal of writing is easy reading and communication of information.

## Architecture Rules

- Do not blindly write code. Research current documentation when an external contract is unclear.
- Use modular architecture with separation of concerns.
- Code should be easy to explain.
- Prefer clear names, small functions, explicit data flow, and straightforward control flow.
- Add abstractions only when they clarify real boundaries or reduce meaningful complexity.
- Prefer efficient implementation over quick hacks.
- Keep the code modular and testable.
- Keep code explainable from API request through service, adapter, external call, and persistence.
- Do not preserve backward compatibility during this build.
- Avoid technical debt, bloat, code smell, stopgap solutions, and poor long-term architecture decisions.
- Prefer the simplest implementation that fully meets requirements.
- Avoid speculative abstractions, configuration, and indirection.
- Keep external dependencies behind adapters.
- Use typed models at system boundaries.
- Work only within the requested phase or phase batch.
- When there is a meaningful implementation choice, pause and ask first.

## Testing

- Do not over-test. Each test must protect a user outcome, security boundary, data-integrity rule, external contract, or cost rule.
- Test behavior through a public boundary. Prefer API, database, provider, adapter, and UI behavior over private helpers.
- Do not read source files from tests.
- Do not assert module inventories, import text, private attributes, object wiring, or arbitrary implementation constants.
- Assert a provider or tool call count only when deduplication protects a user, reliability, or cost rule.
- Remove a test when a stronger user-facing or integration test covers the same behavior.
- A source refactor should not require test changes when behavior stays the same.
- Use small test data and deterministic control flow.
- Do not add stress tests unless they protect a measured limit or safety boundary.
- Every test name must state the behavior it protects.
- Delete tests that cannot justify their presence.
- A passing test count does not justify a test.
- Prefer one current forward-only schema baseline over a long chain of disposable migrations.
