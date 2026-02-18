# Nathan's Python Coding Preferences

> Reference guide for Claude when writing Python code for this user

---

## Core Philosophy

- **Clarity beats cleverness.** Favor explicit, readable code over compact one-liners or metaprogramming tricks.
- **NO TYPE HINTS in function signatures.** Communicate types through docstrings and comments instead.
- **Annotate aggressively.** Every non-trivial block should include short, purposeful comments so someone skimming the file can follow the logic without running it.
- **Consistent documentation.** All modules, classes, and functions use Sphinx-style docstrings.
- **Single source of truth.** Document expected inputs/outputs immediately above the implementation.

---

## File Structure

1. **Module docstring**
   - First line: concise summary.
   - Follow with any required context (dependencies, environment variables, known gotchas).

2. **Imports**
   - Group: stdlib → third-party → local packages.
   - One import per line; avoid `from module import *`.

3. **Constants**
   - Uppercase, documented with inline comments.
   - Centralize hard-coded paths or environment variable names.

4. **Functions & Classes**
   - **NO type hints in definitions.**
   - Each has a Sphinx-style docstring (`:param type name:` / `:return:` / `:rtype:`).
   - Add leading comments before complex control flow.

5. **Script guard** (`if __name__ == "__main__":`) for runnable modules; include commentary on expected usage.

---

## Docstring Standards (Sphinx-Style)

- Document **every parameter**, even when obvious.
- For functions returning multiple structures, spell out the schema and mention ordering or sorting guarantees.
- When omitting type hints in signatures, keep docstring types precise (e.g. `:param str name:` not `:param name:`).
- Top-level module docstring should enumerate:
  - Dependencies (if any external packages required)
  - Side effects (files written, environment changes)
  - Environmental flags or configuration

**Example:**
```python
def process_data(data, threshold):
    """
    Process incoming data and filter by threshold.

    :param list data: List of numeric values to process
    :param float threshold: Minimum value to include in results
    :return: Filtered and sorted data
    :rtype: list
    """
    # Filter out values below threshold to meet requirements.
    filtered = [x for x in data if x >= threshold]

    # Sort in descending order for downstream consumers.
    filtered.sort(reverse=True)

    return filtered
```

---

## Commenting Guidelines

### Pre-Block Comments
Use full sentences describing **WHY** you are doing something, not only what.

```python
# Force reload so changes are picked up during development sessions.
reload(helper_module)
```

### Inline Comments
Reserve for clarifying magic numbers or non-obvious expressions.

```python
timeout_secs = 5  # Matches network retry window.
```

### Section Headers
Help with scanning in long files:

```python
# --- Data Processing -----------------------------------------------

# --- Utility Functions ---------------------------------------------
```

---

## Style Guidelines

- **Indentation:** 4 spaces (no tabs)
- **Line length:** 120-character soft limit
- **Formatting:** Respect existing formatting in the file
- Use meaningful variable names; avoid single-letter variables except in obvious contexts (loop counters, coordinates)

---

## Error Handling & Logging

- Use standard `logging` module for consistent output
- Log at appropriate levels: DEBUG for details, INFO for milestones, WARNING/ERROR for issues
- Wrap risky operations with try/except to report meaningful messages
- When raising exceptions, prefer custom message strings with context

---

## Quick Checklist

- [ ] Module docstring and header comments present
- [ ] All functions/classes documented (Sphinx style, **no signature type hints**)
- [ ] Comments explain intent throughout the script
- [ ] Constants are uppercase with inline documentation
- [ ] Logging statements exist around major actions
- [ ] Imports grouped properly (stdlib → third-party → local)

---

## Remote Access & Deployment

> **Full documentation:** See `Docs/REMOTE_ACCESS_GUIDE.md` for complete details on all machines, SSH keys, VPN access, and troubleshooting.

---

**Remember:** Nathan likes a lot of notes throughout the code. When in doubt, add more explanatory comments!

---

## Workflow Preferences

- **Run code yourself.** Don't ask Nathan to run commands, API calls, or rebuilds that you can execute on your own.
- **Be proactive.** If something needs to be done (like rebuilding embeddings, running migrations, testing), just do it.
- **Only ask when necessary.** Reserve questions for decisions that genuinely require Nathan's input.

---

### Pushing Live
- When Nathan says "Push live":
  - Push all changes to Github.
  - Push and deploy all changes to the Mini PC and make sure the website is working.
  - Nathan Tests everything on the live website.
  - The frontend on the Mini PC should be rebuilt.

### Session Checklist
- [ ] At the beginning of each session, read the recent session notes in `Docs/SessionNotes/`
- [ ] Read `Docs/REMOTE_ACCESS_GUIDE.md` for SSH/network access to all machines
- [ ] Update Session notes throughout the session: `Docs/SessionNotes/`
- [ ] Update rebuild guides if infrastructure changes:
  - `Docs/Repro/REBUILD_GUIDE.md`