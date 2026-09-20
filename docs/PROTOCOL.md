# Bridge wire protocol

## Current protocol

**Current protocol version:** 25. The bridge uses localhost TCP and newline-terminated UTF-8 JSON. Each connection carries one handshake and one authenticated command, then closes. Use the companion client for port discovery and authentication.

## Handshake and authenticated envelopes

```json
-> { "cmd": "hello", "protocol": 25, "nonce": "<32 lowercase hex characters>" }
<- { "ok": true, "result": { "protocol": 25, "nonce": "<32 lowercase hex characters>", "proof": "<hex>" } }
-> { "seq": 1, "payload": "{\"cmd\":\"get_status\"}", "auth": "<hex>" }
<- { "seq": 1, "payload": "{\"ok\":true,\"result\":{...}}", "auth": "<hex>" }
```

All proofs use HMAC-SHA256, with the UTF-8 token as key and lowercase hex output:

```text
hello proof: dd-mcp/25|server|<client nonce>|<mod nonce>
request MAC: dd-mcp/25|request|<client nonce>|<mod nonce>|1|<payload>
response MAC: dd-mcp/25|response|<client nonce>|<mod nonce>|1|<payload>
```

The MAC covers the exact UTF-8 encoding of the decoded `payload` **string**.
Verify it before parsing that string as JSON. This avoids cross-language JSON
canonicalization: whitespace and key order inside the string are authenticated.
Both nonces are freshly generated per connection. The fixed sequence `1` is the
only sequence accepted; a successful request consumes the connection. Direction
separation prevents a request proof from authenticating a response.

The inner request contains `cmd` plus command parameters. An `id` parameter
identifies an element where the command requires it. A `token` field is refused.
The response shapes below describe the inner payload, not the wire envelope.

The mod proves knowledge of the token before the client sends a command. Every
command and its response are then authenticated, including Python's `ping`.
Protocol 25 provides integrity, not encryption.

## Responses

The authenticated inner response is `{ "ok": true, "result": {...} }` on success or `{ "ok": false, "error": "..." }` on failure. Reject unverified responses. Never automatically repeat a mutation after an uncertain transport failure.

## Public tools and parameters

The following is the public MCP tool surface; the companion may perform several bridge requests for one tool. The MCP schemas define types, defaults, and required fields. Coordinates use 256 world pixels per tile. Element IDs identify items returned by creation or query tools.

