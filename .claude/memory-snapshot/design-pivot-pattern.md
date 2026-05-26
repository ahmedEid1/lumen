---
name: design-pivot-pattern
description: "How the user approaches mid-flight design direction changes on the Lumen/Skillpath repo, and what to recover when they do"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 570ed99c-48b3-471c-a2d9-c72712d55445
---

This project has reversed a major design direction mid-flow at least once: 35-iter Thoth (Egyptian temple) pass → fully discarded → new Skillpath (Apple-grade modern e-learning) brand. Treat any chosen theme as removable, not load-bearing.

**Why:** the user iterates on visual identity by trying a complete pass and then deciding to abandon if it doesn't feel right. The 80+ commits of prior work are not wasted — the i18n extraction, server/client split, ui-primitive gold defaults, glyph asset infrastructure can all be repurposed. Visual tokens (palette, fonts, primitives) are the disposable layer.

**How to apply:**
- Don't get attached to themes; the visual language is the most likely thing to get pivoted.
- When pivoting, keep: i18n keys + structure, server/client splits, ui-primitive contracts (Button, Card, Input variants), test setup, Lumen primitive *files* (Cartouche, Glyph, EyeDivider, PapyrusBg, Torchlight) since deleting them would touch every consumer. Re-skin via new tokens instead.
- Discard: theme-specific copy (cartouche eyebrows, "library of Thoth", deity names), theme-specific assets (Wikimedia hieroglyph SVGs can stay in public/ for now; ignored if not referenced), font choices (Fraunces+Lora → whatever the new direction wants).
- Name pivots happen too: prefers descriptive over abstract (Skillpath > Lume), 1-2 syllables, immediately readable as the platform type.
