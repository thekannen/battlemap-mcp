---
name: battlemap-lighting-hierarchy
description: Use when a Dungeondraft brief needs atmosphere, a readable route, focused illumination, or intentional darkness.
---

# Dungeondraft lighting hierarchy

Light is a compositional signal, and darkness is half of it. Decide the global
condition first, then place sources that earn their place against it.

## Set the global condition first

Set the ambient light with `set_ambient_light` before placing any source. Start
close to neutral when the scene's colour should come from local sources rather
than tinting the whole map. Ambient can also restate the time of day without
rebuilding the geometry, so treat it as a global condition rather than a change
to every asset.

Tint ambient when the brief calls for a pervasive condition — moonlight, fog, a
strange sky — and expect to compensate in the sources.

## Make lighting choices intentional

Treat a departure from these as a decision you should be able to justify:

- **Shadows on.** A source that casts no shadow reads as a glow, not a light.
- **Intensity at its default.** Distance and range do the shaping. Reach for
  stacked sources in one spot before an unusual intensity when you want a hot
  centre.
- **Range scoped to the room, not the map.** A source lights what it stands in.
- **A limited palette.** Keep light colours few enough that a threshold or a
  special condition remains distinct.

## Make warm and cool light communicate

Use warm and cool light to distinguish conditions when the brief calls for it:
for example, warm local light can contrast with moonlight, magic, ice, or water.
A scene lit entirely in cool colour should be an intentional answer to the
brief.

## Every light needs a source the viewer can point at

A light has a job *and* a cause, and the rules below only cover the job. Before
placing one, name what is emitting it — then place the object that emits it.
Candle, hearth fire, lantern, brazier, forge, torch, a window with light behind
it, a magical portal, a glowing rune. A pool of warm light on bare ground with
nothing above it does not read as atmosphere; it reads as a mistake, and it is
the kind a viewer notices immediately even when they cannot say why.

This cuts both ways. An emitter placed with no light is just as wrong: an unlit
lantern hanging by a door, or a hearth full of fire throwing nothing into the
room, tells the viewer the scene is a diagram. Fire in a hearth and light from
that hearth are one decision, made together.

**Outdoors the global condition is itself the source, so decide it.** Daylight,
overcast, dusk, moonlight — that choice sets what the open ground already has
and therefore what a local source is allowed to add. Under full daylight,
scattered warm pools along a road are unexplainable; at night the same road
wants the light to come from lantern posts, lit windows, a watchfire — things
that are in the scene. An exterior that is dark everywhere except where a
source stands is correct at night and wrong at noon.

So when a region reads as flat or lifeless, the fix is rarely another bare
light. It is usually the missing global condition, or a source object that was
never placed.

## Place by role, and protect the darkness

Name the job of each `add_light` before placing it:

| Role | Job |
| --- | --- |
| Focal event | The encounter's central action, reward, hazard or clue. |
| Threshold | A meaningful change of state: outside to inside, safe to dangerous. |
| Route cue | An entrance, a safe passage, or the next decision. |
| Local reveal | Makes an interactable feature readable without taking over its area. |

1. Place the focal event's light, then check it still wins at whole-map scale.
2. Add thresholds and route cues only where a player must notice a transition or
   choose a direction. Evenly spaced sources along a corridor read as
   infrastructure and flatten the hierarchy.
3. Add a local reveal only when it explains interaction, cover or danger.

Leave the space between roles dark. Contrast is what makes a lit area mean
something — and where the surroundings are lit, a focal point can be made by
*withholding* light instead of adding it.

## Verify the hierarchy

Call `get_composition_snapshot`, then review a whole-map `export_map` and a
focused `screenshot` of the focal event. The snapshot is an inventory aid, not a
brightness measurement — only the render answers whether the hierarchy reads.

If a source competes with the focal event, erases a useful shadow, or makes the
scene look evenly illuminated, `undo` it before adding another. Finish with the
[composition audit](../battlemap-composition-audit/SKILL.md) once the
hierarchy holds at both scales.
