---
name: code-cleanup
description: >-
  Apply targeted, behavior-preserving cleanups to code — rename cryptic or two-letter variable
  names into intent-revealing ones, remove duplication (DRY it up), and trim needless verbosity.
  Use whenever the user wants to clean up, tidy, or simplify messy code for readability, asks to
  fix unclear or short variable names (like `co`, `io`, `rt`), wants repeated code de-duplicated,
  or says something is too verbose / hard to follow. Trigger on phrases like "clean this up",
  "make this more readable", "this is too verbose", "DRY this up", "these variable names are
  terrible", "what does `co` even mean", or "tidy up this function" — even when the skill isn't
  named. This refactors in place; it does not add features or change what the code does.
---

# Code Cleanup

Make code easier to read without changing what it does. Three things drag readability down, and
this skill goes after all three in one pass: cryptic names, copy-paste duplication, and needless
verbosity.

The principles here are language-agnostic; examples are in Python because that's this repo's
stack, but apply the same judgment to any language.

## Scope: stay surgical

Clean up **the code in question** — the file or selection the user pointed at, or the most
recently edited code if they didn't name one. Don't sweep across the whole repo reformatting
things nobody asked about. The goal is a focused, reviewable diff, not churn.

Leave already-clear code alone. If a function is fine, say so and move on. A cleanup that touches
everything is as hard to review as the mess it replaced.

## Pass 1 — Names that explain themselves

Rename cryptic, abbreviated, or two-letter names into ones that say what they hold:

```
co  → company          io → input_offset       rt  → retry_count
res → response (or result, depending on what it is)
tmp → parsed_rows      d  → delay_seconds       val → discount_rate
```

A good name lets a reader skip the definition. `retry_count` needs no comment; `rt` does.

**But short names are not automatically bad — keep the ones that are genuinely conventional.**
Renaming these usually hurts readability instead of helping:

- Loop indices: `i`, `j`, `k`
- The caught exception: `except ValueError as e`
- Intentional throwaway: `for _ in range(n)`, `_, value = pair`
- Established domain idioms: `df` (DataFrame), `f` (open file handle), `x`/`y` (coordinates),
  `n` (a count in a tight numeric loop), `ax` (matplotlib axis)
- Single letters inside a short comprehension or lambda where the scope is one line

The test is **clarity in context, not length.** `n` in a three-line math loop is clear; `n`
holding a customer's full mailing address is not. Rename for understanding, not to satisfy a
character-count rule. When a short name is locally obvious, leave it.

When you do rename, change **every** use site, plus any docstring or comment that mentions the
old name. A half-renamed variable is worse than the original.

## Pass 2 — DRY up real repetition

When the same logic appears 2–3+ times, pull it into one place: a helper function, a constant, a
loop over data, or a shared object.

```python
# Before — same shape three times
user_total = price_a * 1.08 + shipping_a
guest_total = price_b * 1.08 + shipping_b
vip_total   = price_c * 1.08 + shipping_c

# After
TAX_RATE = 1.08
def order_total(price, shipping):
    return price * TAX_RATE + shipping
```

**Don't over-abstract.** Duplication is cheaper than the wrong abstraction:

- Merge code only if the pieces would genuinely have to **change together for the same reason.**
  Things that look alike today but evolve independently should stay separate.
- The extracted helper should be **simpler** than the duplication it removes. If you need five
  flags and three branches to unify two blocks, leave them as two blocks.
- Two occurrences is a judgment call; coincidental similarity is not duplication.

## Pass 3 — Trim verbosity

Replace boilerplate with the language's plain idioms — without turning it into clever code golf.

```python
# Guard clause beats nested ifs
if user is None:
    return None
return user.name                      # not: if user is not None: if ...: return ...

# Comprehension beats manual accumulation
names = [u.name for u in users if u.active]

# Truthiness beats comparison to True/False/len
if items:                             # not: if len(items) > 0 == True
```

Also: delete dead code and commented-out blocks, drop comments that just restate the code, and
collapse redundant temporary variables. Stop when the code is *clear* — match the surrounding
style, and don't compress it into something cleverer than the reader can follow.

> For comment-specific cleanup — shortening long comments, cutting jargon, keeping them to one line
> where possible — use the `clean-comments` skill.

## Guardrails — this is a refactor, not a rewrite

- **Preserve observable behavior.** Same inputs → same outputs and side effects. If you're
  tempted to fix a bug or add a feature, that's a separate change — flag it, don't fold it in.
- **Don't rename public/exported API** (function names, exported symbols, config keys) without
  calling it out first — callers you can't see may depend on it.
- **Respect repo conventions.** In this project that means: keep Pydantic models for agent/tool
  I/O (schemas on models, behavior in prompts), never hardcode an AWS region (read
  `os.environ["AWS_REGION"]`), and keep macros/nutrition computed in code — report only what a
  tool actually returned, never fabricate a value. Match the existing style.
- **Verify before claiming done.** If there are tests or a runnable entrypoint, run them after
  and report the result (this repo runs the notebook via `uv run --with nbconvert`). If not,
  re-read your own diff to confirm the logic is unchanged. State plainly what you verified and what
  you didn't — don't assert "behavior preserved" on faith.
- **Summarize the changes** in a few lines: what you renamed, what you extracted, what you
  trimmed, and anything you deliberately left alone.

## Worked example

**Before** — cryptic names, a duplicated block, and a verbose loop:

```python
def proc(co, io):
    res = []
    for i in range(len(co)):
        if co[i]["active"] == True:
            n = co[i]["name"].strip().lower()
            res.append(n)
    for i in range(len(io)):
        if io[i]["active"] == True:
            n = io[i]["name"].strip().lower()
            res.append(n)
    return res
```

**After:**

```python
def active_names(*record_groups):
    def normalize(record):
        return record["name"].strip().lower()

    return [
        normalize(record)
        for group in record_groups
        for record in group
        if record["active"]
    ]
```

**Summary of changes:**
- Renamed `proc`→`active_names`, `co`/`io`→a `*record_groups` varargs, `res`→the return list,
  `n`→`normalize()` (kept loop-local `record`/`group` as clear names).
- DRY'd the two identical loops into one comprehension over all groups.
- Trimmed verbosity: `== True` → truthiness, index loops → direct iteration.
- Behavior preserved: still returns the lowercased, stripped names of every active record, in
  the same order.
