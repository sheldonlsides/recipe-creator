---
name: clean-comments
description: >-
  Keep code comments short, plain, and useful — one line by default, multiple lines only when the
  logic genuinely needs them, and worded in simple language instead of dense jargon. Use whenever
  you write or edit comments, or when the user asks to "clean up the comments", "add comments",
  says the comments are "too long", "too wordy", "too technical", "hard to follow", or "explain in
  plain English". Trigger on "comment this", "simplify these comments", "these comments are
  overkill", or any task that adds or rewrites comments — even when the skill isn't named. This is
  language-agnostic; it changes comments only, never the code's behavior.
---

# Clean Comments

Good comments help the next reader understand the code quickly. Bad comments are long, repeat what
the code already says, or bury a simple idea in jargon. This skill keeps comments tight and clear.

The rules are language-agnostic — examples use Python (`#`) and JavaScript (`//`), but apply the
same judgment to any language.

## Rule 1 — One line by default

Most comments fit on a single line. Write that one line and move on. If you find yourself starting
a multi-line block, first ask whether one plain sentence would do.

```python
# Good — says the why in one line
retries = 3  # give the flaky API a couple of extra tries

# Overkill — three lines for an idea that fits in one
# We set the number of retries here.
# This is because the API can sometimes fail.
# So we try again a few times.
retries = 3
```

## Rule 2 — Multiple lines only when needed

Reserve longer comments for the cases that truly earn them:

- A genuinely tricky algorithm or a non-obvious sequence of steps.
- A "why" that needs real context — a workaround, an edge case, a business rule, a gotcha.
- Structured doc blocks that the language or tooling expects (docstrings, JSDoc, etc.). These are
  the legitimate exception to the one-line rule — follow the doc style, but still keep each line
  plain.

If a block comment is just several lines each restating one line of code, collapse it.

```python
# Fair use of multiple lines — explains a non-obvious decision
# Portions are scaled by gram weight, not serving count, because the
# nutrition store reports everything per 100g. Scaling by servings
# would double-count when a recipe lists the same food twice.
grams = base_grams * scale
```

## Rule 3 — Plain language, not jargon

Write so a teammate who doesn't know this corner of the code can follow it. Prefer everyday words.
Spell out an acronym the first time, or skip it. Drop filler.

```javascript
// Jargon-heavy — hard to parse
// Memoize the idempotent resolver to elide redundant IO round-trips.

// Plain — same meaning
// Cache the lookup so we don't hit the network twice for the same value.
```

## Comment the "why", not the obvious "what"

The code already shows *what* it does. A comment earns its place by explaining *why*, or by
flagging something surprising. Delete comments that just narrate the line beneath them — that
overlaps with the `code-cleanup` skill's verbosity pass.

```python
# Useless — restates the code
count += 1  # add one to count

# Useful — explains intent
count += 1  # one more failed attempt before we back off
```

## Guardrails

- **Only touch comments.** Editing or removing comments must not change what the code does.
- **Keep comments truthful.** If you simplify a comment, make sure it still matches the code. A
  short wrong comment is worse than a long right one.
- **Match the surrounding style.** Use the file's existing comment marker and tone; don't convert a
  whole file's style on a whim.
- **Don't strip required doc blocks.** Public docstrings / API doc comments stay — just keep them
  plain.