| Tool | Parameters |
| --- | --- |
| `ping` | — |
| `get_status` | — |
| `list_asset_categories` | — |
| `list_asset_packs` | — |
| `prepare_map_with_packs` | `filename`, `packs` |
| `list_assets` | `category`, `search`, `limit`, `vanilla_only`, `match_mode`, `min_score`, `searches` |
| `preview_assets` | `assets`, `category`, `columns`, `cell_px` |
| `repair_terrain` | `force` |
| `validate_scene` | `samples`, `emitter_reach` |
| `validate_floorplan` | `cell_woxels`, `min_room_tiles` |
| `validate_placements` | `tolerance_woxels` |
| `list_elements` | `kind`, `limit`, `include_points`, `offset` |
| `get_composition_snapshot` | — |
| `get_element` | `id` |
| `list_levels` | — |
| `place_object` | `asset`, `x`, `y`, `scale`, `rotation`, `sorting`, `layer`, `color`, `modulate`, `block_light` |
| `place_objects` | `objects` |
| `draw_wall` | `points`, `asset`, `loop`, `shadow`, `type`, `joint`, `color` |
| `merge_walls` | `ids` |
| `draw_path` | `points`, `asset`, `layer`, `sorting`, `smoothness`, `width`, `fade_in`, `fade_out`, `grow`, `shrink` |
| `add_light` | `x`, `y`, `color`, `energy`, `range`, `shadows`, `asset` |
| `add_portal` | `asset`, `x`, `y`, `closed`, `radius`, `mount`, `snap_max`, `flip`, `fallback_free`, `rotation` |
| `add_roof` | `points`, `asset`, `width`, `type`, `sorting`, `sunlight`, `sun_angle`, `sun_contrast` |
| `place_pattern` | `asset`, `rect`, `points`, `category`, `color`, `rotation`, `z` |
| `build_room` | `rect`, `points`, `wall_asset`, `floor`, `floor_asset`, `floor_category`, `floor_color`, `floor_slot`, `wall_type`, `wall_joint` |
| `scatter_objects` | `assets`, `rect`, `count`, `scale_min`, `scale_max`, `rotation_min`, `rotation_max`, `min_gap`, `color`, `sorting`, `layer`, `seed` |
| `add_text` | `text`, `x`, `y`, `size`, `color`, `font` |
| `generator_options` | `name`, `value` |
| `generate_dungeon` | `design`, `floor`, `wall` |
| `add_floor` | `rect`, `points`, `invert`, `smart_tile_id`, `wall_asset`, `wall_color`, `bevel` |
| `set_verbose` | `on` |
| `log_marker` | `text` |
| `paint_material` | `points`, `asset`, `size`, `layer`, `smooth`, `erase` |
| `set_trace_image` | `path`, `scale`, `opacity`, `center`, `clear` |
| `get_map_style` | — |
| `set_map_style` | `building_wear`, `grid_style` |
| `set_water_style` | `deep_color`, `shallow_color`, `blend_distance`, `border` |
| `set_terrain_blending` | `enabled` |
| `get_terrain` | `rect`, `samples` |
| `set_terrain_slot` | `asset`, `slot` |
| `fill_terrain` | `slot`, `asset` |
| `fill_region` | `rect`, `points`, `slot`, `asset`, `rate` |
| `paint_terrain` | `slot`, `x`, `y`, `radius`, `rate`, `asset` |
| `paint_path` | `points`, `slot`, `radius`, `rate`, `asset` |
| `get_cave` | — |
| `set_cave_entrance` | `x`, `y`, `radius`, `open` |
| `dig_cave` | `points`, `radius`, `dig`, `ground_color`, `wall_color`, `texture` |
| `add_water` | `rect`, `points`, `invert` |
| `set_ambient_light` | `color` |
| `list_prefabs` | `set` |
| `place_prefab` | `name`, `set`, `x`, `y`, `rotation` |
| `list_tool_controls` | `tool` |
| `tool_action` | `tool`, `control` |
| `set_tool_option` | `tool`, `control`, `item`, `color`, `pressed`, `value`, `item_index`, `item_metadata` |
| `save_map` | `filename`, `overwrite`, `wait` |
| `get_save_directory` | — |
| `set_save_directory` | `path` |
| `open_map` | `path`, `wait` |
| `clear_caves` | — |
| `move_element` | `id`, `x`, `y` |
| `move_elements` | `ids`, `dx`, `dy`, `rotation`, `pivot_x`, `pivot_y` |
| `modify_object` | `id`, `scale`, `rotation`, `color`, `modulate`, `shadow`, `layer`, `block_light` |
| `duplicate_object` | `id`, `dx`, `dy` |
| `delete_element` | `id` |
| `delete_elements` | `ids` |
| `add_level` | `label` |
| `set_map_size` | `width`, `height` |
| `delete_level` | `id` |
| `set_level` | `id` |
| `screenshot` | `max_px` |
| `clear_captures` | — |
| `export_map` | `ppi`, `format`, `timeout`, `max_px` |
| `get_export` | `operation_id`, `timeout`, `max_px` |
| `get_operation` | `operation_id` |
| `get_camera` | — |
| `set_camera` | `x`, `y`, `zoom` |
| `focus_element` | `id`, `zoom` |
| `fit_elements` | `ids`, `pad` |
| `select_elements` | `ids` |
| `clear_selection` | — |
| `undo` | — |
| `redo` | — |
| `get_recent_nodes` | `since`, `limit` |
| `get_tool_layer` | `tool` |
| `set_tool_layer` | `tool`, `layer` |
| `select_tool` | `tool` |
| `inspect_dungeondraft_installation` | `live` |
| `install_dungeondraft_bridge` | `mods_dir`, `confirm` |
