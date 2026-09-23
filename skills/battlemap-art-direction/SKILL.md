---
name: battlemap-art-direction
description: Use when translating a Dungeondraft map brief into a deliberate visual plan before building or reviewing an environment, interior, or mixed scene.
---

# Dungeondraft art direction

Turn the brief into a map the players can read at a glance. Composition comes
before decoration: intentional zones, a clear route, a focal event and a
controlled density gradient make later detail feel designed rather than piled
on.

## Plan before placement

1. Call `ping` and `get_status`. If the bridge or a map is unavailable, stop.
2. Complete the [style bible](../_shared/style-bible.md) with the user’s brief.
   When a materially different visual direction is plausible, ask the user to
   choose before proceeding.
   Record: Use, Focal event, Primary and secondary zones, Route, Route states,
   Palette and mood, Density gradient, Coverage and emphasis, Playability,
   Asset searches and Completion checks. State whether each planned route is
   open, blocked or gated before choosing assets.
3. Choose environment, interior, or both. Preserve empty space around the
   focal event and along the primary route.
4. Set a [material language](../battlemap-material-language/SKILL.md) and
   [lighting hierarchy](../battlemap-lighting-hierarchy/SKILL.md), then use
   `list_assets` for its material families. Use only returned assets; refine
   the search rather than assuming an installed pack.

Do not place anything until the plan is coherent.

**Load the placing skill before placing anything.** This skill plans; it does
not carry the placement rules. Before the first object goes down, load
[interiors](../battlemap-interiors/SKILL.md) for rooms and
[environments](../battlemap-environments/SKILL.md) for ground and
exteriors — both, for a building with a site. The two rules that matter most
from the first call:

- **Vary what is not a fixture.** Keep beds, shelf runs and counters squared to
  their walls; give everything else a scale of about 0.85-1.15 and a few degrees
  off the quarter turns. If a placement result carries an `arrangement_note`,
  fix that batch before placing more.
- **Size the map to the scene** before laying out, or plan surroundings out to
  its edges.

## Build and finish

Follow the shared [build loop](../_shared/build-loop.md). Use the environment
or interior composition skill for the relevant zone, then run the
[composition audit](../battlemap-composition-audit/SKILL.md) before invoking
visual review and declaring the map complete.

At every checkpoint, compare the rendered view with the style bible: the
focal event should be first to read, secondary zones should support it, and
routes must stay playable at token scale. Verify that broad coverage reaches
the intended play space while emphasis remains concentrated in the planned
dominant zones. Call `save_map` at each checkpoint
and capture a `screenshot` before each finish decision. If remaining work is a UI-only
micro-adjustment, hand it back to the user instead of churning the map.
