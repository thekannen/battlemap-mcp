"""Contract tests for portable Dungeondraft map-aesthetics skills."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CHECKER = Path(__file__).resolve().parents[2] / "tools" / "check_skills.py"
REPOSITORY_ROOT = CHECKER.parents[1]


def run_checker(root: Path) -> subprocess.CompletedProcess[str]:
    """Run the repository skill linter against an isolated skill tree."""
    return subprocess.run(
        [sys.executable, str(CHECKER), str(root)],
        check=False,
        capture_output=True,
        text=True,
    )


def write_index(root: Path, skills: list[dict[str, object]]) -> None:
    directory = root / "skills"
    directory.mkdir(parents=True)
    directory.joinpath("skill-index.json").write_text(json.dumps({"schema": 1, "skills": skills}))


def skill_entry(name: str, path: str) -> dict[str, object]:
    return {
        "name": name,
        "path": path,
        "triggers": ["map request"],
        "requires": [],
        "minimum_protocol": 22,
    }


def write_skill(root: Path, relative_path: str, body: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def test_checker_accepts_an_empty_skill_index(tmp_path):
    """A repository can introduce the format before publishing a skill."""
    write_index(tmp_path, [])

    result = run_checker(tmp_path)

    assert result.returncode == 0
    assert result.stdout == ""


def test_checker_reports_missing_frontmatter_name(tmp_path):
    """Every indexed skill needs a discoverable frontmatter name."""
    path = "skills/battlemap-art-direction/SKILL.md"
    write_index(tmp_path, [skill_entry("battlemap-art-direction", path)])
    write_skill(tmp_path, path, "---\ndescription: Use when composing a map\n---\nping\n")

    result = run_checker(tmp_path)

    assert result.returncode == 1
    assert "missing frontmatter name" in result.stdout


def test_checker_reports_an_index_path_that_does_not_exist(tmp_path):
    """The index cannot silently point agents to a missing skill."""
    write_index(tmp_path, [skill_entry("battlemap-art-direction", "skills/missing/SKILL.md")])

    result = run_checker(tmp_path)

    assert result.returncode == 1
    assert "indexed skill path does not exist" in result.stdout


def test_checker_reports_missing_relative_references(tmp_path):
    """Shared workflow guidance must resolve inside the repository tree."""
    path = "skills/battlemap-art-direction/SKILL.md"
    write_index(tmp_path, [skill_entry("battlemap-art-direction", path)])
    write_skill(
        tmp_path,
        path,
        "---\nname: battlemap-art-direction\ndescription: Use when composing a map\n---\n"
        "ping get_status list_assets save_map screenshot\n[missing](../_shared/nope.md)\n",
    )

    result = run_checker(tmp_path)

    assert result.returncode == 1
    assert "relative reference does not exist" in result.stdout


def test_checker_requires_discovery_and_visual_review_for_creation_skills(tmp_path):
    """Creation guidance cannot tell an agent to build without asset discovery."""
    path = "skills/battlemap-art-direction/SKILL.md"
    write_index(tmp_path, [skill_entry("battlemap-art-direction", path)])
    write_skill(
        tmp_path,
        path,
        "---\nname: battlemap-art-direction\ndescription: Use when composing a map\n---\n"
        "ping get_status save_map screenshot\n",
    )

    result = run_checker(tmp_path)

    assert result.returncode == 1
    assert "missing required token: list_assets" in result.stdout


def test_checker_rejects_forbidden_blind_building_language(tmp_path):
    """The skills must not normalize guessed assets or unreviewed construction."""
    path = "skills/battlemap-art-direction/SKILL.md"
    write_index(tmp_path, [skill_entry("battlemap-art-direction", path)])
    write_skill(
        tmp_path,
        path,
        "---\nname: battlemap-art-direction\ndescription: Use when composing a map\n---\n"
        "ping get_status list_assets save_map screenshot\nNever guess an asset path.\n",
    )

    result = run_checker(tmp_path)

    assert result.returncode == 1
    assert "forbidden phrase: guess an asset path" in result.stdout


def test_art_direction_skill_has_a_coherent_visual_plan_contract():
    """The entry skill must require planning, discovery and screenshot review."""
    skill = REPOSITORY_ROOT / "skills" / "battlemap-art-direction" / "SKILL.md"

    text = skill.read_text()

    assert "../_shared/build-loop.md" in text
    assert "../_shared/style-bible.md" in text
    for field in (
        "Use",
        "Focal event",
        "Primary and secondary zones",
        "Route",
        "Palette and mood",
        "Density gradient",
        "Playability",
        "Asset searches",
        "Completion checks",
    ):
        assert field in text
    assert "list_assets" in text
    assert "screenshot" in text
    assert "Do not place anything until the plan is coherent." in text


def test_environment_skill_teaches_composition_without_a_fixed_clutter_quota():
    """Outdoor guidance must use relationships and visual checks, not object counts."""
    skill = REPOSITORY_ROOT / "skills" / "battlemap-environments" / "SKILL.md"

    text = skill.read_text()

    for requirement in (
        "terrain layering",
        "transition band",
        "silhouette",
        "route",
        "water",
        "negative space",
        "list_assets",
        "paint_terrain",
        "get_terrain",
        "export_map",
    ):
        assert requirement in text
    assert "fixed clutter target" not in text


def test_interior_skill_centers_room_purpose_and_playable_circulation():
    """Indoor guidance must build a room hierarchy instead of uniform dressing."""
    skill = REPOSITORY_ROOT / "skills" / "battlemap-interiors" / "SKILL.md"

    text = skill.read_text()

    for requirement in (
        "room purpose",
        "circulation",
        "focal point",
        "furniture cluster",
        "edge treatment",
        "visible cause",
        "add_light",
        "save_map",
    ):
        assert requirement in text
    assert "res://" not in text


def test_visual_review_skill_requires_observable_repair_evidence():
    """Review guidance must bound repairs and capture the result at two scales."""
    skill = REPOSITORY_ROOT / "skills" / "battlemap-visual-review" / "SKILL.md"
    rubric = REPOSITORY_ROOT / "skills" / "_shared" / "review-rubric.md"

    text = skill.read_text()
    rubric_text = rubric.read_text()

    assert "../_shared/review-rubric.md" in text
    for requirement in ("export_map", "focused screenshot", "at most three", "undo", "finish"):
        assert requirement in text
    for dimension in ("Brief fit", "Composition", "Material depth", "Believability", "Playability"):
        assert dimension in rubric_text
    assert "universal numeric threshold" not in rubric_text


def test_composition_audit_skill_requires_two_scale_evidence_and_bounded_repairs():
    """A final polish pass must compare observable map views, not add uniform detail."""
    skill = REPOSITORY_ROOT / "skills" / "battlemap-composition-audit" / "SKILL.md"

    text = skill.read_text()

    for requirement in (
        "get_composition_snapshot",
        "fit_elements",
        "export_map",
        "encounter-scale",
        "screenshot",
        "route",
        "density contrast",
        "at most three",
        "undo",
        "same view",
    ):
        assert requirement in text
    assert "uniform detail" not in text
    assert "universal numeric threshold" not in text
    assert "not a score" in text


def test_material_language_skill_turns_a_brief_into_a_bounded_visual_system():
    """A coherent map needs intentional reuse, not an unbounded asset collage."""
    skill = REPOSITORY_ROOT / "skills" / "battlemap-material-language" / "SKILL.md"

    text = skill.read_text()

    for requirement in (
        "material vocabulary",
        "structural family",
        "supporting family",
        "accent family",
        "threshold",
        "focal event",
        "list_assets",
        "get_composition_snapshot",
        "export_map",
        "screenshot",
    ):
        assert requirement in text
    assert "fixed asset count" not in text
    assert "every open area" not in text


def test_lighting_hierarchy_skill_treats_darkness_as_a_compositional_choice():
    """Atmosphere needs focused contrast, not uniform illumination."""
    skill = REPOSITORY_ROOT / "skills" / "battlemap-lighting-hierarchy" / "SKILL.md"

    text = skill.read_text()

    for requirement in (
        "ambient light",
        "darkness",
        "focal event",
        "threshold",
        "add_light",
        "set_ambient_light",
        "get_composition_snapshot",
        "export_map",
        "screenshot",
        "undo",
    ):
        assert requirement in text
    assert "regular intervals" not in text
    assert "every room" not in text


def test_skills_require_coverage_hierarchy_semantics_and_scale_passes():
    """Composition guidance must make distribution and VTT semantics reviewable."""
    style_bible = REPOSITORY_ROOT / "skills" / "_shared" / "style-bible.md"
    build_loop = REPOSITORY_ROOT / "skills" / "_shared" / "build-loop.md"
    art_direction = REPOSITORY_ROOT / "skills" / "battlemap-art-direction" / "SKILL.md"
    environments = REPOSITORY_ROOT / "skills" / "battlemap-environments" / "SKILL.md"
    interiors = REPOSITORY_ROOT / "skills" / "battlemap-interiors" / "SKILL.md"
    visual_review = REPOSITORY_ROOT / "skills" / "battlemap-visual-review" / "SKILL.md"
    composition_audit = REPOSITORY_ROOT / "skills" / "battlemap-composition-audit" / "SKILL.md"
    material_language = REPOSITORY_ROOT / "skills" / "battlemap-material-language" / "SKILL.md"
    lighting_hierarchy = REPOSITORY_ROOT / "skills" / "battlemap-lighting-hierarchy" / "SKILL.md"

    style_text = style_bible.read_text()
    assert "Coverage and emphasis" in style_text
    assert "Route states" in style_text
    # the build loop crafts region by region, so the plan has to name the regions
    assert "Region plan" in style_text
    for requirement in (
        "material language",
        "lighting hierarchy",
        # phase spine: foundation globally, then one region at a time
        "Lay the foundation",
        "Assign region emphasis",
        "one at a time",
        "screenshot",
    ):
        assert requirement in build_loop.read_text()
    assert build_loop.read_text().count("screenshot") >= 3
    assert "Coverage and emphasis" in art_direction.read_text()
    assert "open, blocked or gated" in art_direction.read_text()
    assert "barriers, openings and lights" in environments.read_text()
    assert "../_shared/build-loop.md" in environments.read_text()
    assert "doors, barriers and lights" in interiors.read_text()
    assert "../_shared/build-loop.md" in interiors.read_text()
    for skill in (art_direction, environments, interiors, visual_review):
        assert "battlemap-composition-audit" in skill.read_text()
    for skill in (art_direction, environments, interiors):
        assert "battlemap-material-language" in skill.read_text()
        assert "battlemap-lighting-hierarchy" in skill.read_text()
    assert "battlemap-composition-audit" in composition_audit.read_text()
    assert "material vocabulary" in material_language.read_text()
    assert "ambient light" in lighting_hierarchy.read_text()
    for requirement in ("coverage", "barriers", "openings", "lighting"):
        assert requirement in visual_review.read_text()


def test_interior_skill_teaches_layer_order_for_supported_objects():
    """A prop resting on furniture needs a layer above it, chosen at placement."""
    text = (REPOSITORY_ROOT / "skills" / "battlemap-interiors" / "SKILL.md").read_text()

    for requirement in ("place_object", "layer", "as you place it"):
        assert requirement in text
    assert "set_tool_layer" not in text, "obsolete workaround must not be taught"
    lowered = text.lower()
    assert "rest" in lowered or "stack" in lowered
    # sorting reorders within one layer; it is not a substitute for the layer itself
    assert "sorting" in lowered


def test_interior_skill_covers_wall_junction_treatment():
    """Corner and T-junction seams read as an editing artifact unless masked."""
    text = (REPOSITORY_ROOT / "skills" / "battlemap-interiors" / "SKILL.md").read_text()

    lowered = text.lower()
    assert "junction" in lowered
    assert "post" in lowered or "pillar" in lowered or "column" in lowered


def test_material_language_breaks_large_surfaces_without_adding_clutter():
    """A monotonous floor is repaired by material or orientation, not by props.

    The failure this guards is answering "this room looks empty" with more
    objects, which buries circulation while leaving the surface as flat as it
    was.
    """
    text = (REPOSITORY_ROOT / "skills" / "battlemap-material-language" / "SKILL.md").read_text()

    lowered = text.lower()
    assert "orientation" in lowered
    assert "place_pattern" in text
    # names the wrong repair (more objects) as well as the right one (material)
    assert "not with props" in lowered or "rather than adding" in lowered
    assert "scatter objects over it" in lowered


def test_composition_audit_protects_quiet_space_when_detail_is_added():
    """Composition guidance must not treat every unfilled region as a defect."""
    text = (REPOSITORY_ROOT / "skills" / "battlemap-composition-audit" / "SKILL.md").read_text()
    lowered = text.lower()

    assert "quiet space" in lowered or "quiet ground" in lowered
    assert "quiet" in lowered
    assert "scale detail with zones" in lowered
    # the repair for evenly spread decoration is subtraction, not more emphasis
    assert "take detail" in lowered


def test_lighting_skill_orders_ambient_before_sources_and_keeps_a_narrow_palette():
    """Ambient sets the global condition; sources are placed against it."""
    text = (REPOSITORY_ROOT / "skills" / "battlemap-lighting-hierarchy" / "SKILL.md").read_text()
    lowered = text.lower()

    assert "before placing any source" in lowered
    assert "limited palette" in lowered
    assert "withholding" in lowered


def test_skills_do_not_prescribe_a_global_object_shadow_policy():
    """Object shadows must remain a scene-specific style decision."""
    for path in (REPOSITORY_ROOT / "skills").rglob("*.md"):
        lowered = path.read_text().lower()
        for banned in (
            "turn off object shadows",
            "turn object shadows off",
            "disable object shadows",
            "always enable object shadows",
            "always turn on object shadows",
        ):
            assert banned not in lowered, f"{path.name} prescribes an object-shadow policy"


def test_build_loop_sequences_by_region_not_by_feature():
    """Work is finished a region at a time, not swept globally per detail level."""
    text = (REPOSITORY_ROOT / "skills" / "_shared" / "build-loop.md").read_text()
    lowered = text.lower()

    # framing a region is what makes a bounded unit of work verifiable
    for requirement in ("set_camera", "fit_elements", "save_map", "screenshot"):
        assert requirement in text
    assert "one at a time" in lowered or "one region at a time" in lowered
    # the shell stops being editable once dressing starts
    assert "foundation" in lowered
    # generation tools do the layout rather than hand-placing every wall
    assert "generate_dungeon" in text


def test_build_loop_assigns_region_emphasis_before_crafting():
    """Crafting every region to the same finish flattens the map's hierarchy.

    Finished maps concentrate emphasis and leave most of their area quiet, so a
    region-at-a-time order needs a budget assigned up front. Without it, "craft
    each room carefully" produces uniformly busy maps — the same defect the
    composition audit exists to catch, arrived at from the opposite direction.
    """
    text = (REPOSITORY_ROOT / "skills" / "_shared" / "build-loop.md").read_text()
    lowered = text.lower()

    assert "emphasis" in lowered
    for level in ("hero", "supporting", "quiet"):
        assert level in lowered
    # a quiet region is finished when it is sparse, not neglected
    assert "sparse" in lowered or "finished when" in lowered


def test_build_loop_sets_the_ambient_condition_before_regions_are_judged():
    """Regions crafted under one ambient and lit under another were judged wrong.

    Ambient defines the condition every region screenshot is read against, so it
    belongs with the foundation; individual sources still come later.
    """
    text = (REPOSITORY_ROOT / "skills" / "_shared" / "build-loop.md").read_text()

    assert "set_ambient_light" in text
    ambient_at = text.index("set_ambient_light")
    add_light_at = text.index("add_light")
    assert ambient_at < add_light_at, "ambient condition must precede placing sources"


def test_interiors_composes_functional_clusters_around_an_anchor():
    """A zone reads as purposeful when one feature is reinforced, not when props fill a box.

    Placing furniture by picking coordinates inside a region rectangle produces
    "tables in boxes": varied rotations but no relationship between the pieces.
    The fix is to name the zone's anchor, place it first, and position everything
    else relative to it.
    """
    text = (REPOSITORY_ROOT / "skills" / "battlemap-interiors" / "SKILL.md").read_text()
    lowered = text.lower()

    assert "anchor" in lowered
    # the ordering is the rule: anchor, then what supports it, then incidental detail
    anchor_at = lowered.index("anchor")
    assert "supporting" in lowered[anchor_at:]
    # furniture has to relate to the architecture, not float in the middle
    assert "against" in lowered and "wall" in lowered
    assert "freestanding" in lowered


def test_build_loop_designs_circulation_before_furnishing_a_region():
    """Routes are designed first; furniture is placed around them, not vice versa."""
    text = (REPOSITORY_ROOT / "skills" / "_shared" / "build-loop.md").read_text()
    lowered = text.lower()

    assert "circulation" in lowered
    # circulation must be settled before the region-by-region furnishing phases
    assert lowered.index("circulation") < lowered.index("interior rooms, one at a time")
    # a region declares what it is for, not only how much emphasis it gets
    assert "purpose" in lowered


def test_region_emphasis_is_about_prominence_not_object_count():
    """Quiet means low visual competition, which is not the same as nearly empty.

    A storeroom is quiet because it is uniform, unlit and low-contrast — it may
    still be densely packed. Reading "quiet" as "few objects" produces a
    ceremonially sparse storeroom, which is its own kind of wrong.
    """
    text = (REPOSITORY_ROOT / "skills" / "_shared" / "build-loop.md").read_text()
    lowered = text.lower()

    assert "prominence" in lowered or "visual competition" in lowered
    assert "not the same as" in lowered or "does not mean" in lowered


def test_composition_audit_has_two_runnable_semantic_checks():
    """Two falsifiable self-checks, not more taste-based advice.

    One: if every floor were the same material, could the functional areas still
    be told apart? Two: describing each area's use without hedging.
    """
    text = (REPOSITORY_ROOT / "skills" / "battlemap-composition-audit" / "SKILL.md").read_text()
    lowered = text.lower()

    assert "same material" in lowered or "one material" in lowered
    assert "hedge" in lowered or "probably" in lowered


def test_material_language_floor_supports_a_distinction_rather_than_creating_one():
    """A hard floor change with no wall, threshold or level change behind it reads as a diagram."""
    text = (REPOSITORY_ROOT / "skills" / "battlemap-material-language" / "SKILL.md").read_text()
    lowered = text.lower()

    assert "threshold" in lowered
    assert "support" in lowered and "distinction" in lowered


def test_environments_prefers_clusters_over_even_spacing():
    """Evenly spaced single shrubs read as stamped regardless of how few there are."""
    text = (REPOSITORY_ROOT / "skills" / "battlemap-environments" / "SKILL.md").read_text()
    lowered = text.lower()

    assert "cluster" in lowered
    assert "evenly spaced" in lowered or "even spacing" in lowered
    assert "min_gap" in text


def test_build_loop_gates_furnishing_on_a_structural_check():
    """Structure must be proven before anything is dressed.

    Repairing a floorplan after furnishing means moving every prop twice, and
    the defects that matter — a sealed room, a door that missed its wall — are
    invisible in element counts. The check is cheap and read-only, so it
    belongs as a gate at the end of the shell phase rather than as advice.
    """
    text = (REPOSITORY_ROOT / "skills" / "_shared" / "build-loop.md").read_text()
    lowered = text.lower()

    assert "validate_floorplan" in text
    # it has to gate, not merely be mentioned somewhere afterwards
    assert lowered.index("validate_floorplan") < lowered.index("interior rooms, one at a time")
    assert "sealed" in lowered
    for signal in ("before", "furnish"):
        assert signal in lowered


def test_material_language_auditions_a_family_before_committing_to_it():
    """Filenames are not descriptions, and the cost of trusting them is rework.

    bench_03 and bench_05 are stone. That surfaced only after they were placed
    in a timber tavern and rendered, and recovering meant rescaling and
    re-tinting every one. The look has to happen while the family is being
    CHOSEN — which is also the only moment cheap enough to be worth it, since a
    map commits to few families and repeats each many times.
    """
    text = (REPOSITORY_ROOT / "skills" / "battlemap-material-language" / "SKILL.md").read_text()
    lowered = text.lower()

    assert "preview_assets" in text
    # it belongs to choosing the family, not to every placement
    assert lowered.index("preview_assets") < lowered.index("place with jitter")
    # the red-mask trap has to be called out, or a colourable asset reads as red art
    assert "mask" in lowered


def test_material_language_verifies_the_first_placement_before_repeating():
    """Scale is not normalised, and a family is placed many times.

    Benches went down at 0.9 and read as pebbles; the fix was 1.9, applied to
    eight of them after the fact. A contact sheet cannot catch this — it shows
    the art, not how big the thing is against the room — so the first placement
    has to be checked in situ before the family is repeated.
    """
    text = (REPOSITORY_ROOT / "skills" / "battlemap-material-language" / "SKILL.md").read_text()
    lowered = text.lower()

    # distinctive phrases: an earlier version of this test passed on the words
    # "first" and "repeats" appearing incidentally elsewhere in the skill
    assert "first instance" in lowered
    assert "before repeating" in lowered
    # it is a verification step, so it belongs after the placement guidance
    assert lowered.index("place with jitter") < lowered.index("first instance")
    # a tint judged on a plain ground shifts under the map's own light
    assert "modulate" in lowered


def test_build_loop_says_why_a_checkpoint_matters():
    """Undo is bounded, so past a point a checkpoint is the only way back."""
    text = (REPOSITORY_ROOT / "skills" / "_shared" / "build-loop.md").read_text()
    lowered = text.lower()

    assert "undo" in lowered
    assert "40" in text or "capped" in lowered


def test_composition_audit_warns_that_counts_do_not_cover_surfaces():
    """Zero elements is not an empty map.

    Floors, tiles, terrain and water are layers, not elements. A scratch map
    reporting every count at zero was in fact covered in leftover tiling, and
    reading counts alone produced a confident wrong claim about it.
    """
    text = (REPOSITORY_ROOT / "skills" / "battlemap-composition-audit" / "SKILL.md").read_text()
    lowered = text.lower()

    assert "counts" in lowered
    for surface in ("terrain", "layers"):
        assert surface in lowered


def test_material_language_measures_an_asset_before_positioning_it():
    """Asset sizes are not normalised and cannot be guessed.

    bar_table was estimated at 512 woxels, then 794; it is 1223 — nearly five
    tiles, meaning one piece IS the whole bar. Repeating it produced overlap
    rather than a longer counter. fit_elements on a single id returns the real
    bounds, which is the only reliable way to know a footprint.
    """
    text = (REPOSITORY_ROOT / "skills" / "battlemap-material-language" / "SKILL.md").read_text()
    lowered = text.lower()

    assert "fit_elements" in text
    assert "footprint" in lowered
    # one piece may already be the entire fixture
    assert "whole fixture" in lowered or "entire fixture" in lowered


def test_interiors_checks_the_wall_before_placing_against_it():
    """Three placement errors in one build shared this cause.

    A hearth was pushed through an exterior wall, a counter was overlapped with
    its own neighbour, and a window was buried behind a chimney breast — each
    time by checking the object in isolation and never its surroundings.
    """
    text = (REPOSITORY_ROOT / "skills" / "battlemap-interiors" / "SKILL.md").read_text()
    lowered = text.lower()

    assert "window" in lowered
    assert "already on that wall" in lowered or "what is already on" in lowered
    assert "validate_placements" in text


def test_interiors_requires_a_fixture_to_work_for_whoever_uses_it():
    """Furniture that cannot be operated reads as scenery, not architecture.

    A bar needs a side the server can stand on; a hearth that is the room's
    focal point needs visible fire, or it is a cold stone recess.
    """
    text = (REPOSITORY_ROOT / "skills" / "battlemap-interiors" / "SKILL.md").read_text()
    lowered = text.lower()

    assert "silhouette" in lowered
    for signal in ("bar", "fire"):
        assert signal in lowered


def test_the_build_loop_gates_lighting_on_a_placement_check():
    """A checker nothing calls catches nothing.

    validate_placements exists because three intrusions survived a whole build
    while every element count read as correct. If the loop does not call it,
    the next build finds them the same way this one did — in a render, by eye,
    and only after the furniture is in.
    """
    text = (REPOSITORY_ROOT / "skills" / "_shared" / "build-loop.md").read_text()
    lowered = text.lower()

    assert "validate_placements" in text
    # it has to land AFTER the rooms are furnished; run before, it has nothing
    # to measure, and the shell already has its own gate in phase 3
    assert text.index("validate_placements") > text.index("## 7. Interior rooms")
    assert text.index("validate_placements") < text.index("## 8. Light the map")
    # and it must say what it deliberately does not report, or the first
    # tankard on a table reads as a defect and the tool gets ignored
    assert "tankard" in lowered


def test_lighting_requires_every_source_to_be_explainable():
    """A light with nothing emitting it reads as a glitch, indoors or out.

    The hierarchy rules say what a light is FOR — focal, threshold, route cue —
    and nothing said what is producing it. A pool of warm light on open ground
    with no lantern, fire or window above it has no cause a viewer can name,
    and outdoors the global condition (daylight, moonlight, overcast) is itself
    a source that has to be decided rather than assumed.
    """
    text = (REPOSITORY_ROOT / "skills" / "battlemap-lighting-hierarchy" / "SKILL.md").read_text()
    lowered = text.lower()

    assert "source" in lowered
    # the rule has to name real emitters, or it stays an abstraction
    for emitter in ("lantern", "fire", "moonlight"):
        assert emitter in lowered, f"the rule never names {emitter} as a source"
    # and it has to say the object goes in, not just that a source exists
    assert "place the object" in lowered or "object that emits" in lowered


def test_environments_treats_a_building_as_having_a_site():
    """An inn read as floating in a void because the outside was leftover space.

    The exterior of a building map is not the margin left after the walls go
    up. It is where the building is, and it has to answer how people arrive,
    where they come in, and where the work happens — otherwise no amount of
    ground texture makes it feel inhabited.
    """
    text = (REPOSITORY_ROOT / "skills" / "battlemap-environments" / "SKILL.md").read_text()
    lowered = text.lower()

    assert "site" in lowered
    assert "margin" in lowered or "leftover" in lowered
    # the concrete questions, not just the principle
    assert "arrive" in lowered or "approach" in lowered
    assert "road" in lowered or "track" in lowered


def test_the_build_loop_puts_ground_under_everything_before_objects():
    """Terrain painted around objects reads as objects floating.

    The failure was grass only where the trees touched. Painting ground last,
    per-object, is what produces that; covering the whole surface first is what
    prevents it, and it costs one call.
    """
    text = (REPOSITORY_ROOT / "skills" / "_shared" / "build-loop.md").read_text()

    assert "validate_scene" in text
    # Phase 2 has always said to fill the ground field, and that was not enough
    # to stop it happening — so the rule has to be restated where the exterior
    # is actually dressed, with the consequence attached.
    exterior = text[text.index("## 6. Exterior regions") : text.index("## 7. Interior rooms")]
    assert "fill_terrain" in exterior
    assert "around" in exterior.lower(), "it has to say why painting ground last fails"
    # and the brush/region distinction, which is what produced the disc stains
    assert "fill_region" in exterior and "paint_terrain" in exterior


def test_material_language_says_to_look_at_a_material_not_read_its_name():
    """`dirt` sounds like a road surface and renders nearly black.

    Chosen by name it read as a shadow across the bottom of the map and cost a
    round of revision; the contact sheet showed the problem in one look.
    """
    text = (REPOSITORY_ROOT / "skills" / "battlemap-material-language" / "SKILL.md").read_text()
    lowered = text.lower()

    # preview_assets was already recommended for shortlists before this rule
    # existed, and the material was still picked by name — so pin the claim the
    # new section actually makes, not the tool it happens to mention.
    assert "## Look at a material; do not read its name" in text
    assert "dirt" in lowered, "the rule should carry the case that produced it"
    # the two things a name cannot tell you
    assert "value" in lowered and "contrast" in lowered


def test_material_language_fits_the_asset_to_the_space_it_goes_in():
    """An oak is 5.7 tiles wide; the exterior band was 3.

    Measuring the asset is half of it. The other half is measuring the gap it
    has to sit in, which is what made four trees cover the building.
    """
    text = (REPOSITORY_ROOT / "skills" / "battlemap-material-language" / "SKILL.md").read_text()
    lowered = text.lower()
    assert "space it has to sit in" in lowered or "measure the gap" in lowered


def test_interiors_gives_a_directional_fixture_a_facing():
    """A wall torch throws light one way, and unrotated is not neutral.

    Placed unrotated on a south wall, the sconce hung through the wall and lit
    the road instead of the entry hall.
    """
    text = (REPOSITORY_ROOT / "skills" / "battlemap-interiors" / "SKILL.md").read_text()
    lowered = text.lower()
    assert "facing" in lowered
    assert "unrotated" in lowered or "rotation 0" in lowered


def test_the_build_loop_confirms_a_checkpoint_rather_than_trusting_the_call():
    """A tavern was built for twenty minutes into a map that could not be saved.

    save_map kept replying as though it had worked, and every "checkpoint" was a
    request nobody confirmed. The loop has to say how to tell a real checkpoint
    from a request for one, and what to do when it is not one.
    """
    text = (REPOSITORY_ROOT / "skills" / "_shared" / "build-loop.md").read_text()
    prose = " ".join(text.split()).lower()  # the rule may wrap anywhere
    assert "saves_seen" in text
    assert "save_warning" in text
    assert "stop building and tell the user" in prose


def _prose(path):
    """Skill text with wrapping normalised, so a rule may be re-wrapped freely."""
    return " ".join((REPOSITORY_ROOT / path).read_text().split())


def test_the_build_loop_caps_wall_junctions_above_the_walls():
    """Corner posts were placed on the default layer and vanished into the wall.

    The loop offers typed merging for eligible runs and keeps the measured
    layer requirement for architectural posts used at remaining seams.
    """
    prose = _prose("skills/_shared/build-loop.md")
    assert "merge_walls(ids=[survivor, absorbed])" in prose
    assert "layer 700 up" in prose or "layer=700" in prose
    assert "pillar_wood" in prose
    # it belongs to shell work, before the regions are dressed
    text = (REPOSITORY_ROOT / "skills" / "_shared" / "build-loop.md").read_text()
    assert text.index("layer=700") < text.index("## 4. Assign region emphasis")


def test_the_build_loop_matches_a_doors_opening_to_its_art():
    """A tavern's entrance used radius=256 and its doors floated in the hole.

    Measured with door_01: the art fills a 256-woxel opening and never grows
    past it, so a wider radius only opens more wall around a fixed-size door.
    A double door is therefore two portals, not one wide one. The quieter
    failures — a gap left in the wall, a portal placed too near another — are
    reported only by `kind` and `snap_distance`, so the loop must name them.
    """
    prose = _prose("skills/_shared/build-loop.md")
    assert "never grows beyond its natural size" in prose
    assert "a double door is two portals" in prose
    assert "freestanding" in prose
    assert "snap_distance" in prose and "`kind`" in prose


def test_interiors_gives_wall_furniture_a_rotation_per_wall():
    """Every bookshelf in a tavern faced the partition it stood against.

    Saying "decide the facing" was not enough; the skill has to say which way
    the asset already faces at rotation 0, and what each wall therefore needs.
    """
    prose = _prose("skills/battlemap-interiors/SKILL.md")
    assert "facing DOWN at rotation 0" in prose
    for row in (
        "| North (wall above it) | 0 |",
        "| East | 90 |",
        "| South | 180 |",
        "| West | 270 |",
    ):
        assert row in prose, row
    assert "preview_assets" in prose
    assert "flush" in prose


def test_environments_says_which_ground_edges_can_never_blend():
    """Grass painted across a pattern path's edge never arrives.

    And the reason blending looks impossible even on terrain: slot 0 is the
    base and cannot be painted, so a grass base needs a second, paintable slot.
    """
    prose = _prose("skills/battlemap-environments/SKILL.md")
    assert "cannot blend into anything" in prose
    assert "path_blender" in prose
    assert "Slot 0 is the base and is NOT paintable" in prose
    assert "paintable slot" in prose


def test_environments_requires_ground_that_is_alive():
    """An exterior passed every structural check and read as municipal lawn."""
    prose = _prose("skills/battlemap-environments/SKILL.md")
    assert "Nothing grows on a map by itself" in prose
    assert "ferns" in prose  # the families a build never reaches for
    assert "where feet and wheels do not" in prose
    assert "sparse, not sterile" in prose


def test_the_build_loop_asks_before_building_when_the_brief_is_open():
    """A vague brief answered by guessing costs a whole build, then a rebuild.

    The rule has to bound the asking as well as require it: one round, at most
    five, scaled to how open the brief is, and only about decisions the model
    cannot make for itself.
    """
    prose = _prose("skills/_shared/build-loop.md")
    assert "one round of at most five questions" in prose
    assert "a detailed brief needs none" in prose
    assert "never which table asset to use" in prose
    assert "style bible" in prose
    # it belongs in planning, before the foundation goes down
    text = (REPOSITORY_ROOT / "skills" / "_shared" / "build-loop.md").read_text()
    assert text.index("at most five questions") < text.index("## 2. Lay the foundation")


def test_the_build_loop_checks_which_asset_packs_the_map_includes():
    """A whole tavern was built from 1,792 vanilla assets with 12 packs installed.

    Nothing was broken: packs are scoped per map, and that map included none, so
    `list_assets` looked complete. The rule has to say the scope is the MAP and
    that a map cannot gain packs afterwards — otherwise the check reads as
    optional and gets skipped exactly when it matters, before anything is built.
    """
    prose = _prose("skills/_shared/build-loop.md")
    assert "list_asset_packs" in prose
    assert "scoped per MAP" in prose
    assert "installed_but_not_in_this_map" in prose
    assert "prepare_map_with_packs" in prose
    # it belongs in preflight, before anything is placed
    text = (REPOSITORY_ROOT / "skills" / "_shared" / "build-loop.md").read_text()
    assert text.index("list_asset_packs") < text.index("## 2. Lay the foundation")


def test_the_build_loop_picks_packs_by_subject_rather_than_all_of_them():
    """ "Include everything" is only free on a small library.

    One measured library held 12.5 GB across 14 packs, with a single pack
    carrying 129,098 of 141,197 objects — so the rule has to give the model a
    basis for choosing (subject, and the fact that size is wildly uneven)
    rather than just telling it packs exist. It also has to say what happens
    when it reaches past the map's packs, because that used to lose work
    silently and now fails loudly.
    """
    prose = _prose("skills/_shared/build-loop.md")
    assert "Choose packs by subject" in prose
    assert "vary enormously in size" in prose  # the skew is why not to take all
    assert "hidden_unusable" in prose
    assert "refused, not silently lost" in prose
    assert "preview_assets" in prose  # the exemption, so packs stay evaluable


def test_the_build_loop_requires_a_checkpoint_to_be_a_real_save():
    """Runtime behavior and validation."""
    prose = _prose("skills/_shared/build-loop.md")
    assert "is_backup" in prose
    assert "map_file" in prose
    assert "autosave" in prose.lower()
    assert "explicit `filename`" in prose or "explicit filename" in prose


def test_the_build_loop_forbids_summarising_a_validator_as_clean():
    """Runtime behavior and validation."""
    prose = _prose("skills/_shared/build-loop.md")
    assert "never summarise them as" in prose
    assert "`ok: false`" in prose
    assert "blocks calling the map finished" in prose
    assert "coverage" in prose  # an incomplete verdict is not a clean one


def test_the_build_loop_makes_the_planning_choice_visible():
    """Runtime behavior and validation."""
    prose = _prose("skills/_shared/build-loop.md")
    assert "Say which way you went" in prose
    assert "never visibly exercised" in prose


def test_the_build_loop_requires_supporting_props_in_the_same_pass():
    """Runtime behavior and validation."""
    prose = _prose("skills/_shared/build-loop.md")
    assert "carries its meaning through its neighbours" in prose
    assert "map zoom" in prose
    assert "preview_assets" in prose


def test_environments_scales_vegetation_from_its_texture_size():
    """Stated as a principle with no asset names or counts: these skills ship to
    users whose installed library is nothing like the one this was measured on.
    """
    prose = _prose("skills/battlemap-environments/SKILL.md")
    assert "texture_size" in prose
    assert "desired_tiles * 256 / texture_px" in prose
    assert "Never assume a family shares a size" in prose


def test_the_public_skills_make_no_claims_about_which_assets_are_installed():
    """Skills ship to users whose library is nothing like the one they were
    written against.

    A count of grasses, a pack's size in gigabytes or "this library" is a fact
    about one machine on the day it was measured. It reads as authoritative,
    it cannot be checked by the model, and it is wrong for almost everyone —
    so the rules must teach discovery (`list_assets`, `list_asset_packs`,
    `texture_size`) instead of memorised inventory.
    """
    import re

    banned = re.compile(
        r"\bthis library\b|\bmeasured here\b|\binstalled here\b|\b\d+(\.\d+)?\s?GB\b"
        r"|\b\d{1,3},\d{3}\b",
        re.IGNORECASE,
    )
    offenders = []
    for path in sorted((REPOSITORY_ROOT / "skills").rglob("*.md")):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            found = banned.search(line)
            if found:
                rel = path.relative_to(REPOSITORY_ROOT)
                offenders.append(f"{rel}:{number}: {found.group(0)!r} in {line.strip()[:70]}")
    assert not offenders, "install-specific claims in public skills:\n" + "\n".join(offenders)


def test_the_build_loop_chooses_its_tools_before_its_assets():
    """Runtime behavior and validation."""
    prose = _prose("skills/_shared/build-loop.md")
    assert "Choose the tools before you choose the assets" in prose
    for named in (
        "generate_dungeon",
        "dig_cave",
        "place_pattern",
        "draw_path",
        "add_water",
        "list_prefabs",
    ):
        assert named in prose, named
    assert "Delivery" in prose


def test_interiors_does_not_claim_a_pattern_floor_sits_above_objects():
    """Runtime behavior and validation."""
    prose = _prose("skills/battlemap-interiors/SKILL.md")
    assert "Floor patterns sit on 100" not in prose
    assert "ABSOLUTE" in prose
    assert "-100" in prose
    assert "read both back" in prose


def test_the_build_loop_treats_junction_posts_as_a_workaround():
    """Runtime behavior and validation."""
    prose = _prose("skills/_shared/build-loop.md")
    assert "Do not add posts automatically" in prose
    assert "Prefer one continuous polyline" in prose
    assert "T-junctions, loops, cave walls" in prose


def test_the_build_loop_checks_under_a_roof_before_calling_a_building_done():
    """Runtime behavior and validation."""
    prose = _prose("skills/_shared/build-loop.md")
    assert "A roof hides the room it covers" in prose
    assert "RIDGE line and a width" in prose
    assert "roof_type" in prose  # the readback that makes the check possible


def test_environments_requires_a_crossing_to_be_one_span():
    """Runtime behavior and validation."""
    prose = _prose("skills/battlemap-environments/SKILL.md")
    assert "A crossing is one span" in prose
    assert "visible seam" in prose
    assert "layers.water: true" in prose


def test_the_build_loop_teaches_path_end_treatments():
    """Runtime behavior and validation."""
    prose = _prose("skills/_shared/build-loop.md")
    for flag in ("fade_in", "fade_out", "grow", "shrink"):
        assert flag in prose, flag
    assert "hard rectangular cut" in prose


def test_the_build_loop_looks_for_a_prefab_before_hand_composing():
    """Runtime behavior and validation."""
    prose = _prose("skills/_shared/build-loop.md")
    assert "Look for a prefab before hand-composing" in prose
    assert "list_prefabs" in prose
    assert "names what it skipped" in prose


def test_the_build_loop_has_a_delivery_step():
    """Runtime behavior and validation."""
    prose = _prose("skills/_shared/build-loop.md")
    assert "Deliver it" in prose
    assert "add_text" in prose
    assert "Universal VTT" in prose
    assert "GM version and a player version are different files" in prose


def test_environments_carves_caves_rather_than_building_them():
    """Runtime behavior and validation."""
    prose = _prose("skills/battlemap-environments/SKILL.md")
    assert "Caves are carved, not built" in prose
    assert "A single point is a chamber" in prose
    assert "ground_color" in prose and "wall_color" in prose
    assert "cave mouth" in prose.lower()


def test_the_build_loop_plans_levels_and_roof_ridges():
    """Runtime behavior and validation."""
    prose = _prose("skills/_shared/build-loop.md")
    assert "A second floor is a plan, not an afterthought" in prose
    assert "share the map's COORDINATES" in prose or "shares the map's COORDINATES" in prose
    assert "takes an ID from `list_levels`, not a position" in prose
    assert "ridge line and a width, not an outline" in prose
    assert "sun_angle" in prose
