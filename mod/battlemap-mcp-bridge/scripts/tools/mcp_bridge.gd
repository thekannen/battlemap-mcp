var script_class = "tool"

const HOST := "127.0.0.1"
const PORT := 8787
# A process launched by the evaluator gets a dedicated, exact listener. This
# must not fall back to PORT_SCAN: a fallback can point the evaluator's client
# at the user's shared bridge when the requested endpoint was unavailable.
const EVALUATOR_PORT_ENV := "BATTLEMAP_MCP_LISTEN_PORT"
# How many ports past PORT to try. Each map opened orphans the previous
# instance's listener (see start()), so a long session walks up this range.
const PORT_SCAN := 10
# The port actually bound, published for the client to read. The token file
# next to it is what authenticates; this only says where to knock.
const PORT_FILE := "mcp_bridge_port"
const PROTOCOL_VERSION := 25

const TOKEN_FILE := "mcp_bridge_token"

const CONFIG_FILE := "mcp_bridge_config.json"

const SETTINGS_FILE := "mcp_bridge_settings.json"
const PANEL_ICON := "icons/mcp_bridge.png"

# Maps saved through the bridge land in a named subdirectory of Dungeondraft's
# own map folder rather than loose in it, so they are easy to find and easy to
# tell apart from maps the user made by hand.
const SAVE_SUBDIR := "battlemap-mcp"

# A peer that never sends a newline would otherwise grow its buffer without
# bound. 1 MiB is far above any legitimate request (the largest realistic one is
# a long points array, a few tens of KiB).
const MAX_LINE_BYTES := 1048576
const READ_BYTES_PER_UPDATE := 131072
const READ_BYTES_PER_CONN := 65536

const MAX_CONNS := 8
const MAX_TOTAL_BUFFER_BYTES := 4194304
const MAX_REQUESTS_PER_UPDATE := 8

const MAX_REQUESTS_PER_CONN_PER_UPDATE := 2
# A peer that keeps presenting a wrong proof is not a confused client.
const MAX_AUTH_FAILURES := 3
const OUT_CHUNK_BYTES := 65536
# A peer that connects and never authenticates is closed. Legitimate clients
# handshake immediately; this is what stops idle sockets accumulating.
const UNAUTHENTICATED_MS := 5000
const IDLE_MS := 30000

# Commands that get wrapped in a Dungeondraft undo record (see _record_and_dispatch).
const CREATE_CMDS := [
	"place_object", "draw_wall", "draw_path", "add_light",
	"add_portal", "add_roof", "add_text", "duplicate_object",
]
const TRANSFORM_CMDS := ["move_element", "modify_object"]

const DELETE_CMDS := ["delete_element"]

const MAX_BATCH_ITEMS := 100

const MAX_FILE_BATCH_ITEMS := 1000
const TERRAIN_CMDS := ["fill_terrain", "fill_region", "paint_terrain", "paint_path"]
const CAVE_CMDS := ["dig_cave", "clear_caves", "set_cave_entrance"]

const MATERIAL_DEFAULT_LAYER := -400

const COMPOSITE_CMDS := ["place_pattern", "scatter_objects", "build_room", "place_prefab",
	"place_objects"]
# Neutral opaque tint for pattern floors when no color is given. PatternShapeTool
# has no per-texture default (and its .Color leaks across calls), so we apply a
# deterministic wood/stone-neutral tone; callers pass an explicit color to override.
const DEFAULT_PATTERN_TINT := Color(0.62, 0.5, 0.34)

const WOXELS_PER_TILE := 256

const DEFAULT_OBJECT_LAYER := 100

const SMART_TILE_CATEGORIES := ["Smart Tiles", "Smart Tiles Double"]
# Contact-sheet limits. Capped because each asset is decoded and rescaled, and
# because a sheet of hundreds is unreadable anyway — the point is to choose
# between a handful of candidates, not to browse a library.
const PREVIEW_MAX_ASSETS := 32
const PREVIEW_BG := Color(0.34, 0.34, 0.36, 1.0)
# A colourable asset's raw texture IS its unpainted red mask, so on the neutral
# ground it reads as red ART rather than "whatever colour you pass". Giving it a
# distinct ground is what stops that misreading.
const PREVIEW_BG_COLORABLE := Color(0.16, 0.26, 0.32, 1.0)

const TILE_PREVIEW_CATEGORIES := ["Simple Tiles", "Smart Tiles", "Smart Tiles Double",
	"Patterns Colorable"]

const KIND_NAMES := {
	1: "wall", 2: "wall_portal", 3: "portal", 4: "object",
	5: "path", 6: "light", 7: "pattern", 8: "roof",
}
# kind string -> the Level child collection that holds those nodes.
const COLLECTIONS := {
	"objects": "Objects", "walls": "Walls", "lights": "Lights",
	"paths": "Pathways", "portals": "Portals", "roofs": "Roofs",
	"texts": "Texts",
}

const META_SERVER := "mcp_bridge_server"
const META_PORT := "mcp_bridge_port"
const META_OWNER := "mcp_bridge_owner"

var _instance_id := 0
var _port := PORT
# Per-command log bracketing, off by default so normal use stays quiet.
# Toggled at runtime by set_verbose — no restart needed.
var _verbose := false

var _paused := false
var _panel = null
var _panel_labels := {}
var _panel_controls := {}
var _last_request := ""

var _select_tool_enabled := false

var _signals := {}

var _save_in_flight := false
var _save_path := ""
var _save_is_backup := false
var _save_started_ms := 0
# Saves Dungeondraft has actually begun. OnSaveBegin fires inside SaveMap when
# a save starts, so an unchanged count across a SaveMap call means it declined.
var _save_begins := 0
var _last_save_path := ""
var _saves_seen := 0

var _save_stale_path := ""

var _save_failed_path := ""
# A save that never reports its end would wedge every mutating command forever,
# so the in-flight flag expires. Generous: a large map on a slow disk is slow,
# and expiring early is worse than expiring late.
const SAVE_STALE_MS := 60000

var _assigned := []
var _assign_seq := 0
const ASSIGN_LOG_MAX := 4000

# Dungeondraft's layer values, as read off the layer menu (see _layer_index).
const LAYER_MIN := -500
const LAYER_MAX := 900
const LAYER_STEP := 100

const SAFE_DURING_SAVE := [
	"ping", "get_status", "set_verbose", "log_marker",
	"list_asset_categories", "list_assets", "list_asset_packs", "list_elements", "get_composition_snapshot", "get_element",
	"preview_assets",
	"list_levels", "get_terrain", "get_save_directory",
	"get_map_style", "get_cave",
	"list_tool_controls", "list_prefabs", "get_camera", "get_recent_nodes",
	"get_tool_layer", "get_snap_settings", "checkpoint", "list_checkpoints",

	"screenshot", "export_map",
	"get_operation",
]

const UNSAFE_DURING_EXPORT := ["screenshot", "export_map", "preview_assets"]

func _enable_tool(tool_name : String, editor_tool, do_enable := true) -> bool:
	var was_active := str(Global.Editor.ActiveToolName) == tool_name
	if do_enable and editor_tool != null and editor_tool.has_method("Enable"):
		editor_tool.Enable()
	return was_active

# Same rule as _release_tool, for sites that only hold the tool's name.
func _release_tool_named(tool_name : String) -> void:
	if not Global.Editor.Tools.has(tool_name):
		return
	_release_tool(
		Global.Editor.Tools[tool_name],
		str(Global.Editor.ActiveToolName) == tool_name)

func _rearm_active_tool() -> void:
	if Global.Editor == null:
		return
	var active_name = str(Global.Editor.ActiveToolName)
	# No tool selected yet (a freshly created map) reads back as "Null".
	if active_name == "" or active_name == "Null":
		return
	if not Global.Editor.Tools.has(active_name):
		return
	var active = Global.Editor.Tools[active_name]
	if active.has_method("Enable"):
		active.Enable()

func _release_tool(editor_tool, was_active : bool) -> void:
	# The UI still points at this tool, so leave it enabled — that is the state
	# the editor expects it to be in, and disabling it here is what crashes.
	if was_active:
		return
	if editor_tool != null and editor_tool.has_method("Disable"):
		editor_tool.Disable()

var _server : TCP_Server = null
# Each entry: { "peer": StreamPeerTCP, "buf": String, "out": PoolByteArray,
#               "born": int, "last": int, "cnonce": String, "snonce": String,
#               "closing": bool }
var _conns := []
var _crypto = null
var _undo_stack := []
var _redo_stack := []

var _op_serial := 0
var _lost_serial := 0
var _current_session := ""
var _checkpoints := {}
const MAX_CHECKPOINTS := 20
const CHECKPOINT_WARN_STEPS := 5
# Commands that never enter history themselves and are not map edits a
# checkpoint could miss.
const CHECKPOINT_CMDS := ["checkpoint", "rollback_checkpoint", "list_checkpoints"]
var _token := ""

const MAX_UNDO_OPS := 1000

const SNAPSHOT_BUDGET_BYTES := 64 * 1024 * 1024

# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

func _state_directory() -> String:

	var home = OS.get_environment("USERPROFILE") if OS.get_name() == "Windows" else OS.get_environment("HOME")
	var base = ""
	if OS.get_name() == "Windows":
		base = OS.get_environment("LOCALAPPDATA")
		if not base.is_abs_path(): base = home.plus_file("AppData/Local")
	elif OS.get_name() == "OSX":
		base = home.plus_file("Library/Application Support")
	else:
		base = OS.get_environment("XDG_STATE_HOME")
		if not base.is_abs_path(): base = home.plus_file(".local/state")
	if not base.is_abs_path(): return ""
	return base.plus_file("battlemap-mcp")

func _token_path() -> String:
	var base = _state_directory()
	return base.plus_file(TOKEN_FILE) if base != "" else ""

func _config_path() -> String:
	var base = _state_directory()
	return base.plus_file(CONFIG_FILE) if base != "" else ""

func _ensure_token() -> String:
	var f = File.new()
	# Replace the old inode before writing: chmod does not revoke an already
	# open handle held by another account. Never write a secret into that inode.
	if not _harden_token_file(true):
		return ""

	var token := ""

	var crypto = null
	if ClassDB.can_instance("Crypto"):
		crypto = ClassDB.instance("Crypto")

	if crypto == null:
		print("[mcp-bridge] FATAL: this build cannot instance Crypto, so no secure token can be generated.")
		return ""
	var raw = crypto.generate_random_bytes(32)
	if typeof(raw) != TYPE_RAW_ARRAY or raw.size() != 32:
		print("[mcp-bridge] FATAL: Crypto.generate_random_bytes returned %s bytes, expected 32." % (
			raw.size() if typeof(raw) == TYPE_RAW_ARRAY else "non-byte"))
		return ""
	token = raw.hex_encode()

	if f.open(_token_path(), File.WRITE) != OK:
		print("[mcp-bridge] FATAL: could not write bridge token; the bridge is OFF for this session.")
		return ""
	f.store_string(token)
	f.flush()
	var write_error = f.get_error()
	f.close()
	if write_error != OK:
		print("[mcp-bridge] FATAL: could not persist bridge token; the bridge is OFF for this session.")
		return ""
	# Recheck after close and read the actual persisted bytes. A successful
	# open/store alone does not establish that the client can read this token.
	if not _harden_token_file():
		return ""
	if f.open(_token_path(), File.READ) != OK:
		return ""
	var persisted = f.get_as_text()
	f.close()
	if persisted != token:
		print("[mcp-bridge] FATAL: token persistence verification failed; the bridge is OFF.")
		return ""
	return token

# Godot 3 has no file-permission API, so use the native platform tools and
# verify the resulting access boundary. A warning is not enough: accepting a
# public token makes the HMAC authentication secret public too.
func _unix_execute(executable: String, arguments: Array) -> int:

	var escaped = []
	for argument in arguments:
		escaped.append(str(argument).replace("\\", "\\\\").replace("\"", "\\\"").replace("$", "\\$").replace("`", "\\`"))
	var output = []
	var result = OS.execute(executable, escaped, true, output, true)
	if result != 0:
		for message in output:
			print(str(message).strip_edges())
	return result

func _powershell_token_check(script: String, path: String, reset: bool) -> int:
	# -Command reparses arguments as source. Encode an ASCII script with a
	# base64 path instead, including paths containing quotes or metacharacters.
	var source = "$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + Marshalls.raw_to_base64(path.to_utf8()) + "'));$reset=" + ("$true;" if reset else "$false;") + script
	var ascii_bytes = source.to_utf8()
	var utf16 = PoolByteArray()
	utf16.resize(ascii_bytes.size() * 2)
	for i in range(ascii_bytes.size()):
		utf16[i * 2] = ascii_bytes[i]
		utf16[i * 2 + 1] = 0
	var powershell = OS.get_environment("SystemRoot").plus_file("System32/WindowsPowerShell/v1.0/powershell.exe")
	var output = []
	var result = OS.execute(powershell, ["-NoProfile", "-NonInteractive", "-EncodedCommand", Marshalls.raw_to_base64(utf16)], true, output)
	if result != 0:
		for message in output:
			print("[mcp-bridge] " + str(message).strip_edges())
	return result

func _harden_token_file(reset: bool = false) -> bool:
	var path = _token_path()
	var os_name = OS.get_name()
	if os_name == "X11":
		# Preserve the inherited Linux path. POSIX ACL masks follow chmod;
		# unlike macOS, Linux has no chmod -N to remove extended ACL entries.
		var linux_script = "set -eu\np=$1\nparent=${p%/*}\ncase \"$p\" in /*) ;; *) exit 1;; esac\n# Refuse any redirected ancestor before creating our own directory.\nd=$parent\nwhile test \"$d\" != /; do\n test ! -L \"$d\"\n d=${d%/*}\n test -n \"$d\" || d=/\ndone\nif test ! -e \"$parent\"; then\n test \"${2:-0}\" = 1\n (umask 077; /bin/mkdir -p \"$parent\")\nfi\n# A redirected parent is refused, not chmodded through its target.\ntest \"$(cd \"$parent\" && /bin/pwd -P)\" = \"$parent\"\ntest \"$(/usr/bin/stat -c %u -- \"$parent\")\" = \"$(/usr/bin/id -u)\"\ntest ! -L \"$p\"\nif test -e \"$p\"; then\n test -f \"$p\"\n test \"$(/usr/bin/stat -c %u -- \"$p\")\" = \"$(/usr/bin/id -u)\"\n test \"$(/usr/bin/stat -c %h -- \"$p\")\" = 1\nfi\n# Private parent prevents other accounts replacing the entry between checks.\n/bin/chmod 700 \"$parent\"\ntest \"$(/usr/bin/stat -c %a -- \"$parent\")\" = 700\nif test \"${2:-0}\" = 1; then\n if test -e \"$p\"; then /bin/rm \"$p\"; fi\n (umask 077; set -C; : > \"$p\")\nfi\ntest -f \"$p\" && test ! -L \"$p\"\n/bin/chmod 600 \"$p\"\ntest \"$(/usr/bin/stat -c %a -- \"$p\")\" = 600\ntest \"$(/usr/bin/stat -c %u -- \"$p\")\" = \"$(/usr/bin/id -u)\"\ntest \"$(/usr/bin/stat -c %h -- \"$p\")\" = 1\n"
		if _unix_execute("/bin/sh", ["-c", linux_script, "--", path, "1" if reset else "0"]) == 0:
			return true
	if os_name == "OSX":
		var mac_script = "set -eu\nreason='native permission command failed; check storage access and macOS permission tools'\ntrap 'status=$?; if test \"$status\" != 0; then printf \"%s\\n\" \"[mcp-bridge] token storage: $reason\" >&2; fi' 0\np=$1\nparent=${p%/*}\nreason='token path must be absolute'\ncase \"$p\" in /*) ;; *) exit 1;; esac\n# Refuse any redirected ancestor before creating our own directory.\nreason='redirected ancestor refused; use a real private storage directory'\nd=$parent\nwhile test \"$d\" != /; do\n test ! -L \"$d\"\n d=${d%/*}\n test -n \"$d\" || d=/\ndone\nif test ! -e \"$parent\"; then\n reason='missing state directory during verification; restart to create private storage'\n test \"${2:-0}\" = 1\n reason='cannot create private state directory; check parent write access'\n (umask 077; /bin/mkdir -p \"$parent\")\nfi\n# A redirected parent is refused, not chmodded through its target.\nreason='redirected parent refused; use a real private storage directory'\ntest \"$(cd \"$parent\" && /bin/pwd -P)\" = \"$parent\"\nreason='state directory owner mismatch; use storage owned by the current account'\ntest \"$(/usr/bin/stat -f %u \"$parent\")\" = \"$(/usr/bin/id -u)\"\nreason='token symlink refused; use a regular private token file'\ntest ! -L \"$p\"\nif test -e \"$p\"; then\n reason='token must be a regular file'\n test -f \"$p\"\n reason='token owner mismatch; use a token owned by the current account'\n test \"$(/usr/bin/stat -f %u \"$p\")\" = \"$(/usr/bin/id -u)\"\n reason='token hard link refused; use a file with a single link'\n test \"$(/usr/bin/stat -f %l \"$p\")\" = 1\nfi\n# Private parent prevents other accounts replacing the entry between checks.\nreason='cannot restrict private state directory ACL or mode; check ownership and access'\n/bin/chmod -N \"$parent\"\n/bin/chmod 700 \"$parent\"\ntest \"$(/usr/bin/stat -f %Lp \"$parent\")\" = 700\nif test \"$2\" = 1; then\n reason='cannot rotate token; check private directory write access'\n if test -e \"$p\"; then /bin/rm \"$p\"; fi\n (umask 077; set -C; : > \"$p\")\nfi\nreason='missing token or nonregular token during verification; restart to create private storage'\ntest -f \"$p\"\ntest ! -L \"$p\"\nreason='cannot restrict token ACL or mode; check ownership and access'\n/bin/chmod -N \"$p\"\n/bin/chmod 600 \"$p\"\ntest \"$(/usr/bin/stat -f %Lp \"$p\")\" = 600\ntest \"$(/usr/bin/stat -f %u \"$p\")\" = \"$(/usr/bin/id -u)\"\ntest \"$(/usr/bin/stat -f %l \"$p\")\" = 1\n"
		if _unix_execute("/bin/sh", ["-c", mac_script, "--", path, "1" if reset else "0"]) == 0:
			return true
	elif os_name == "Windows":

		var acl_script = "$ErrorActionPreference='Stop'; try {\n$me=[Security.Principal.WindowsIdentity]::GetCurrent().User\n$SID=[Security.Principal.SecurityIdentifier]\n$AR=[Security.AccessControl.FileSystemAccessRule]\nfunction Owner($e){$e.GetAccessControl('Owner').GetOwner($SID)}\nfunction PrivateAcl($path) {\n $entry=Get-Item -Force -LiteralPath $path\n $owner=(Owner $entry)\n if($owner -ne $me){throw ('owner mismatch: expected '+$me.Value+', actual '+$owner.Value)}\n $acl=$entry.GetAccessControl('Access')\n $inherit=0\n if($entry.PSIsContainer){$inherit=3}\n $acl.SetAccessRuleProtection($true,$false)\n foreach($r in @($acl.Access)){$acl.PurgeAccessRules($r.IdentityReference)}\n $acl.SetAccessRule($AR::new($me,'FullControl',$inherit,'None','Allow'))\n $entry.SetAccessControl($acl)\n $actual=$entry.GetAccessControl('Access')\n $rules=@($actual.GetAccessRules($true,$true,$SID))\n if(!$actual.AreAccessRulesProtected -or $rules.Count -ne 1){throw 'acl'}\n $r=$rules[0]\n if($r.IdentityReference -ne $me -or $r.AccessControlType -ne 'Allow' -or $r.FileSystemRights -ne 2032127 -or $r.InheritanceFlags -ne $inherit -or $r.PropagationFlags -ne 0){throw 'acl'}\n}\n$parent=[IO.Path]::GetDirectoryName($p)\n$d=$parent\nwhile($d){$e=Get-Item -Force -LiteralPath $d -ErrorAction SilentlyContinue;if($e -and ($e.Attributes -band 1024)){throw 'redirected parent'};$d=[IO.Path]::GetDirectoryName($d)}\nif(!(Test-Path -LiteralPath $parent)){\n if(!$reset){throw 'missing state directory'}\n $da=[Security.AccessControl.DirectorySecurity]::new()\n $da.SetAccessRuleProtection($true,$false)\n $da.AddAccessRule($AR::new($me,'FullControl',3,0,'Allow'))\n [IO.Directory]::CreateDirectory($parent,$da)|Out-Null\n}\n$item=Get-Item -Force -LiteralPath $p -ErrorAction SilentlyContinue\nif($null -ne $item){\n if($item.PSIsContainer -or ($item.Attributes -band 1024)){throw 'type'}\n if((Owner $item) -ne $me){throw ('owner mismatch: expected '+$me.Value+', actual '+(Owner $item).Value)}\n $links=@(& \"$env:SystemRoot\\System32\\fsutil.exe\" hardlink list $p)\n if($LASTEXITCODE -ne 0 -or $links.Count -ne 1){throw 'links'}\n}\nPrivateAcl $parent\nif($reset){\n if($null -ne $item){[IO.File]::Delete($p)}\n $acl=[Security.AccessControl.FileSecurity]::new()\n $acl.SetOwner($me);$acl.SetAccessRuleProtection($true,$false)\n $acl.AddAccessRule($AR::new($me,'FullControl','Allow'))\n $stream=[IO.FileStream]::new($p,[IO.FileMode]::CreateNew,2032127,[IO.FileShare]::None,4096,[IO.FileOptions]::None,$acl)\n $stream.Dispose()\n}\nPrivateAcl $p\nexit 0\n} catch {Write-Output ('token storage: '+$_.Exception.Message);exit 1}\n"
		if _powershell_token_check(acl_script, path, reset) == 0:
			return true
	print("[mcp-bridge] FATAL: private token storage could not be verified; the bridge is OFF.")
	return false

const HASH_SHA256 := 2
const HMAC_BLOCK_BYTES := 64

func _sha256_bytes(data : PoolByteArray) -> PoolByteArray:
	var ctx = ClassDB.instance("HashingContext")
	ctx.start(HASH_SHA256)
	ctx.update(data)
	return ctx.finish()

func _hmac_sha256(key : PoolByteArray, message : PoolByteArray) -> PoolByteArray:
	var block = key
	if block.size() > HMAC_BLOCK_BYTES:
		block = _sha256_bytes(block)
	while block.size() < HMAC_BLOCK_BYTES:
		block.append(0)
	var inner := PoolByteArray()
	var outer := PoolByteArray()
	for i in range(HMAC_BLOCK_BYTES):
		inner.append(block[i] ^ 0x36)
		outer.append(block[i] ^ 0x5c)
	inner.append_array(message)
	var digest = _sha256_bytes(inner)
	outer.append_array(digest)
	return _sha256_bytes(outer)

func _proof(role : String, cnonce : String, snonce : String) -> String:
	var message = "dd-mcp/%d|%s|%s|%s" % [PROTOCOL_VERSION, role, cnonce, snonce]
	return _hmac_sha256(_token.to_utf8(), message.to_utf8()).hex_encode()

func _message_proof(role : String, c : Dictionary, payload : String) -> String:
	var message = "dd-mcp/%d|%s|%s|%s|1|%s" % [PROTOCOL_VERSION, role, c["cnonce"], c["snonce"], payload]
	return _hmac_sha256(_token.to_utf8(), message.to_utf8()).hex_encode()

func _valid_nonce(nonce) -> bool:
	if typeof(nonce) != TYPE_STRING or nonce.length() != 32:
		return false
	for i in range(nonce.length()):
		if "0123456789abcdef".find(nonce.substr(i, 1)) == -1:
			return false
	return true

func _random_hex(bytes : int) -> String:
	return _crypto.generate_random_bytes(bytes).hex_encode()

func _evaluator_port():
	var configured = OS.get_environment(EVALUATOR_PORT_ENV)
	if configured == "":
		return null
	if not configured.is_valid_integer():
		print("[mcp-bridge] invalid %s; refusing to listen" % EVALUATOR_PORT_ENV)
		return -1
	var port = int(configured)
	if port < 1024 or port > 65535:
		print("[mcp-bridge] %s must be between 1024 and 65535; refusing to listen" % EVALUATOR_PORT_ENV)
		return -1
	return port

func start():
	_token = _ensure_token()
	if _token == "":
		print("[mcp-bridge] FATAL: refusing to listen without a secure token. " +
			"The bridge is OFF for this session.")
		return

	if not ClassDB.can_instance("HashingContext"):
		print("[mcp-bridge] FATAL: this build cannot instance HashingContext, " +
			"so peers cannot be authenticated. The bridge is OFF for this session.")
		return
	_crypto = ClassDB.instance("Crypto")
	if _crypto == null:
		print("[mcp-bridge] FATAL: Crypto unavailable at start. The bridge is OFF for this session.")
		return
	_connect_signals()

	_instance_id = OS.get_ticks_usec()

	for cand in [Engine, ProjectSettings, Global.Editor, Global.World]:
		if cand != null and not cand.has_meta("mcp_first_writer"):
			cand.set_meta("mcp_first_writer", _instance_id)

	var host = Engine
	var parked = null
	if host != null and host.has_meta(META_SERVER):
		parked = host.get_meta(META_SERVER)
	if parked != null and is_instance_valid(parked) and parked.is_listening():
		_server = parked
		_port = PORT
		if host.has_meta(META_PORT):
			_port = int(host.get_meta(META_PORT))
		host.set_meta(META_OWNER, _instance_id)
		_register_tool()
		print("[mcp-bridge] adopted the existing listener on %s:%d (protocol v%d)" % [HOST, _port, PROTOCOL_VERSION])
		return

	# Nothing to adopt: bind fresh. The normal bridge scans if something outside
	# Dungeondraft holds 8787. An evaluator chooses its own port and must bind
	# exactly that port; scanning would break its ownership boundary.
	var requested_port = _evaluator_port()
	if requested_port == -1:
		_register_tool()
		return
	var bound = -1
	var attempts = 1 if requested_port != null else PORT_SCAN
	for i in range(attempts):
		var candidate = requested_port if requested_port != null else PORT + i
		var srv = TCP_Server.new()
		if srv.listen(candidate, HOST) == OK:
			_server = srv
			bound = candidate
			break

	if bound == -1:
		_server = null
		if requested_port != null:
			print("[mcp-bridge] FAILED to listen on evaluator port %d" % requested_port)
			_register_tool()
			return
		var last = PORT + PORT_SCAN - 1
		print("[mcp-bridge] FAILED to listen on any port in %d-%d" % [PORT, last])
		OS.alert("MCP bridge could not open a port in %d-%d.\nQuit and reopen Dungeondraft; if that fails, another program is holding these ports." % [PORT, last], "Battlemap MCP Bridge")
		_register_tool()
		return

	_port = bound
	if host != null:
		host.set_meta(META_SERVER, _server)
		host.set_meta(META_PORT, bound)
		host.set_meta(META_OWNER, _instance_id)
	_write_port_file(bound)
	_register_tool()
	print("[mcp-bridge] listening on %s:%d (protocol v%d)" % [HOST, bound, PROTOCOL_VERSION])

	var running_sha = _bridge_sha256()
	print("[mcp-bridge] running bridge %s" % (running_sha.substr(0, 12) if running_sha != ""
		else "(unidentified: Dungeondraft's script header was not recognised)"))
	print("[mcp-bridge] token file: %s" % _token_path())
	print("[mcp-bridge] auth: per-connection HMAC-SHA256 challenge; the token is never sent")

func _write_port_file(port : int) -> void:

	if OS.get_environment(EVALUATOR_PORT_ENV) != "":
		return
	var f = File.new()
	if f.open(_state_directory().plus_file(PORT_FILE), File.WRITE) == OK:
		f.store_string(str(port))
		f.close()
	else:
		print("[mcp-bridge] warning: could not write %s; clients will assume port %d" % [PORT_FILE, PORT])

func update(delta : float):
	if _server == null:
		return
	# Exactly one instance drains the shared listener: the one that started most
	# recently. Without this the adopted socket would be polled by every
	# instance ever created for this session.
	var host = Engine
	if host.has_meta(META_OWNER) and host.get_meta(META_OWNER) != _instance_id:
		return

	_tick_export_job()

	var now = OS.get_ticks_msec()
	var accepts := MAX_CONNS
	while accepts > 0 and _server.is_connection_available():
		accepts -= 1
		var peer = _server.take_connection()
		peer.set_no_delay(true)
		if _conns.size() >= MAX_CONNS:
			# Dropped without an error response on purpose: writing one needs
			# the very output path a flood is trying to fill.
			peer.disconnect_from_host()
			continue
		_conns.append({ "peer": peer, "buf": PoolByteArray(), "scan": 0, "authenticated": false, "out": PoolByteArray(), "sent": 0, "born": now,
			"last": now, "cnonce": "", "snonce": "", "closing": false, "bad": 0 })

	# Work per frame is bounded: this runs on the thread that draws the editor.
	var budget := MAX_REQUESTS_PER_UPDATE
	var read_budget := READ_BYTES_PER_UPDATE
	var scan_budget := READ_BYTES_PER_UPDATE
	var buffered := 0
	var still_open := []
	for c in _conns:
		var peer : StreamPeerTCP = c["peer"]
		if peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			continue

		if not c["authenticated"] and now - c["born"] > UNAUTHENTICATED_MS:
			peer.disconnect_from_host()
			continue
		var avail = min(peer.get_available_bytes(), min(READ_BYTES_PER_CONN, read_budget))
		if avail > 0 and not c["closing"]:
			c["last"] = now
			read_budget -= avail
			var res = peer.get_data(avail)
			if res[0] == OK:
				var incoming : PoolByteArray = c["buf"]
				incoming.append_array(res[1])
				c["buf"] = incoming
				if c["buf"].size() > MAX_LINE_BYTES:
					c["buf"] = PoolByteArray()
					c["closing"] = true
		# Keep raw bytes until a complete frame; UTF-8 can span socket reads.
		var mine := MAX_REQUESTS_PER_CONN_PER_UPDATE
		while c["scan"] < c["buf"].size() and budget > 0 and mine > 0 and scan_budget > 0 and not c["closing"]:
			var at = c["scan"]
			c["scan"] += 1
			scan_budget -= 1
			if c["buf"][at] != 10:
				continue
			var line = ""
			if at > 0:
				line = c["buf"].subarray(0, at - 1).get_string_from_utf8().strip_edges()
			if at + 1 >= c["buf"].size():
				c["buf"] = PoolByteArray()
			else:
				c["buf"] = c["buf"].subarray(at + 1, c["buf"].size() - 1)
			c["scan"] = 0
			# Empty and whitespace frames consume the same allowance as commands.
			budget -= 1
			mine -= 1
			if line != "":
				_handle_line(c, line)
				if c["bad"] >= MAX_AUTH_FAILURES:
					c["closing"] = true

		_flush(c)

		# A queued response the peer never reads used to be a blocking write.
		# Now it simply waits here, and these deadlines decide when to give up.
		var unauthenticated = not c["authenticated"] and now - c["born"] > UNAUTHENTICATED_MS
		var idle = now - c["last"] > IDLE_MS

		buffered += c["buf"].size() + (c["out"].size() - c["sent"])
		if (c["closing"] and c["out"].size() == 0) or unauthenticated or idle:
			peer.disconnect_from_host()
			continue
		if buffered > MAX_TOTAL_BUFFER_BYTES:
			# One peer per frame, the one that crossed the line: enough to stop
			# unbounded growth without punishing connections that behaved.
			print("[mcp-bridge] dropping a connection: buffered bytes across peers exceeded %d" % MAX_TOTAL_BUFFER_BYTES)
			peer.disconnect_from_host()
			continue
		still_open.append(c)
	# Round-robin: whoever was served first this frame goes last next frame, so
	# a busy peer cannot hold the front of the queue.
	if still_open.size() > 1:
		still_open.append(still_open.pop_front())
	_conns = still_open

# Write what the kernel will take right now and keep the rest for the next
# frame. put_data() blocks until the peer drains, which on this thread means
# the editor stops (security review 2026-09-13); put_partial_data() never does.
func _flush(c : Dictionary) -> void:
	var peer : StreamPeerTCP = c["peer"]
	var pending = c["out"].size() - c["sent"]
	if pending > 0:
		if peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			c["out"] = PoolByteArray()
			c["sent"] = 0
			return

		var last = c["sent"] + min(OUT_CHUNK_BYTES, pending) - 1
		var res = peer.put_partial_data(c["out"].subarray(c["sent"], last))
		if res[0] != OK:
			c["out"] = PoolByteArray()
			c["sent"] = 0
			c["closing"] = true
			return
		var sent = res[1]
		if sent <= 0:
			return
		c["sent"] += sent
		if c["sent"] >= c["out"].size():
			c["out"] = PoolByteArray()
			c["sent"] = 0

# ---------------------------------------------------------------------------
# Request handling
# ---------------------------------------------------------------------------

func _handle_line(c : Dictionary, line : String):
	var parsed = JSON.parse(line)
	var envelope = parsed.result
	if parsed.error != OK or typeof(envelope) != TYPE_DICTIONARY:
		_send(c, _err("invalid JSON request"))
		return
	if str(envelope.get("cmd", "")) == "hello":
		var nonce = envelope.get("nonce", "")
		if c["snonce"] != "" or envelope.get("protocol", 0) != PROTOCOL_VERSION or not _valid_nonce(nonce):
			_send(c, _err("hello requires protocol %d and a fresh 32-character hex nonce" % PROTOCOL_VERSION))
			c["closing"] = true
			return
		c["cnonce"] = nonce
		c["snonce"] = _random_hex(16)
		_send(c, _ok({ "protocol": PROTOCOL_VERSION, "nonce": c["snonce"],
			"proof": _proof("server", nonce, c["snonce"]) }))
		return
	# Diagnostic ping is only available BEFORE hello. Python always uses the
	# authenticated envelope, including for ping, and never trusts raw replies.
	if str(envelope.get("cmd", "")) == "ping" and c["snonce"] == "":
		var diagnostic_ping = _record_and_dispatch({ "cmd": "ping" })
		# Installation paths and process identity require an authenticated caller.
		diagnostic_ping.get("result", {}).erase("bridge_root")
		diagnostic_ping.get("result", {}).erase("process_id")
		_send(c, diagnostic_ping)
		return
	var body = envelope.get("payload", null)
	if c["snonce"] == "" or typeof(body) != TYPE_STRING or envelope.get("seq", 0) != 1 or c["authenticated"]:
		c["bad"] += 1
		_send(c, _err("expected an authenticated protocol %d request" % PROTOCOL_VERSION))
		return
	if str(envelope.get("auth", "")) != _message_proof("request", c, body):
		c["bad"] += 1
		_send(c, _err("bad or missing token"))
		return
	c["authenticated"] = true
	# Consume the session before dispatch: even a pipelined duplicate cannot run.
	c["closing"] = true
	parsed = JSON.parse(body)
	var req = parsed.result
	var resp : Dictionary
	if parsed.error != OK or typeof(req) != TYPE_DICTIONARY:
		resp = _err("invalid authenticated JSON request")
	elif req.has("token"):
		resp = _err("token fields are not accepted")
	else:
		if _verbose:
			print("[mcp-bridge] >>> %s %s" % [str(req.get("cmd", "?")), _log_args(req)])
		resp = _record_and_dispatch(req)
		if _verbose:
			print("[mcp-bridge] <<< %s %s" % [str(req.get("cmd", "?")), str(resp.get("ok", false))])
	var response_body = _wire_json(resp)
	_send(c, { "seq": 1, "payload": response_body, "auth": _message_proof("response", c, response_body) })

# The request minus the noise: token never, and long arrays summarised so a
# 200-point polyline does not bury the log it is supposed to make readable.
func _log_args(req : Dictionary) -> String:
	var parts := []
	for k in req.keys():
		if k == "cmd" or k == "token" or k == "auth" or k == "nonce":
			continue
		var v = req[k]
		if typeof(v) == TYPE_ARRAY and v.size() > 4:
			parts.append("%s=[%d items]" % [k, v.size()])
		else:
			parts.append("%s=%s" % [k, str(v)])
	parts.sort()
	return "{" + PoolStringArray(parts).join(" ") + "}"

func _wire_json(value) -> String:
	var body = JSON.print(value)
	var bytes = body.to_utf8()
	if not (0 in bytes):
		return body
	var escaped := PoolByteArray()
	var zero_escape = "\\u0000".to_utf8()
	for byte in bytes:
		if byte == 0:
			escaped.append_array(zero_escape)
		else:
			escaped.append(byte)
	return escaped.get_string_from_utf8()

func _send(c : Dictionary, resp : Dictionary):
	var body = _wire_json(resp)
	# Pool arrays are copy-on-write values in GDScript: c["out"].append_array()
	# would append to a temporary and drop the response on the floor. Read,
	# modify, write back.
	var out = c["out"]
	out.append_array((body + "\n").to_utf8())
	c["out"] = out
	_flush(c)

const MAP_WEAR_NAMES = ["none", "dust", "grime", "noise", "scratched"]
const MAP_WEAR_TEXTURES = ["", "res://textures/wear/dust.png", "res://textures/wear/grime.png",
	"res://textures/wear/noise.png", "res://textures/wear/scratched.png"]
const MAP_GRID_NAMES = ["dashes", "dotted", "narrow_line", "thick_line"]
const MAP_GRID_TEXTURES = ["res://textures/grid/dashes.png", "res://textures/grid/dotted_line.png",
	"res://textures/grid/narrow_line.png", "res://textures/grid/thick_line.png"]

func _record_and_dispatch(req : Dictionary) -> Dictionary:
	var cmd = req.get("cmd", "")
	_current_session = str(req.get("session", ""))

	var pre = null
	if cmd == "set_map_style":
		pre = _map_style_snapshot()
	if cmd in TRANSFORM_CMDS and req.has("id"):
		var node = Global.World.GetNodeByID(int(req["id"]))
		if node != null:
			pre = _snapshot(node)

	var pre_many = null
	if cmd == "move_elements" and typeof(req.get("ids")) == TYPE_ARRAY:
		pre_many = {}
		for raw_id in req["ids"]:
			if typeof(raw_id) != TYPE_INT and typeof(raw_id) != TYPE_REAL:
				continue
			var many_node = Global.World.GetNodeByID(int(raw_id))
			if many_node != null:
				pre_many[int(raw_id)] = _snapshot(many_node)

	# build_room paints terrain when its floor is terrain, so it changes the
	# splat as well as creating nodes; capture both or its undo is half an undo.
	var terrain_before = null
	var terrain_before2 = null
	var slots_before = null
	if cmd in TERRAIN_CMDS or (cmd == "build_room" and str(req.get("floor", "")) == "terrain"):
		var lvl = Global.World.GetCurrentLevel()
		if lvl != null:
			terrain_before = lvl.Terrain.CloneSplatImage()

			terrain_before2 = _clone_splat2(lvl)

			slots_before = _terrain_slots(lvl)

	var assign_mark = -1
	if cmd in COMPOSITE_CMDS:
		assign_mark = _assign_seq

	var cave_before = null
	if cmd in CAVE_CMDS:
		cave_before = _cave_snapshot()
		if cave_before == null: return _err("cave bitmaps unavailable or sizes do not match")

	# Resolve the node and its parent before dispatch: afterwards it is out of
	# the tree and GetNodeByID can no longer find it.
	var deleted_node = null
	var deleted_parent = null
	if cmd in DELETE_CMDS and req.has("id"):
		deleted_node = Global.World.GetNodeByID(int(req["id"]))
		if deleted_node != null:
			deleted_parent = deleted_node.get_parent()

	var deleted_many = null
	if cmd == "delete_elements" and typeof(req.get("ids")) == TYPE_ARRAY:
		deleted_many = []
		var recorded := {}
		for raw_delete_id in req["ids"]:
			if not (typeof(raw_delete_id) in [TYPE_INT, TYPE_REAL]):
				continue
			var delete_id = int(raw_delete_id)
			if recorded.has(delete_id):
				continue
			var doomed = Global.World.GetNodeByID(delete_id)
			if doomed != null:
				recorded[delete_id] = true
				deleted_many.append({ "id": delete_id, "node": doomed,
					"parent": doomed.get_parent() })

	# The Unofficial Patch claims walls and texts it has not seen on its next
	# tick; see _patch_adopt_wall. Walls the bridge adds, directly or through a
	# deferred re-attach on undo, are the ones missing from this list afterwards.
	var patch_walls_before = null
	var patch_groups_touched = 0
	if not (cmd in SAFE_DURING_SAVE) and _patch_verified():
		patch_walls_before = _patch_wall_ids()
		# 1: a group member is the target; 2: undo, redo or a save may have
		# changed or renamed members, so only if the map has groups at all.
		if _patch_touches_group(req):
			patch_groups_touched = 1
		elif cmd in ["undo", "redo", "save_map"]:
			patch_groups_touched = 2

	var result = _safe_dispatch(req)

	if patch_walls_before != null:
		# Now for what was added directly, and next frame for deferred attaches:
		# the patch polls on a timer that may fire before the deferred call.
		_patch_after_edit(patch_walls_before)
		call_deferred("_patch_after_edit", patch_walls_before, patch_groups_touched)

	if typeof(result) == TYPE_DICTIONARY and result.get("ok", false) \
			and cmd in CREATE_CMDS and typeof(result.get("result")) == TYPE_DICTIONARY \
			and result["result"].has("id"):
		if Global.World.GetNodeByID(int(result["result"]["id"])) == null:
			return _err(("%s reported id %d, but no node has that id — the " +
				"handler returned something other than what it created. This " +
				"is a bug in the bridge, not in your request.")
				% [str(cmd), int(result["result"]["id"])])

	if typeof(result) == TYPE_DICTIONARY and result.get("ok", false):
		var op = _build_op(cmd, req, result, pre, terrain_before, cave_before,
			deleted_node, deleted_parent, pre_many, assign_mark, slots_before,
			terrain_before2, deleted_many)
		if op != null:
			_push_undo(op)
		elif not (cmd in SAFE_DURING_SAVE) and not (cmd in ["undo", "redo"]) \
				and not (cmd in CHECKPOINT_CMDS):
			_note_unrecorded(str(cmd))
		_checkpoint_warning(result)

		if not (cmd in SAFE_DURING_SAVE) and not (cmd in ["undo", "redo"]) \
				and not (cmd in CHECKPOINT_CMDS):
			_discard_redo()

	if typeof(result) == TYPE_DICTIONARY and result.get("ok", false) \
			and not (cmd in SAFE_DURING_SAVE) and _save_stale_path != "" \
			and typeof(result.get("result")) == TYPE_DICTIONARY:
		result["result"]["save_warning"] = ("The last save (%s) started and " +
			"never finished, so Dungeondraft may be refusing to save at all and " +
			"this edit may exist only in memory. Call save_map: if it reports " +
			"that no save started, stop and tell the user — only a restart " +
			"recovers, and it discards unsaved work.") % _save_stale_path
	return result

# Returns an undo op for a recordable command, or null. Ops are reversed by
# _apply_op (undo=true) and re-applied (undo=false).
func _build_op(cmd, req, result, pre, terrain_before, cave_before = null,
		deleted_node = null, deleted_parent = null, pre_many = null,
		assign_mark : int = -1, slots_before = null, terrain_before2 = null,
		deleted_many = null):
	if cmd in CREATE_CMDS:
		var id = result["result"].get("id", -1)
		if id != null and int(id) >= 0:
			var node = Global.World.GetNodeByID(int(id))
			if node != null:
				return { "kind": "create", "node": node, "parent": node.get_parent(), "id": int(id) }
	elif cmd == "delete_elements":
		if deleted_many != null and not deleted_many.empty():
			return { "kind": "delete_many", "entries": deleted_many }
	elif cmd in DELETE_CMDS:
		if deleted_node != null:
			return { "kind": "delete", "node": deleted_node, "parent": deleted_parent,
				"id": int(req["id"]) }
	elif cmd == "set_map_style" and pre != null:
		var after = _map_style_snapshot()
		if after != null and pre != after:
			return { "kind": "map_style", "before": pre, "after": after }
	elif cmd in TRANSFORM_CMDS and pre != null:
		var node = Global.World.GetNodeByID(int(req["id"]))
		if node != null:
			return { "kind": "transform", "id": int(req["id"]), "old": pre, "new": _snapshot(node) }
	elif cmd in TERRAIN_CMDS and terrain_before != null:
		var lvl = Global.World.GetCurrentLevel()
		if lvl != null:

			return { "kind": "terrain", "level": int(lvl.ID), "before": terrain_before,
				"after": lvl.Terrain.CloneSplatImage(),
				"before2": terrain_before2, "after2": _clone_splat2(lvl),
				"slots_before": slots_before, "slots_after": _terrain_slots(lvl) }
	elif cmd in CAVE_CMDS and cave_before != null:
		if cmd == "set_cave_entrance" and result["result"].get("changed_cells", 0) == 0: return null
		var after = _cave_snapshot()
		if after != null:
			var cave_lvl = Global.World.GetCurrentLevel()
			return { "kind": "cave", "level": (int(cave_lvl.ID) if cave_lvl != null else -1),
				"before": cave_before, "after": after }
	elif cmd in COMPOSITE_CMDS and assign_mark >= 0:

		var entries := []

		for made_id in _assigned_since(assign_mark, ASSIGN_LOG_MAX):
			var made = Global.World.GetNodeByID(int(made_id))
			if made != null:
				entries.append({ "id": int(made_id), "node": made, "parent": made.get_parent() })
		var group := { "kind": "group", "cmd": cmd, "entries": entries }
		if terrain_before != null:
			var glvl = Global.World.GetCurrentLevel()
			if glvl != null:
				group["level"] = int(glvl.ID)
				group["terrain_before"] = terrain_before
				group["terrain_after"] = glvl.Terrain.CloneSplatImage()
				group["terrain_before2"] = terrain_before2
				group["terrain_after2"] = _clone_splat2(glvl)
				group["slots_before"] = slots_before
				group["slots_after"] = _terrain_slots(glvl)
		if entries.empty() and not group.has("terrain_before"):
			return null
		return group
	elif cmd == "move_elements" and pre_many != null:
		var entries := []
		for mid in result["result"].get("moved", []):
			var moved_node = Global.World.GetNodeByID(int(mid))
			if moved_node != null and pre_many.has(int(mid)):
				entries.append({ "id": int(mid), "old": pre_many[int(mid)],
					"new": _snapshot(moved_node) })
		if not entries.empty():
			return { "kind": "transform_many", "entries": entries }
	return null

func _do_undo() -> Dictionary:
	if _undo_stack.empty():
		return _ok({ "undone": false, "reason": "nothing to undo" })
	var blocked = _wall_merge_history_error(_undo_stack.back(), true)
	if blocked == "": blocked = _cave_history_error(_undo_stack.back())
	if blocked == "": blocked = _prop_detach_history_error(_undo_stack.back(), true)
	if blocked != "": return _err(blocked)
	var op = _undo_stack.pop_back()
	_apply_op(op, true)
	_redo_stack.append(op)
	return _ok({ "undone": true, "kind": op["kind"], "undo_depth": _undo_stack.size() })

func _do_redo() -> Dictionary:
	if _redo_stack.empty():
		return _ok({ "redone": false, "reason": "nothing to redo" })
	var blocked = _wall_merge_history_error(_redo_stack.back(), false)
	if blocked == "": blocked = _cave_history_error(_redo_stack.back())
	if blocked == "": blocked = _prop_detach_history_error(_redo_stack.back(), false)
	if blocked != "": return _err(blocked)
	var op = _redo_stack.pop_back()
	_apply_op(op, false)
	_push_undo(op)
	return _ok({ "redone": true, "kind": op["kind"], "redo_depth": _redo_stack.size() })

func _release_op(op):
	if typeof(op) != TYPE_DICTIONARY:
		return
	if op.get("kind") == "wall_merge":
		var absorbed = op.get("absorbed")
		if is_instance_valid(absorbed) and absorbed.get_parent() == null and not _held_by_wall_merge(absorbed, op):
			absorbed.queue_free()
		return
	if op.get("kind") in ["group", "delete_many"]:
		for entry in op.get("entries", []):
			var held = entry.get("node")
			if is_instance_valid(held) and held.get_parent() == null and not _held_by_wall_merge(held, op):
				held.queue_free()
		return
	if not (op.get("kind") in ["create", "delete"]):
		return
	var node = op.get("node")
	if is_instance_valid(node) and node.get_parent() == null and not _held_by_wall_merge(node, op):
		node.queue_free()

func _push_undo(op):
	_op_serial += 1
	op["serial"] = _op_serial
	# A redo re-pushes the original op, which keeps the session that made it.
	if not op.has("session"):
		op["session"] = _current_session
	_undo_stack.append(op)
	while _undo_stack.size() > MAX_UNDO_OPS:
		var evicted = _undo_stack.pop_front()
		_lost_serial = int(max(_lost_serial, int(evicted.get("serial", 0))))
		_release_op(evicted)
	_trim_snapshot_ops()

# Drop the oldest image-holding ops once their snapshots pass the budget. Undo
# still steps back through the rest in order; it just cannot reach terrain or
# cave edits older than that.
func _holds_snapshot(op) -> bool:
	return typeof(op) == TYPE_DICTIONARY and (op.get("kind") in ["terrain", "cave"] \
		or (op.get("kind") == "group" and op.has("terrain_before")))

func _image_bytes(value) -> int:
	if value is Image:
		return value.get_width() * value.get_height() * 4
	if value is BitMap:
		var size = value.get_size()
		return int(size.x * size.y / 8) + 1
	return 0

func _snapshot_bytes(op) -> int:
	var total := 0
	for key in ["before", "after", "before2", "after2", "terrain_before", "terrain_before2"]:
		total += _image_bytes(op.get(key))
	for key in ["before", "after"]:
		var cave = op.get(key)
		if typeof(cave) == TYPE_DICTIONARY:
			total += _image_bytes(cave.get("floor")) + _image_bytes(cave.get("entrances"))
	return total

func _snapshot_op_count() -> int:
	var n := 0
	for op in _undo_stack:
		if _holds_snapshot(op): n += 1
	return n

func _snapshot_total_bytes() -> int:
	var total := 0
	for op in _undo_stack:
		if _holds_snapshot(op): total += _snapshot_bytes(op)
	return total

func _trim_snapshot_ops() -> void:
	var held := 0
	var i := _undo_stack.size() - 1
	while i >= 0:
		var op = _undo_stack[i]
		if _holds_snapshot(op):
			held += _snapshot_bytes(op)
			if held > SNAPSHOT_BUDGET_BYTES:
				_lost_serial = int(max(_lost_serial, int(op.get("serial", 0))))
				_release_op(op)
				_undo_stack.remove(i)
		i -= 1

func _discard_redo():
	for op in _redo_stack:
		_release_op(op)
	_redo_stack = []

func _apply_op(op, undo : bool):
	match op["kind"]:
		"create":
			if undo:
				_detach_node(op["node"], int(op["id"]))
			else:
				_attach_node(op["node"], op["parent"], int(op["id"]))
		"delete":
			if undo:
				_attach_node(op["node"], op["parent"], int(op["id"]))
			else:
				_detach_node(op["node"], int(op["id"]))
		"transform":
			_apply_props(Global.World.GetNodeByID(int(op["id"])), op["old"] if undo else op["new"])
		"wall_merge":
			_apply_wall_merge(op, undo)
		"transform_many":
			for entry in op["entries"]:
				_apply_props(Global.World.GetNodeByID(int(entry["id"])),
					entry["old"] if undo else entry["new"])
		"map_style":
			_restore_map_style(op["before"] if undo else op["after"])
		"terrain":
			_restore_terrain_slots(op.get("slots_before") if undo else op.get("slots_after"),
				int(op.get("level", -1)))
			_restore_splat(op["before"] if undo else op["after"],
				op.get("before2") if undo else op.get("after2"), int(op.get("level", -1)))
		"delete_many":
			# Mirror of "group": the delete already happened, so undo puts them
			# back and redo takes them out again, children-first on the way out.
			if undo:
				for restored in op["entries"]:
					_attach_node(restored["node"], restored["parent"], int(restored["id"]))
			else:
				var gone := op["entries"].size() - 1
				while gone >= 0:
					var redone_delete = op["entries"][gone]
					_detach_node(redone_delete["node"], int(redone_delete["id"]))
					gone -= 1
		"group":
			if undo:
				# Reverse order: a composite's later nodes may sit inside earlier ones.
				var back := op["entries"].size() - 1
				while back >= 0:
					var undone = op["entries"][back]
					_detach_node(undone["node"], int(undone["id"]))
					back -= 1
				if op.has("terrain_before"):
					_restore_terrain_slots(op.get("slots_before"), int(op.get("level", -1)))
					_restore_splat(op["terrain_before"], op.get("terrain_before2"),
						int(op.get("level", -1)))
			else:
				for redone in op["entries"]:
					_attach_node(redone["node"], redone["parent"], int(redone["id"]))
				if op.has("terrain_after"):
					_restore_terrain_slots(op.get("slots_after"), int(op.get("level", -1)))
					_restore_splat(op["terrain_after"], op.get("terrain_after2"),
						int(op.get("level", -1)))
		"cave":
			_restore_cave(op["before"] if undo else op["after"], int(op.get("level", -1)))

func _detach_node(node, id : int):

	if _select_tool_enabled and Global.Editor.Tools.has("SelectTool"):
		var stool = Global.Editor.Tools["SelectTool"]
		if stool.has_method("DeselectAll"):
			stool.DeselectAll()

	if is_instance_valid(node) and node.get_parent() != null:
		# Props release their texture on leaving the tree. Keep the resource and
		# appearance with the detached node so undo/redo can restore them.
		if node is Node2D and Global.Editor.Tools["SelectTool"].GetSelectableType(node) == 4:
			if node.has_method("Save") and node.has_method("Load"):
				node.set_meta("mcp_detached_prop", node.Save(false))
				node.set_meta("mcp_detached_appearance", _snapshot(node))
				node.set_meta("mcp_detached_renderers", _prop_renderers(node))
		node.get_parent().call_deferred("remove_child", node)
		if node.has_meta("mcp_detached_renderers"):
			call_deferred("_release_detached_prop_renderers", node)
	if Global.World.HasNodeID(id):
		Global.World.RemoveNodeID(id)

func _attach_node(node, parent, id : int, refresh : bool = true):
	if not is_instance_valid(node):
		return
	# Deferred for the same reason as _detach_node: add_child is refused while
	# the parent is mid-setup, and the failure is not graceful.
	if node.get_parent() == null and is_instance_valid(parent):
		parent.call_deferred("add_child", node)
		if node.has_meta("mcp_detached_prop"):
			call_deferred("_restore_detached_prop", node, id)

		if parent.has_method("AddToSearchTable"):
			parent.call_deferred("AddToSearchTable", node, false)
	Global.World.SetNodeID(node, id)
	if refresh and node.has_method("RemakeLines"):
		node.RemakeLines()

func _prop_detach_error(node) -> String:
	if not is_instance_valid(node) or not (node is Node2D): return ""
	if Global.Editor.Tools["SelectTool"].GetSelectableType(node) != 4: return ""
	if not node.has_method("Save") or not node.has_method("Load"):
		return "cannot safely detach this object: native save/load is unavailable. No changes were made."
	var renderers = _prop_renderers(node)
	if renderers.size() != 2:
		return "cannot safely identify this object's renderers for undo. No changes were made."
	for renderer in renderers:
		if not is_instance_valid(renderer) or not (renderer is Sprite) or renderer.get_parent() != node:
			return "cannot safely identify this object's renderers for undo. No changes were made."
	return ""

func _prop_detach_history_error(op, undoing : bool) -> String:
	var kind = str(op.get("kind", ""))
	if (kind == "create" and undoing) or (kind == "delete" and not undoing):
		return _prop_detach_error(op["node"])
	if (kind == "group" and undoing) or (kind == "delete_many" and not undoing):
		for entry in op["entries"]:
			var blocked = _prop_detach_error(entry["node"])
			if blocked != "": return blocked
	return ""

func _prop_renderers(node) -> Array:
	# Prop creates fresh main/shadow sprites on every tree entry, but leaves
	# the previous pair behind on exit. Identify the private shadow through
	# its public visibility setter, without relying on child order or names.
	var main = node.get("Sprite")
	var before = {}
	for child in node.get_children():
		if child is Sprite: before[child] = child.visible
	var had_shadow = bool(node.get("HasShadow"))
	node.set("HasShadow", not had_shadow)
	var changed = []
	for child in before:
		if child.visible != before[child]: changed.append(child)
	node.set("HasShadow", had_shadow)
	if changed.size() != 1 or changed[0] == main or main == null:
		return []
	return [main, changed[0]]

func _release_detached_prop_renderers(node):
	if not is_instance_valid(node) or node.get_parent() != null: return
	for renderer in node.get_meta("mcp_detached_renderers"):
		if is_instance_valid(renderer) and renderer.get_parent() == node:
			node.remove_child(renderer)
			renderer.free()
	node.remove_meta("mcp_detached_renderers")

func _restore_detached_prop(node, id : int):
	if not is_instance_valid(node) or not node.is_inside_tree():
		return
	if not node.has_meta("mcp_detached_prop") or not node.has_method("Load"):
		return
	# The native loader restores both the asset reference and baked custom color.
	node.Load(node.get_meta("mcp_detached_prop"))
	# Load allocates a fresh registry ID even when restoring an existing node.
	var loaded_id = _node_id_or(node, -1)
	if loaded_id != id and Global.World.HasNodeID(loaded_id):
		Global.World.RemoveNodeID(loaded_id)
	Global.World.SetNodeID(node, id)
	node.set_meta("node_id", id)
	_apply_props(node, node.get_meta("mcp_detached_appearance"))
	node.remove_meta("mcp_detached_prop")
	node.remove_meta("mcp_detached_appearance")

func _apply_props(node, snap):
	if node == null or snap == null:
		return
	if snap.get("position") != null:
		node.position = snap["position"]
	if snap.get("rotation") != null:
		node.rotation = snap["rotation"]
	if snap.get("scale") != null:
		node.scale = snap["scale"]
	if snap.get("transform") != null:
		node.transform = snap["transform"]
		_patch_write_shear(node)
	if snap.get("z_index") != null:
		node.z_index = int(snap["z_index"])
	if snap.get("rect_position") != null:
		node.set("rect_position", snap["rect_position"])
	if snap.has("portal_direction"): node.Direction = snap["portal_direction"]
	if snap.has("wall_points"):
		node.Points = PoolVector2Array(snap["wall_points"])
		for entry in snap["wall_portals"]:
			var portal = Global.World.GetNodeByID(int(entry["id"]))
			if portal != null:
				portal.position = entry["position"]
				portal.rotation = entry["rotation"]
				portal.Direction = entry["direction"]
		node.RemakeLines()
	if snap.get("block_light") != null:
		# Through the same helper, so undo goes through the occluder lifecycle
		# rather than setting a property the occluders then contradict.
		_apply_block_light(node, bool(snap["block_light"]))
	if snap.get("shadow") != null:
		node.set("HasShadow", snap["shadow"])
	if snap.get("color") != null:

		_set_node_color(node, snap["color"])
	if snap.get("modulate") != null:
		# Same best-effort rationale as the colour restore above.
		_set_node_modulate(node, snap["modulate"])

func _generate_dungeon(req : Dictionary) -> Dictionary:
	if not Global.Editor.Tools.has("Generator"):
		return _err("this build exposes no Generator tool")
	var gen = Global.Editor.Tools["Generator"]
	if not gen.has_method("Generate"):
		return _err("Generator exposes no Generate on this Dungeondraft build")

	var design = str(req.get("design", ""))
	var switched = ""
	if design != "":
		if not (design in ["Dungeon", "Cave"]):
			return _err("'design' must be \"Dungeon\" or \"Cave\", got: " + design)
		switched = _set_wizard_design(design)
		if switched != "":
			return _err(switched)

	var before = _generated_counts()
	# Enable FIRST, then set the pickers: Enable() resets the wizard panel, so
	# anything chosen before it is discarded. The sliders are unaffected — they
	# survive and take effect — which is why only the texture pickers need this.
	var mark := _assign_mark()
	var gen_active := _enable_tool("Generator", gen)
	var applied := {}
	if req.has("wall"):
		applied["wall"] = _apply_picker("Wall", int(req["wall"]), gen)
	if req.has("floor"):
		applied["floor"] = _apply_picker("Floor", int(req["floor"]), gen)
	gen.Generate()
	_release_tool(gen, gen_active)
	var after = _generated_counts()
	# A generated dungeon is thousands of nodes; report a capped sample plus the
	# marker, so a caller who wants them all can page with get_recent_nodes.
	var created := _assigned_since(mark, 200)
	return _ok({ "design": _current_wizard_design(), "before": before,
		"after": after, "applied": applied,
		"ids": created, "ids_since": mark, "ids_truncated": created.size() >= 200,
		"note": "replaces the level's layout; run it on an empty map before " +
			"placing anything by hand" })

func _apply_picker(name : String, idx : int, gen) -> String:
	var rows = _wizard_rows()
	if not rows.has(name):

		for k in rows.keys():
			if str(k).to_lower() == name.to_lower():
				name = k
				break
	if not rows.has(name):

		return ("no '" + name + "' picker available for the " +
			_current_wizard_design() + " design; available: " + str(rows.keys()))
	var control = rows[name]
	if not (control is ItemList):
		return "'" + name + "' is not a texture picker"
	var count = control.get_item_count()
	if idx < 0 or idx >= count:
		return "index %d out of range (0-%d)" % [idx, count - 1]
	control.select(idx)
	control.emit_signal("item_selected", idx)
	var meta = control.get_item_metadata(idx)
	if gen == null:
		return "selected %d (no Generator to apply it to)" % idx
	if typeof(meta) == TYPE_STRING and str(meta) != "":
		var category = "Walls" if name == "Wall" else "Terrain"
		var tex = _asset_tex(category, str(meta))
		if tex == null:
			tex = load(str(meta))
		if tex != null and gen.has_method("ChangeTexture"):
			gen.ChangeTexture(tex)
			return str(meta)
	if gen.has_method("ChangeTileset"):
		gen.ChangeTileset(idx)
		return "tileset %d" % idx
	return "selected %d, no setter available" % idx

# Press the Map Wizard's Dungeon/Cave radio. Returns "" on success or an error
# string. Matched on the button's visible text, which is stable; the node names
# are autogenerated and are not.
func _set_wizard_design(design : String) -> String:
	var box = _wizard_design_box(design)
	if box == null:
		return "could not find a '" + design + "' option in the Map Wizard panel"
	if not box.has_method("set_pressed"):
		return "the '" + design + "' option is not a pressable control"
	box.set_pressed(true)

	box.emit_signal("toggled", true)
	box.emit_signal("pressed")
	if Global.Editor.Tools.has("Generator"):
		var gen = Global.Editor.Tools["Generator"]
		if gen.has_method("OnDesignChange"):
			gen.OnDesignChange(design)
	if not box.pressed:
		return "pressing '" + design + "' did not take"
	return ""

func _generator_options(req : Dictionary) -> Dictionary:
	var panel = Global.Editor.get("MapWizardPanel")
	if panel == null:
		return _err("no MapWizardPanel on this build")
	var gen = null
	if Global.Editor.Tools.has("Generator"):
		gen = Global.Editor.Tools["Generator"]
	var rows = _wizard_rows()

	if req.has("name"):
		var name = str(req["name"])
		if not rows.has(name):
			return _err("no '%s' dial in the Map Wizard; available: %s" % [name, str(rows.keys())])
		if not req.has("value"):
			return _err("'value' is required when setting a dial")
		var control = rows[name]

		if control is ItemList:
			return _err(("'%s' cannot be set on its own: Generator.Enable() " +
				"resets the wizard panel and discards it. Pass floor= or wall= " +
				"to generate_dungeon, which applies the choice after enabling " +
				"the tool.") % name)

		var v = float(req["value"])
		var lo = float(control.min_value)
		var hi = float(control.max_value)
		if v < lo or v > hi:
			return _err("'%s' must be between %s and %s" % [name, str(lo), str(hi)])
		control.set_value(v)
		# value_changed is what the wizard listens to, and set_value does emit it.
		return _ok({ "name": name, "kind": "number", "value": control.value,
			"min": lo, "max": hi })

	var out := {}
	for name in rows.keys():
		var c = rows[name]
		if c is ItemList:
			var sel = -1
			var picked = c.get_selected_items()
			if picked.size() > 0:
				sel = picked[0]
			out[name] = { "kind": "list", "selected": sel,
				"count": c.get_item_count() }
		else:
			out[name] = { "kind": "number", "value": c.value, "min": c.min_value,
				"max": c.max_value, "step": c.step }
	return _ok({ "design": _current_wizard_design(), "dials": out })

# label text -> the Range control that follows it.
func _wizard_rows() -> Dictionary:
	var out := {}
	var panel = Global.Editor.get("MapWizardPanel")
	if panel == null:
		return out
	var align = null
	for child in panel.get_children():
		if child.get_child_count() > 0:
			align = child
			break
	if align == null:
		return out
	_collect_rows(align, out)
	return out

func _collect_rows(node, out : Dictionary) -> void:
	var pending = ""
	for child in node.get_children():
		if child is Label:
			# Stored as written but matched case-insensitively downstream; see
			# _wizard_design_box for why casing is not stable across versions.
			pending = str(child.get_text())
			continue
		# Only claim a control when a label is waiting for one.
		if pending != "":
			var control = _first_control(child)
			if control != null:
				# Skip rows the current design hides. Cave hides the Floor and
				# Wall pickers, and listing them there advertised five dials on a
				# panel showing three — two of which do nothing for that design.
				if _row_visible(child):
					out[pending] = control
				pending = ""
				continue

		if child.get_child_count() > 0:
			_collect_rows(child, out)

# Is this row on screen? Walks up to the Map Wizard panel rather than calling
# is_visible_in_tree(), which also reports false whenever the panel itself is
# closed — that would empty the listing instead of filtering it.
func _row_visible(node) -> bool:
	var panel = Global.Editor.get("MapWizardPanel")
	var cur = node
	while cur != null and cur != panel:
		if cur is CanvasItem and not cur.visible:
			return false
		cur = cur.get_parent()
	return true

func _first_control(node):
	if node is Range or node is ItemList:
		return node
	for child in node.get_children():
		var found = _first_control(child)
		if found != null:
			return found
	return null

func _current_wizard_design() -> String:
	for name in ["Dungeon", "Cave"]:
		var box = _wizard_design_box(name)
		if box != null and box.pressed:
			return name
	return "unknown"

func _wizard_design_box(label : String):
	if Global.Editor == null:
		return null
	var panel = Global.Editor.get("MapWizardPanel")
	if panel == null or not panel.has_method("get_children"):
		return null
	# Depth-first, but the panel is shallow and this only looks for CheckBoxes.
	var queue := [panel]
	var seen := 0
	while queue.size() > 0 and seen < 400:
		var node = queue.pop_front()
		for child in node.get_children():
			seen += 1

			if child is CheckBox and str(child.get_text()).to_lower() == label.to_lower():
				return child
			if child.get_child_count() > 0:
				queue.append(child)
	return null

# What the generator is expected to move, so its response can show it did
# something rather than just reporting that the call returned.
func _generated_counts() -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null:
		return {}
	return {
		"walls": _collection(level, "walls").get_child_count(),
		"objects": _collection(level, "objects").get_child_count(),
	}

func _set_verbose(req : Dictionary) -> Dictionary:
	_verbose = bool(req.get("on", true))
	print("[mcp-bridge] verbose logging %s" % ("on" if _verbose else "off"))
	return _ok({ "verbose": _verbose })

# Write a caller-supplied line into Dungeondraft's log, to separate phases of a
# test run so engine output can be attributed to the phase that caused it.
func _log_marker(req : Dictionary) -> Dictionary:
	var text = str(req.get("text", ""))
	print("[mcp-bridge] ===== %s =====" % text)
	return _ok({ "logged": text })

func _set_terrain_blending(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	if level.Terrain == null or not level.Terrain.has_method("SetSmoothBlending"):
		return _err("this build exposes no Terrain.SetSmoothBlending")
	if not req.has("enabled"):
		return _err("'enabled' is required: true for smooth blending, false for textured")
	var enabled = bool(req["enabled"])
	level.Terrain.SetSmoothBlending(enabled)
	level.Terrain.UpdateSplat()
	var now = enabled
	if level.Terrain.has_method("get_SmoothBlending"):
		now = bool(level.Terrain.get_SmoothBlending())
	if now != enabled:
		return _err("SetSmoothBlending(%s) did not take: it reads back %s"
			% [str(enabled), str(now)])
	return _ok({ "smooth_blending": now })

func _set_trace_image(req : Dictionary) -> Dictionary:
	if not Global.Editor.Tools.has("TraceImage"):
		return _err("this build exposes no TraceImage tool")
	var trace = Global.Editor.Tools["TraceImage"]
	var was_active := _enable_tool("TraceImage", trace)
	var applied := {}
	if str(req.get("path", "")) != "":
		var path = str(req["path"])
		var probe = File.new()
		if not probe.file_exists(path):
			_release_tool(trace, was_active)

			return _err(("Dungeondraft cannot open %s (%d characters). Either " +
				"nothing is there, or it cannot be read from here; on Windows a " +
				"path over 260 characters cannot be opened, so copy the image " +
				"somewhere shorter. Pass an absolute path to an image on this " +
				"machine.") % [path, path.length()])
		if not trace.has_method("OnFileSelected"):
			_release_tool(trace, was_active)
			return _err("this build exposes no TraceImage.OnFileSelected")
		trace.OnFileSelected("Image", path)
		applied["path"] = path

		_set_trace_visible(true)
	if bool(req.get("clear", false)) and trace.has_method("OnFileCleared"):
		trace.OnFileCleared("Image")
		applied["cleared"] = true
		_set_trace_visible(false)
	if req.has("scale") and trace.has_method("SetScale"):
		trace.SetScale(float(req["scale"]))
		applied["scale"] = float(req["scale"])
	if req.has("opacity") and trace.has_method("SetOpacity"):
		trace.SetOpacity(float(req["opacity"]))
		applied["opacity"] = float(req["opacity"])
	if bool(req.get("center", false)) and trace.has_method("Center"):
		trace.Center()
		applied["centered"] = true
	_release_tool(trace, was_active)
	if applied.empty():
		return _err("give at least one of path, scale, opacity, center or clear")
	# Read back what is drawn, not what was asked: the Sprite, not the flag.
	var sprite = Global.World.get("TraceImage")
	var drawn := false
	var size = null
	if sprite != null and is_instance_valid(sprite) and sprite is Sprite:
		drawn = sprite.is_visible_in_tree() and sprite.texture != null
		if sprite.texture != null:
			size = [sprite.texture.get_width(), sprite.texture.get_height()]
	applied["visible"] = drawn
	applied["image_size"] = size
	return _ok(applied)

func _set_trace_visible(value : bool) -> void:
	if Global.World.has_method("set_TraceImageVisible"):
		Global.World.set_TraceImageVisible(value)
	var sprite = Global.World.get("TraceImage")
	if sprite != null and is_instance_valid(sprite) and sprite is CanvasItem:
		sprite.visible = value

func _map_style_snapshot():
	if Global.World.GetCurrentLevel() == null: return null
	var grid = Global.World.get("GridMesh")
	if grid == null: return null
	return { "wear": Global.World.get("BuildingWear"), "grid": grid.texture }

func _get_map_style() -> Dictionary:
	var snap = _map_style_snapshot()
	if snap == null: return _err("no map with a grid is open")
	var wear_path = "" if snap["wear"] == null else str(snap["wear"].resource_path)
	var grid_path = "" if snap["grid"] == null else str(snap["grid"].resource_path)
	var wi = MAP_WEAR_TEXTURES.find(wear_path)
	var gi = MAP_GRID_TEXTURES.find(grid_path)
	return _ok({ "scope": "map",
		"building_wear": MAP_WEAR_NAMES[wi] if wi >= 0 else null,
		"grid_style": MAP_GRID_NAMES[gi] if gi >= 0 else null,
		"building_wear_texture": wear_path, "grid_texture": grid_path,
		"options": { "building_wear": MAP_WEAR_NAMES, "grid_style": MAP_GRID_NAMES } })

func _restore_map_style(snap):
	if snap == null or Global.World.GetCurrentLevel() == null: return
	var grid = Global.World.get("GridMesh")
	if grid == null: return
	var settings = Global.Editor.Tools["MapSettings"]
	var was_active := _enable_tool("MapSettings", settings)
	Global.World.SetBuildingWear(snap["wear"])
	grid.texture = snap["grid"]
	settings.UpdateStyleFromWorld()
	_release_tool(settings, was_active)

func _set_map_style(req : Dictionary) -> Dictionary:
	var before = _map_style_snapshot()
	if before == null: return _err("no map with a grid is open")
	if not Global.Editor.Tools.has("MapSettings"):
		return _err("this build exposes no MapSettings tool")
	var settings = Global.Editor.Tools["MapSettings"]
	if not settings.has_method("SetBuildingWear") or not settings.has_method("SetGridStyle") \
			or not settings.has_method("UpdateStyleFromWorld") or not Global.World.has_method("SetBuildingWear"):
		return _err("this build cannot apply and restore map styles")
	if not req.has("building_wear") and not req.has("grid_style"):
		return _err("give at least one of building_wear or grid_style")
	# Validate the entire request before the first mutation.
	var wi = -1
	var gi = -1
	if req.has("building_wear"):
		wi = MAP_WEAR_NAMES.find(req.get("building_wear"))
		if wi < 0: return _err("building_wear must be one of: " + str(MAP_WEAR_NAMES))
	if req.has("grid_style"):
		gi = MAP_GRID_NAMES.find(req.get("grid_style"))
		if gi < 0: return _err("grid_style must be one of: " + str(MAP_GRID_NAMES))
	var was_active := _enable_tool("MapSettings", settings)
	if wi >= 0: settings.SetBuildingWear(wi)
	if gi >= 0: settings.SetGridStyle(gi)
	var out = _get_map_style()
	_release_tool(settings, was_active)
	if not out.get("ok", false) or \
			(wi >= 0 and out["result"].get("building_wear") != req.get("building_wear")) or \
			(gi >= 0 and out["result"].get("grid_style") != req.get("grid_style")):
		_restore_map_style(before)
		return _err("map style readback did not match; previous textures restored")
	return out

func _set_water_style(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var water = level.get("WaterMesh")
	if water == null:
		return _err("this level exposes no WaterMesh")
	if not water.has_method("Save") or not water.has_method("Load") \
			or not water.has_method("UpdateMesh"):
		return _err("this build's WaterMesh cannot be restyled (no Save/Load/UpdateMesh)")
	var bad_water_color = _bad_color(req, ["deep_color", "shallow_color"])
	if bad_water_color != null: return bad_water_color
	var blend = null
	if req.has("blend_distance"):
		blend = float(req["blend_distance"])
		if blend < 0.0:
			return _err("'blend_distance' cannot be negative")
	var deep = null
	if str(req.get("deep_color", "")) != "":
		deep = _color(req["deep_color"], Color(0.09, 0.19, 0.33))
	var shallow = null
	if str(req.get("shallow_color", "")) != "":
		shallow = _color(req["shallow_color"], Color(0.25, 0.45, 0.5))
	# The mesh-level values are what Dungeondraft's own WaterBrush sets, so keep
	# them in step; they are not what saves (see _recolour_water).
	if deep != null: water.set("DeepColor", deep)
	if shallow != null: water.set("ShallowColor", shallow)
	if blend != null: water.set("BlendDistance", blend)
	if req.has("border"):
		if water.has_method("DisableBorder"):
			water.DisableBorder(not bool(req["border"]))
		else:
			water.set("disableBorder", not bool(req["border"]))

	var bodies = _recolour_water(water, deep, shallow, blend, {})
	if bodies < 0:
		return _err("could not read this level's water to restyle it")
	var out = _water_style_readback(water)
	out["bodies_restyled"] = bodies
	return _ok(out)

func _recolour_water(water, deep, shallow, blend, keep : Dictionary) -> int:
	var data = water.Save()
	if typeof(data) != TYPE_DICTIONARY or typeof(data.get("tree")) != TYPE_DICTIONARY:
		return -1
	var count = _recolour_water_node(data["tree"], deep, shallow, blend, keep, true)
	if count > 0:
		water.Load(data)
	water.UpdateMesh(false)
	return count

func _recolour_water_node(node : Dictionary, deep, shallow, blend, keep : Dictionary, root : bool) -> int:
	var count := 0
	# The root is a container with an empty polygon and zeroed colours in every
	# saved map; it is not a body and is left exactly as Dungeondraft wrote it.
	if not root and not keep.has(node.get("ref")):
		if deep != null: node["deep_color"] = deep.to_html(true)
		if shallow != null: node["shallow_color"] = shallow.to_html(true)
		if blend != null: node["blend_distance"] = blend
		count += 1
	var children = node.get("children", [])
	if typeof(children) == TYPE_ARRAY:
		for child in children:
			if typeof(child) == TYPE_DICTIONARY:
				count += _recolour_water_node(child, deep, shallow, blend, keep, false)
	return count

# Every body's style, keyed by ref, from what will actually be saved.
func _water_bodies(water) -> Dictionary:
	var out := {}
	var data = water.Save()
	if typeof(data) == TYPE_DICTIONARY and typeof(data.get("tree")) == TYPE_DICTIONARY:
		_collect_water_bodies(data["tree"], out, true)
	return out

func _collect_water_bodies(node : Dictionary, out : Dictionary, root : bool) -> void:
	if not root:
		out[node.get("ref")] = [str(node.get("deep_color", "")),
			str(node.get("shallow_color", "")), float(node.get("blend_distance", 0.0))]
	var children = node.get("children", [])
	if typeof(children) == TYPE_ARRAY:
		for child in children:
			if typeof(child) == TYPE_DICTIONARY:
				_collect_water_bodies(child, out, false)

# Read the style back off the bodies, because they are what saves. A level
# whose bodies disagree reports that rather than one of them.
func _water_style_readback(water) -> Dictionary:
	var out := {}
	var bodies = _water_bodies(water)
	out["bodies"] = bodies.size()
	var styles := {}
	for ref in bodies:
		styles[str(bodies[ref])] = bodies[ref]
	if styles.size() == 1:
		var only = styles.values()[0]
		out["deep_color"] = "#" + Color(only[0]).to_html(false)
		out["shallow_color"] = "#" + Color(only[1]).to_html(false)
		out["blend_distance"] = only[2]
	elif styles.size() > 1:
		out["mixed_styles"] = styles.size()
	else:
		# No water yet: report what the mesh holds, which is what the bridge
		# will give the next body drawn on this level.
		var deep = water.get("DeepColor")
		if deep is Color: out["deep_color"] = "#" + deep.to_html(false)
		var shallow = water.get("ShallowColor")
		if shallow is Color: out["shallow_color"] = "#" + shallow.to_html(false)
		var blend_now = water.get("BlendDistance")
		if blend_now != null: out["blend_distance"] = float(blend_now)
	var no_border = water.get("disableBorder")
	if no_border != null: out["border"] = not bool(no_border)
	return out

func _get_terrain(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	if level.Terrain == null or not level.Terrain.has_method("CloneSplatImage"):
		return _err("this build exposes no Terrain.CloneSplatImage")
	var img = level.Terrain.CloneSplatImage()
	if img == null: return _err("CloneSplatImage returned nothing")

	var iw = img.get_width()
	var ih = img.get_height()
	if iw <= 0 or ih <= 0:
		return _err("splat image is empty")

	var dims = Global.World.WoxelDimensions
	var x0 = 0.0
	var y0 = 0.0
	var w = float(dims.x)
	var h = float(dims.y)
	if req.has("rect"):
		var r = req["rect"]
		if typeof(r) != TYPE_ARRAY or r.size() < 4:
			return _err("'rect' must be [x, y, w, h] in woxels")
		x0 = float(r[0]); y0 = float(r[1]); w = float(r[2]); h = float(r[3])
	if w <= 0.0 or h <= 0.0:
		return _err("rect width and height must be positive")

	var n = int(req.get("samples", 16))
	if n < 2: n = 2
	if n > 64: n = 64

	var rows := []
	img.lock()
	for j in range(n):
		var row := []
		for i in range(n):
			var wx = x0 + w * (float(i) / float(n - 1))
			var wy = y0 + h * (float(j) / float(n - 1))
			var px = int(clamp(wx / float(dims.x) * float(iw), 0, iw - 1))
			var py = int(clamp(wy / float(dims.y) * float(ih), 0, ih - 1))
			var c = img.get_pixel(px, py)

			row.append([stepify(c.r, 0.01), stepify(c.g, 0.01),
				stepify(c.b, 0.01), stepify(c.a, 0.01)])
		rows.append(row)
	img.unlock()

	var rows2 := []
	var img2 = _clone_splat2(level)
	if img2 != null and img2.get_width() == iw and img2.get_height() == ih:
		img2.lock()
		for j2 in range(n):
			var row2 := []
			for i2 in range(n):
				var wx2 = x0 + w * (float(i2) / float(n - 1))
				var wy2 = y0 + h * (float(j2) / float(n - 1))
				var px2 = int(clamp(wx2 / float(dims.x) * float(iw), 0, iw - 1))
				var py2 = int(clamp(wy2 / float(dims.y) * float(ih), 0, ih - 1))
				var c2 = img2.get_pixel(px2, py2)
				row2.append([stepify(c2.r, 0.01), stepify(c2.g, 0.01),
					stepify(c2.b, 0.01), stepify(c2.a, 0.01)])
			rows2.append(row2)
		img2.unlock()

	var blending = null
	if level.Terrain.has_method("get_SmoothBlending"):
		blending = bool(level.Terrain.get_SmoothBlending())

	var out := {
		"rect": [x0, y0, w, h],
		"samples": n,
		"splat_size": [iw, ih],
		"slots": _terrain_slots(level),
		"weights": rows,
		"weights2": rows2,
		"smooth_blending": blending,
		"note": ("the four weights are slots 0-3 read directly from the splat " +
			"image's RGBA channels; slots 1-3 are explicitly paintable and rise " +
			"when painted, while slot 0 is not itself a paintable channel — it " +
			"is whatever fraction channels 1-3 leave unclaimed, so a blank map's " +
			"[1,0,0,0] means 100% unclaimed base, not 100% painted into slot 0, " +
			"and paint_terrain(slot=0) is accepted but never changes this " +
			"readback. Samples are row-major from the rect's top-left and sum " +
			"to ~1. weights2 holds slots 4-7 from the second splat image in the " +
			"same shape, empty on a build that does not expose it. " +
			"smooth_blending is the level's blend mode: true smooth, false " +
			"textured."),
	}
	if _patch_terrain_extended():
		out["extended_slots"] = true
		out["extended_note"] = "the Unofficial Patch's 24 terrain slots are on for " + \
			"this level. Slots 8-23 live in the patch's own images, which these " + \
			"weights do not include, so they may not sum to 1, and the bridge will " + \
			"not paint this level"
	return _ok(out)

func _terrain_slots(level) -> Array:
	var out := []
	if level.Terrain == null or not level.Terrain.has_method("get_Textures"):
		return out
	var textures = level.Terrain.get_Textures()

	for i in range(8):
		var tex = textures[i] if (textures != null and i < textures.size()) else null
		out.append(tex.resource_path if (tex != null and tex is Texture) else "")
	return out

# The level a history entry belongs to. -1 means the entry predates level
# ownership, in which case the current level is the best available answer.
func _level_for_history(level_id : int):
	if level_id < 0:
		return Global.World.GetCurrentLevel()
	var level = Global.World.GetLevelByID(level_id)
	if level == null:
		print("[mcp-bridge] history entry names level %d, which no longer exists" % level_id)
	return level

func _restore_terrain_slots(slots, level_id : int) -> void:
	if typeof(slots) != TYPE_ARRAY:
		return
	var level = _level_for_history(level_id)
	if level == null or level.Terrain == null:
		return
	for i in range(slots.size()):
		var path = str(slots[i])
		if path == "":
			continue
		var tex = _asset_tex("Terrain", path)
		if tex != null:
			level.Terrain.SetTexture(tex, i)
	level.Terrain.UpdateSplat()

func _clone_splat2(level):
	if level == null or level.Terrain == null:
		return null
	if not level.Terrain.has_method("CloneSplatImage2"):
		return null
	if level.Terrain.has_method("get_ExpandedSlots") and not level.Terrain.get_ExpandedSlots():
		return null
	return level.Terrain.CloneSplatImage2()

func _restore_splat(img, img2, level_id : int):
	if img == null:
		return
	var level = _level_for_history(level_id)
	if level == null:
		return
	# A resize between snapshot and undo leaves an image of the wrong raster
	# size. Restoring it would corrupt the splat rather than reverse an edit.
	var current = level.Terrain.CloneSplatImage()
	if current != null and img is Image and current.get_size() != img.get_size():
		print("[mcp-bridge] refusing terrain undo: snapshot %s vs splat %s (resized?)"
			% [str(img.get_size()), str(current.get_size())])
		return

	if img2 != null and level.Terrain.has_method("RestoreSplat2"):
		level.Terrain.RestoreSplat2(img, img2)
	elif level.Terrain.has_method("RestoreSplat2") \
			and level.Terrain.has_method("get_ExpandedSlots") \
			and level.Terrain.get_ExpandedSlots() and img is Image:

		level.Terrain.RestoreSplat2(img,
			_blank_splat(img.get_width(), img.get_height(), Color(0, 0, 0, 0)))
	else:
		level.Terrain.RestoreSplat(img)
	level.Terrain.UpdateSplat()

# Cave edits retain both rasters: rebuilding the floor can also change entrances.
func _cave_snapshot():
	var cave = _cave_mesh()
	if cave == null: return null
	var bm = cave.get_Bitmap()
	var entrances = cave.get("entranceBitmap")
	var snap = null
	if bm is BitMap and entrances is BitMap and bm.get_size() == entrances.get_size():
		snap = { "floor": bm.duplicate(true), "entrances": entrances.duplicate(true),
			"dimensions": Global.World.WoxelDimensions }
	_release_tool_named("CaveBrush")
	return snap

# Refuse before popping history: a refused undo must remain available.
func _cave_history_error(op) -> String:
	if op.get("kind") != "cave": return ""
	var level = Global.World.GetCurrentLevel()
	if level == null or int(level.ID) != int(op.get("level", -1)):
		return "select the cave edit's original level before undo/redo"
	var cave = level.get("CaveMesh")
	if cave == null: return "cave mesh unavailable for undo/redo"
	var bm = cave.get_Bitmap()
	var entrances = cave.get("entranceBitmap")
	if not (bm is BitMap) or not (entrances is BitMap):
		return "cave bitmaps unavailable for undo/redo"
	var size = bm.get_size()
	if op["before"]["dimensions"] != Global.World.WoxelDimensions \
			or entrances.get_size() != size or op["before"]["floor"].get_size() != size \
			or op["after"]["floor"].get_size() != size:
		return "cave bitmap size changed; refusing undo/redo after resize"
	return ""

func _restore_cave(snap, level_id : int):
	if snap == null: return
	var level = Global.World.GetCurrentLevel()
	if level == null or int(level.ID) != level_id: return
	var cave = _cave_mesh()
	if cave == null: return
	cave.SetBitmap(snap["floor"].duplicate(true))
	cave.SetEntranceBitmap(snap["entrances"].duplicate(true))
	cave.FinalizeMeshAndBorders()
	cave.UpdateMesh()
	_release_tool_named("CaveBrush")

func _apply_block_light(node, wants : bool) -> void:
	if node == null or not node.has_method("SetBlockLight"):
		return
	node.set("BlockLight", wants)
	node.SetBlockLight(wants)
	if wants:
		if node.has_method("GenerateOccluder"):
			node.GenerateOccluder()
		if node.has_method("UpdateOccluders"):
			node.UpdateOccluders()
	elif node.has_method("ClearOccluders"):
		node.ClearOccluders()

func _snapshot(node) -> Dictionary:
	var s := {}
	if node.get("Direction") != null: s["portal_direction"] = node.Direction
	if node.has_method("set_Points") and node.has_method("RemakeLines"):
		s["wall_points"] = PoolVector2Array(node.Points)
		s["wall_portals"] = []
		for portal in node.Portals:
			s["wall_portals"].append({ "id": _id(portal), "position": portal.position,
				"rotation": portal.rotation, "direction": portal.Direction })
	if node is Node2D:
		s["position"] = node.position
		s["rotation"] = node.rotation
		s["scale"] = node.scale
		# Rotation and scale cannot carry a Free Transform skew; see
		# _patch_is_sheared.
		if _patch_is_sheared(node):
			s["transform"] = node.transform

		s["z_index"] = node.z_index

	if not (node is Node2D) and node.get("rect_position") != null:
		s["rect_position"] = node.get("rect_position")
	if node.get("HasShadow") != null:
		s["shadow"] = node.get("HasShadow")

	var blocking = node.get("BlockLight")
	if blocking != null:
		s["block_light"] = bool(blocking)
	var mod_tint = _read_node_modulate(node)
	if mod_tint != null:
		s["modulate"] = mod_tint
	var col = _read_node_color(node)
	if col != null:
		s["color"] = col
	return s

# Dispatch with a guard so a bad command can never take down the TCP loop.
func _safe_dispatch(req : Dictionary) -> Dictionary:
	var cmd = req.get("cmd", "")
	_note_request(str(cmd))

	# The user paused the assistant from the panel. Reads, renders and status
	# still answer, so an assistant can see why and say so; nothing that
	# changes the map runs until the user unticks it. Undo/redo are edits too.
	if _paused and not (cmd in SAFE_DURING_SAVE):
		return _err("Paused in Dungeondraft: the user has paused AI edits from " +
			"the Battlemap MCP Bridge panel (Settings tools). Reads, screenshots and " +
			"exports still work. Tell the user, and wait for them to untick " +
			"Pause before editing again.")

	if not (cmd in SAFE_DURING_SAVE) and _saving():
		return _err(("Dungeondraft is saving %s right now%s, and edits made " +
			"during a save are dropped from the file. Retry in a moment; " +
			"get_status reports saving.in_flight.")
			% [_save_path, (" (an automatic backup)" if _save_is_backup else "")])

	if _export_running() and (cmd in UNSAFE_DURING_EXPORT or not (cmd in SAFE_DURING_SAVE)):
		return _err(("export %s is still rendering (%d chunks so far), and it renders " +
			"by moving the camera over the map, so this command would corrupt it " +
			"or read a half-drawn view. Wait for get_operation(%s) to report " +
			"completed or failed, then retry.%s")
			% [_export_job["operation_id"], _export_job["chunks_rendered"],
			_export_job["operation_id"],
			(" It is " + _operation_view(_export_job)["recovery"]) if _export_job["overdue"] else ""])

	if cmd != "preview_assets":
		var unusable_asset = _unincluded_pack_asset(req)
		if unusable_asset != "":
			return _err(unusable_asset)

	if cmd in TERRAIN_PAINT_CMDS:
		var extended = _patch_terrain_refusal()
		if extended != null:
			return extended

	match cmd:
		# --- read / query ---
		"ping": return _ok({ "pong": true, "protocol": PROTOCOL_VERSION, "paused": _paused,
			"engine": Engine.get_version_info(), "bridge_sha256": _bridge_sha256(),
			"bridge_root": Global.get("Root", ""), "process_id": OS.get_process_id(),
			"bridge_instance": _instance_id, "unofficial_patch": _patch_info() })
		"get_status": return _get_status()
		"list_asset_categories": return _list_asset_categories()
		"list_asset_packs": return _list_asset_packs()
		"list_assets": return _list_assets(req)
		"list_elements": return _list_elements(req)
		"get_composition_snapshot": return _get_composition_snapshot()
		"get_element": return _get_element(req)
		"preview_assets": return _preview_assets(req)
		"list_levels": return _list_levels()
		"get_terrain": return _get_terrain(req)
		"set_terrain_blending": return _set_terrain_blending(req)
		"set_water_style": return _set_water_style(req)
		"get_map_style": return _get_map_style()
		"set_map_style": return _set_map_style(req)
		"paint_material": return _paint_material(req)
		"set_trace_image": return _set_trace_image(req)
		"set_verbose": return _set_verbose(req)
		"get_save_directory": return _get_save_directory(req)
		"set_save_directory": return _set_save_directory(req)
		"log_marker": return _log_marker(req)
		"add_floor": return _add_floor(req)
		"generate_dungeon": return _generate_dungeon(req)
		"generator_options": return _generator_options(req)
		"delete_level": return _delete_level(req)
		"set_map_size": return _set_map_size(req)
		"get_cave": return _get_cave(req)
		"set_cave_entrance": return _set_cave_entrance(req)
		"dig_cave": return _dig_cave(req)
		"add_water": return _add_water(req)
		"save_map": return _save_map(req)
		"open_map": return _open_map(req)
		"set_ambient_light": return _set_ambient_light(req)
		"list_prefabs": return _list_prefabs(req)
		"place_prefab": return _place_prefab(req)
		"tool_action": return _tool_action(req)
		"set_tool_option": return _set_tool_option(req)
		"clear_caves": return _clear_caves(req)
		"get_recent_nodes": return _get_recent_nodes(req)
		"get_tool_layer": return _get_tool_layer(req)
		"get_snap_settings": return _get_snap_settings(req)
		"checkpoint": return _checkpoint(req)
		"rollback_checkpoint": return _rollback_checkpoint(req)
		"list_checkpoints": return _list_checkpoints(req)
		"set_tool_layer": return _set_tool_layer(req)
		"select_tool": return _select_tool(req)
		"list_tool_controls": return _list_tool_controls(req)
		# --- create ---
		"place_object": return _place_object(req)
		"place_objects": return _place_objects(req)
		"merge_walls": return _merge_walls(req)
		"draw_wall": return _draw_wall(req)
		"draw_path": return _draw_path(req)
		"add_light": return _add_light(req)
		"add_portal": return _add_portal(req)
		"add_roof": return _add_roof(req)
		"add_text": return _add_text(req)
		"place_pattern": return _place_pattern(req)
		"build_room": return _build_room(req)
		"scatter_objects": return _scatter_objects(req)
		# --- terrain ---
		"set_terrain_slot": return _set_terrain_slot(req)
		"fill_terrain": return _fill_terrain(req)
		"repair_terrain": return _repair_terrain(req)
		"fill_region": return _fill_region(req)
		"paint_terrain": return _paint_terrain(req)
		"paint_path": return _paint_path(req)
		# --- modify / delete ---
		"move_element": return _move_element(req)
		"move_elements": return _move_elements(req)
		"modify_object": return _modify_object(req)
		"duplicate_object": return _duplicate_object(req)
		"delete_element": return _delete_element(req)
		"delete_elements": return _delete_elements(req)
		# --- levels ---
		"add_level": return _add_level(req)
		"set_level": return _set_level(req)
		# --- capture ---
		"screenshot": return _screenshot(req)
		"export_map": return _export_map(req)
		"get_operation": return _get_operation(req)
		# --- camera ---
		"get_camera": return _get_camera()
		"set_camera": return _set_camera(req)
		"focus_element": return _focus_element(req)
		"fit_elements": return _fit_elements(req)
		# --- history (bridge-managed undo/redo of the model's own edits) ---
		"undo": return _do_undo()
		"redo": return _do_redo()
		# --- selection ---
		"select_elements": return _select_elements(req)
		"clear_selection": return _clear_selection()

		_: return _err("unknown cmd: " + str(cmd))

# Scanning a texture for its colour mask costs ~2ms. Worth it for a listing a
# caller is about to choose from; not for one of thousands.
const COLORABLE_SCAN_MAX := 200

const ASSET_CATEGORIES := [
	"Objects", "Walls", "Paths", "Terrain", "Lights", "Portals", "Roofs",
	"Patterns", "Patterns Colorable", "Caves", "Materials",
	"Simple Tiles", "Smart Tiles", "Smart Tiles Double",
]

# ---------------------------------------------------------------------------
# Read / query
# ---------------------------------------------------------------------------

func _get_status() -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null:
		return _ok({ "map_open": false, "bridge_instance": _instance_id,
			"paused": _paused })
	var counts := {}
	for kind in COLLECTIONS:
		counts[kind] = _real_children(level, kind).size()
	if counts.has("portals"):
		counts["portals"] += _wall_mounted_portals(level).size()
	return _ok({
		"map_open": true,
		"paused": _paused,

		"map_file": _current_map_file(),

		"level_id": level.ID,
		"level_count": Global.World.levels.size(),
		"map_size_woxels": [Global.World.WoxelDimensions.x, Global.World.WoxelDimensions.y],
		"map_center": [Global.World.WoxelDimensions.x * 0.5, Global.World.WoxelDimensions.y * 0.5],
		"counts": counts,
		"layers": _layer_summary(level),
		"active_tool": Global.Editor.ActiveToolName,
		"undo_depth": _undo_stack.size(),
		"redo_depth": _redo_stack.size(),
		"max_undo": MAX_UNDO_OPS,
		# Ops holding terrain/cave image snapshots, bounded by memory rather
		# than by count; see SNAPSHOT_BUDGET_BYTES.
		"snapshot_ops": _snapshot_op_count(),
		"snapshot_bytes": _snapshot_total_bytes(),
		"snapshot_budget_bytes": SNAPSHOT_BUDGET_BYTES,
		"saving": _save_state(),
		"export": _operation_view(_export_job) if _export_running() else null,

		"asset_packs": _asset_pack_counts(),
		"signals": _signals.keys(),
		"node_log_seq": _assign_seq,
		# Which bridge instance answered. Every map load starts a new one, and for a
		# moment the old one still answers with the NEW map_file but the OLD map's
		# contents; open_map waits for a changed instance rather than a changed path.
		"bridge_instance": _instance_id,
		"unofficial_patch": _patch_info(),
		# A dialog is holding the editor's input: a popup from Dungeondraft or a
		# mod (the Unofficial Patch shows several on its own). The bridge still
		# answers, but the user may need to close it.
		"dialog_open": _dialog_open(),
	})

func _dialog_open() -> bool:
	var viewport = Global.Editor.get_viewport() if Global.Editor != null else null
	return viewport != null and viewport.gui_has_modal_stack()

func _layer_summary(level) -> Dictionary:
	var out := {}

	# Water and cave are both MeshInstance2D: a mesh with no surfaces has
	# nothing drawn into it.
	out["water"] = _mesh_has_geometry(level.get("WaterMesh"))
	out["cave"] = _mesh_has_geometry(level.get("CaveMesh"))

	var floors = level.get("FloorShapes")
	if floors != null and floors.has_method("get_polygon_count"):
		out["floor_shapes"] = floors.get_polygon_count()

	var patterns = level.get("PatternShapes")
	if patterns != null and patterns.has_method("GetShapes"):
		out["pattern_shapes"] = patterns.GetShapes().size()

	var tiles = level.get("TileMap")
	if tiles != null and tiles.has_method("get_used_cells"):
		out["tile_cells"] = tiles.get_used_cells().size()

	# Terrain is always present — the question is whether anything is painted
	# over the base, which get_terrain answers properly by sampling.
	out["terrain"] = "use get_terrain to sample what is painted"
	return out

func _mesh_has_geometry(node) -> bool:
	if node == null:
		return false
	var mesh = node.get("mesh")
	if mesh == null or not mesh.has_method("get_surface_count"):
		return false
	return mesh.get_surface_count() > 0

const PACKS_DIR := "res://packs"

func _list_asset_packs() -> Dictionary:
	var installed := []
	var dir = Directory.new()
	if dir.open(PACKS_DIR) == OK and dir.list_dir_begin(true, true) == OK:
		var entry = dir.get_next()
		while entry != "":
			if dir.current_is_dir():
				installed.append(_read_pack_manifest(entry))
			entry = dir.get_next()
		dir.list_dir_end()
	var included := []
	for pack in _map_asset_manifest():
		included.append(_describe_asset_pack(pack))
	var included_ids := {}
	for pack in included:
		included_ids[str(pack.get("id", ""))] = true
	var unused := []
	for pack in installed:
		if not included_ids.has(str(pack.get("id", ""))):
			# The full manifest, not a bare id: these are exactly the packs a
			# caller has to CHOOSE between, and an id like "8XXbciV2" says
			# nothing about a pack's subject.
			unused.append(pack)
	return _ok({
		"installed": installed,
		"included_in_this_map": included,
		"installed_but_not_in_this_map": unused,
		"note": ("a map can only use assets from the packs it INCLUDES. Packs " +
			"listed in installed_but_not_in_this_map are mounted but invisible " +
			"to list_assets on this map, and anything placed from one would not " +
			"survive a reload."),
	})

# The AssetPack array of the open map, or an empty array. Read-only.
func _map_asset_manifest() -> Array:
	var header = Global.get("Header")
	if header == null:
		return []
	var manifest = header.get("AssetManifest")
	if manifest == null:
		return []
	return manifest

func _read_pack_manifest(pack_id : String) -> Dictionary:
	var out := { "id": pack_id, "name": "", "version": "", "author": "" }
	var f = File.new()
	if f.open("%s/%s/pack.json" % [PACKS_DIR, pack_id], File.READ) != OK:
		return out
	var raw = f.get_as_text()
	f.close()
	var parsed = JSON.parse(raw)
	if parsed.error != OK or typeof(parsed.result) != TYPE_DICTIONARY:
		return out
	for key in ["name", "version", "author", "keywords",
			"allow_3rd_party_mapping_software_to_read", "custom_color_overrides"]:
		if parsed.result.has(key):
			out[key] = parsed.result[key]
	return out

func _describe_asset_pack(pack) -> Dictionary:
	var out := {}
	if pack == null:
		return out
	for pair in [["id", "ID"], ["name", "Name"], ["version", "Version"], ["author", "Author"]]:
		var value = pack.get(pair[1])
		out[pair[0]] = "" if value == null else str(value)
	return out

# How many packs are mounted, and how many this map includes. Cheap enough for
# get_status: it counts directories, it does not read any asset.
func _asset_pack_counts() -> Dictionary:
	var installed := 0
	var dir = Directory.new()
	if dir.open(PACKS_DIR) == OK and dir.list_dir_begin(true, true) == OK:
		var entry = dir.get_next()
		while entry != "":
			if dir.current_is_dir():
				installed += 1
			entry = dir.get_next()
		dir.list_dir_end()
	return { "included": _map_asset_manifest().size(), "installed": installed }

# The ids of the packs THIS MAP includes, as a lookup.
func _included_pack_ids() -> Dictionary:
	var ids := {}
	for pack in _map_asset_manifest():
		var id = str(_describe_asset_pack(pack).get("id", ""))
		if id != "":
			ids[id] = true
	return ids

func _collect_pack_paths(value, out : Array) -> void:
	if typeof(value) == TYPE_STRING:
		if str(value).begins_with(PACKS_DIR + "/"):
			out.append(str(value))
	elif typeof(value) == TYPE_ARRAY:
		for entry in value:
			_collect_pack_paths(entry, out)
	elif typeof(value) == TYPE_DICTIONARY:
		for key in value.keys():
			_collect_pack_paths(value[key], out)

# The pack id in res://packs/<id>/..., or "" for a core asset.
func _pack_id_of(path : String) -> String:
	var prefix = PACKS_DIR + "/"
	if not path.begins_with(prefix):
		return ""
	var rest = path.substr(prefix.length())
	var cut = rest.find("/")
	if cut < 0:
		return rest
	return rest.substr(0, cut)

# A signature of the included packs, so a cache built while one map was open is
# not reused after another is opened.
func _manifest_signature() -> String:
	var ids := []
	for id in _included_pack_ids().keys():
		ids.append(str(id))
	ids.sort()
	return PoolStringArray(ids).join(",")

func _unincluded_pack_asset(req : Dictionary) -> String:
	var paths := []
	for key in req.keys():
		_collect_pack_paths(req[key], paths)
	if paths.size() == 0:
		return ""
	var included = _included_pack_ids()
	for path in paths:
		var owner = _pack_id_of(str(path))
		if owner != "" and not included.has(owner):
			return (("'%s' belongs to asset pack '%s', which THIS MAP does not " +
				"include. It would place and save, then vanish when the map is " +
				"reopened. Prepare a copy of the map that includes the pack, or " +
				"choose from the assets list_assets offers here.")
				% [str(path), owner])
	return ""

func _list_asset_categories() -> Dictionary:
	var out := []
	var populated := []
	for cat in ASSET_CATEGORIES:
		var all = Script.GetAssetList(cat)
		var n = 0 if all == null else all.size()
		out.append({ "name": cat, "count": n })
		if n > 0:
			populated.append(cat)
	return _ok({ "categories": ASSET_CATEGORIES, "counts": out,
		"populated": populated })

func _preview_assets(req : Dictionary) -> Dictionary:
	var category = str(req.get("category", "Objects"))
	if not (category in ASSET_CATEGORIES):
		return _err("unknown asset category: %s; expected one of %s"
			% [category, str(ASSET_CATEGORIES)])
	var assets = req.get("assets", [])
	if typeof(assets) != TYPE_ARRAY or assets.size() == 0:
		return _err("'assets' must be a non-empty array of asset paths from list_assets")
	if assets.size() > PREVIEW_MAX_ASSETS:
		return _err("'assets' capped at %d per sheet; narrow the candidates first"
			% PREVIEW_MAX_ASSETS)
	var columns = int(clamp(int(req.get("columns", 4)), 1, 8))
	var cell = int(clamp(int(req.get("cell_px", 128)), 32, 256))
	var path = _output_path(req.get("name", "asset_preview.png"))
	if path == "": return _err("invalid 'name': pass a bare filename, not a path")

	var rows = int(ceil(float(assets.size()) / float(columns)))
	var sheet = Image.new()
	sheet.create(columns * cell, rows * cell, false, Image.FORMAT_RGBA8)
	sheet.fill(PREVIEW_BG)

	var missing := []
	var colorable := []
	for i in range(assets.size()):
		var asset = str(assets[i])
		var tex = _asset_tex(category, asset)
		if tex == null:
			missing.append(asset)
			continue
		var img = tex.get_data()
		if img == null:
			missing.append(asset)
			continue
		var cx = (i % columns) * cell
		var cy = int(i / columns) * cell
		if _mask_fraction(tex) > 0.0:
			colorable.append(asset)
			var ground = Image.new()
			ground.create(cell, cell, false, Image.FORMAT_RGBA8)
			ground.fill(PREVIEW_BG_COLORABLE)
			sheet.blit_rect(ground, Rect2(0, 0, cell, cell), Vector2(cx, cy))
		img.convert(Image.FORMAT_RGBA8)

		if category == "Walls" and img.get_width() > img.get_height() * 2:
			img = img.get_rect(Rect2(0, 0, img.get_height() * 2, img.get_height()))
		var w = img.get_width()
		var h = img.get_height()
		if w < 1 or h < 1:
			missing.append(asset)
			continue
		# Fit inside the cell preserving aspect, so a long table is not squashed
		# into a square and judged on a shape it does not have.
		var factor = min(float(cell) / float(w), float(cell) / float(h))
		var nw = int(max(1, int(float(w) * factor)))
		var nh = int(max(1, int(float(h) * factor)))
		img.resize(nw, nh, Image.INTERPOLATE_BILINEAR)
		if category in TILE_PREVIEW_CATEGORIES or (category == "Walls" and _is_greyscale(img)):
			_tint_image(img, DEFAULT_PATTERN_TINT)
		# blend, not blit: these carry alpha, and blitting would punch the
		# transparent border through the ground and lose the silhouette.
		sheet.blend_rect(img, Rect2(0, 0, nw, nh),
			Vector2(cx + (cell - nw) / 2, cy + (cell - nh) / 2))

	var err = sheet.save_png(path)
	if err != OK:
		return _err("save_png failed (err %d): %s" % [err, path])
	return _ok({ "path": path, "columns": columns, "rows": rows, "cell_px": cell,
		"count": assets.size(), "colorable": colorable, "missing": missing,
		"width": sheet.get_width(), "height": sheet.get_height() })

# Wall textures are either greyscale masks the wall tool colours at placement or
# full-colour pack art. Only a mask wants tinting: multiplying a coloured wall
# would misrepresent the very thing the preview exists to show.
func _is_greyscale(img : Image) -> bool:
	img.lock()
	var opaque := 0
	var coloured := 0
	for y in range(0, img.get_height(), 2):
		for x in range(0, img.get_width(), 2):
			var c = img.get_pixel(x, y)
			if c.a < 0.5:
				continue
			opaque += 1
			if max(abs(c.r - c.g), max(abs(c.g - c.b), abs(c.r - c.b))) > 0.08:
				coloured += 1
	img.unlock()
	return opaque > 0 and coloured <= opaque / 50

# Multiply an image by a colour, keeping alpha — what the tile tools do at
# placement, applied to a preview-sized copy. Runs after the resize, so it
# touches at most one cell's worth of pixels.
func _tint_image(img : Image, tint : Color) -> void:
	img.lock()
	for y in range(img.get_height()):
		for x in range(img.get_width()):
			var c = img.get_pixel(x, y)
			img.set_pixel(x, y, Color(c.r * tint.r, c.g * tint.g, c.b * tint.b, c.a))
	img.unlock()

func _list_assets(req : Dictionary) -> Dictionary:
	var category = req.get("category", "Objects")
	var search = str(req.get("search", "")).to_lower()
	var limit = int(req.get("limit", 100))
	var vanilla_only = bool(req.get("vanilla_only", false))

	var only = req.get("only", [])
	var only_set := {}
	if typeof(only) == TYPE_ARRAY:
		for wanted in only:
			only_set[str(wanted)] = true

	var terms := []
	if typeof(req.get("terms")) == TYPE_ARRAY:
		for term in req["terms"]:
			var lowered = str(term).to_lower()
			if lowered != "":
				terms.append(lowered)

	if not (category in ASSET_CATEGORIES):
		return _err("unknown asset category: %s; expected one of %s"
			% [str(category), str(ASSET_CATEGORIES)])
	var all = Script.GetAssetList(category)
	if all == null:
		return _err("unknown asset category: " + str(category))
	# An empty category is a real state, not an error — "Patterns" ships empty
	# and fills only from asset packs — but saying so beats returning nothing.
	if all.size() == 0:
		var have := []
		for cat in ASSET_CATEGORIES:
			var other = Script.GetAssetList(cat)
			if other != null and other.size() > 0:
				have.append(cat)
		return _err(("category '%s' exists but holds no assets in this " +
			"installation (it fills from asset packs); categories with assets: %s")
			% [str(category), str(have)])
	var out := []
	var matched := 0
	var hidden := 0
	var included_packs = _included_pack_ids()
	for path in all:

		var owning_pack = _pack_id_of(str(path))
		if owning_pack != "" and not included_packs.has(owning_pack):
			hidden += 1
			continue
		if vanilla_only and not str(path).begins_with("res://textures/"):
			continue
		if only_set.size() > 0 and not only_set.has(str(path)):
			continue
		if search != "" and str(path).to_lower().find(search) == -1:
			continue
		if terms.size() > 0:
			var lowered_path = str(path).to_lower()
			var missing_term := false
			for term in terms:
				if lowered_path.find(term) == -1:
					missing_term = true
					break
			if missing_term:
				continue
		matched += 1
		if out.size() < limit:
			out.append(path)

	var colorable := []
	if out.size() <= COLORABLE_SCAN_MAX:
		for i in range(out.size()):
			if _mask_fraction(_asset_tex(category, out[i])) > 0.0:
				colorable.append(i)

	return _ok({ "category": category, "total": all.size() - hidden,
		"total_unfiltered": all.size(), "matched": matched,
		"returned": out.size(), "assets": out, "colorable": colorable,
		"hidden_unusable": hidden,
		"colorable_scanned": out.size() <= COLORABLE_SCAN_MAX,
		"colorable_are": "indices into assets",
		# Only when it applies. The note was attached to every listing, including
		# the ones where `colorable` was empty and it said nothing at all.
		"note": (("assets at the 'colorable' indices have an unpainted colour mask " +
			"and render flat RED unless you pass color= when placing them. Colour " +
			"is baked at placement and cannot be changed afterwards.")
			if colorable.size() > 0 else "") })

func _cave_mesh():
	if not Global.Editor.Tools.has("CaveBrush"):
		return null
	var brush = Global.Editor.Tools["CaveBrush"]
	brush.call("Enable")
	if not brush.has_method("get_Mesh"):
		return null
	return brush.call("get_Mesh")

func _mesh_cell(mesh, world : Vector2) -> Vector2:
	var cs = mesh.get("CellSize")
	if cs == null and mesh.has_method("get_CellSize"):
		cs = mesh.call("get_CellSize")
	if cs == null or float(cs) <= 0.0:
		return world
	var buf = 0
	if mesh.get("MapEdgeBuffer") != null:
		buf = int(mesh.get("MapEdgeBuffer"))
	return Vector2(int(floor(world.x / float(cs))) + buf, int(floor(world.y / float(cs))) + buf)

func _paint_material(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	if not level.has_method("GetOrMakeMaterialMesh"):
		return _err("this build exposes no Level.GetOrMakeMaterialMesh")
	var tex = _asset_tex("Materials", req.get("asset", ""))
	if tex == null:
		return _err("could not load material asset: " + str(req.get("asset")) +
			" — pass a path from list_assets(category='Materials')")
	var pts = _points(req.get("points", []))
	if pts.size() < 1:
		return _err("'points' needs >= 1 [x,y] pair")
	var size = int(req.get("size", 2))
	if size < 1 or size > 20:
		return _err("'size' must be between 1 and 20 (brush radius in cells)")
	var layer = int(req.get("layer", MATERIAL_DEFAULT_LAYER))
	var smooth = bool(req.get("smooth", true))

	var mesh = level.GetOrMakeMaterialMesh(layer, tex, smooth)
	if mesh == null:
		return _err("GetOrMakeMaterialMesh returned nothing for layer %d" % layer)
	# Apply it to the mesh that came back, whether it was made or reused.
	if mesh.get("Smooth") != null:
		mesh.set("Smooth", smooth)
	elif mesh.has_method("SetSmooth"):
		mesh.SetSmooth(smooth)
	var value = not bool(req.get("erase", false))
	if mesh.has_method("OnDrawingBegin"):
		mesh.OnDrawingBegin()
	var dabs := 0
	for world_point in pts:
		mesh.SetCircle(_mesh_cell(mesh, world_point), size, value)
		dabs += 1
	if mesh.has_method("OnDrawingEnd"):
		mesh.OnDrawingEnd()
	if mesh.has_method("UpdateMesh"):
		mesh.UpdateMesh()

	var cell = mesh.get("CellSize")
	if cell == null and mesh.has_method("get_CellSize"):
		cell = mesh.call("get_CellSize")
	return _ok({ "layer": layer, "dabs": dabs, "size": size, "erased": not value,
		"smooth": (bool(mesh.get("Smooth")) if mesh.get("Smooth") != null else smooth),
		"smooth_reported_from_mesh": (mesh.get("Smooth") != null),
		"cell_size_woxels": (float(cell) if cell != null else null),
		"covered_woxels": (float(cell) * size * 2.0 if cell != null else null) })

func _cave_cell(cave, world : Vector2) -> Vector2:
	var cs = cave.call("get_CellSize")
	var buf = int(cave.get("MapEdgeBuffer"))
	return Vector2(int(floor(world.x / cs)) + buf, int(floor(world.y / cs)) + buf)

func _tool_control(tname : String, cname : String):
	if not Global.Editor.Tools.has(tname):
		return null
	var tool = Global.Editor.Tools[tname]
	var controls = tool.get("Controls")
	if controls == null or not controls.has(cname):
		return null
	return { "tool": tool, "control": controls[cname] }

const USER_OWNED_TOOLS := {
	"mcp_bridge": "the Battlemap MCP Bridge panel holds the user's own settings, including Pause",
	"snappy_mod": "the Custom Snap Mod's settings are the user's snap grid",
}

func _user_owned(tname : String):
	if USER_OWNED_TOOLS.has(tname):
		return _err("refused: %s, and only the user changes them in Dungeondraft" % USER_OWNED_TOOLS[tname])
	return null

func _tool_action(req : Dictionary) -> Dictionary:
	var tname = str(req.get("tool", ""))
	var cname = str(req.get("control", ""))
	var owned = _user_owned(tname)
	if owned != null: return owned
	var tc = _tool_control(tname, cname)
	if tc == null:
		return _err("no control '" + cname + "' on tool '" + tname + "'; call list_tool_controls")
	var tool = tc["tool"]
	var ctrl = tc["control"]
	if not ctrl.has_signal("pressed"):
		return _err("control '" + cname + "' is not a button (it has no 'pressed' signal)")

	if tname == "SelectTool" and cname == "MERGE_WALLS":
		for thing in tool.get_Selected():
			if thing == null or not is_instance_valid(thing):
				return _err("wall merge selection contains an unavailable element; select again")
			var portals = thing.get("Portals")
			if portals != null and portals.size() > 0:
				return _err("cannot merge walls with mounted portals: native merging can delete doors/windows")
	var was_active := _enable_tool(tname, tool, bool(req.get("enable", true)))
	if ctrl.has_method("is_disabled") and ctrl.is_disabled():
		_release_tool(tool, was_active)
		return _err("control '" + cname + "' is disabled right now (it may need a selection first)")
	ctrl.emit_signal("pressed")
	if bool(req.get("disable_after", true)):
		_release_tool(tool, was_active)
	return _ok({ "tool": tname, "control": cname, "pressed": true })

# The control that actually carries set_pick_color: either the named control
# itself, or a child of it when the panel wraps the picker in a container.
func _colour_picker_in(ctrl, depth : int = 3):
	if ctrl == null or depth < 0:
		return null
	if ctrl.has_method("set_pick_color"):
		return ctrl

	for child in ctrl.get_children():
		var found = _colour_picker_in(child, depth - 1)
		if found != null:
			return found
	return null

func _set_tool_option(req : Dictionary) -> Dictionary:
	var bad_option_color = _bad_color(req, ["color"])
	if bad_option_color != null: return bad_option_color
	var tname = str(req.get("tool", ""))
	var cname = str(req.get("control", ""))
	var owned = _user_owned(tname)
	if owned != null: return owned
	var tc = _tool_control(tname, cname)
	if tc == null:
		return _err("no control '" + cname + "' on tool '" + tname + "'; call list_tool_controls")
	var tool = tc["tool"]
	var ctrl = tc["control"]
	var was_active := _enable_tool(tname, tool, bool(req.get("enable", true)))

	var applied = ""
	# Boolean toggle
	if req.has("pressed") and ctrl.has_method("set_pressed"):
		ctrl.set_pressed(bool(req["pressed"]))
		if ctrl.has_signal("toggled"): ctrl.emit_signal("toggled", bool(req["pressed"]))
		applied = "pressed"

	elif req.has("color") and _colour_picker_in(ctrl) != null:
		var picker = _colour_picker_in(ctrl)
		var col = _color(req["color"], Color(1, 1, 1))
		picker.set_pick_color(col)
		if picker.has_signal("color_changed"): picker.emit_signal("color_changed", col)
		applied = "color"

	elif (req.has("item") or req.has("item_index") or req.has("item_metadata")) \
			and ctrl.has_method("get_item_count") and ctrl.has_method("select"):
		var count = ctrl.get_item_count()
		var idx = -1
		if req.has("item_index"):
			idx = int(req["item_index"])
			if idx < 0 or idx >= count:
				_release_tool(tool, was_active)
				return _err("control '%s' has %d items, so index %d is out of range"
					% [cname, count, idx])
		elif req.has("item_metadata"):
			var want_meta = str(req["item_metadata"])
			if ctrl.has_method("get_item_metadata"):
				for i in range(count):
					var meta = ctrl.get_item_metadata(i)
					if meta != null and str(meta).find(want_meta) != -1:
						idx = i
						break
			if idx < 0:
				_release_tool(tool, was_active)
				return _err(("control '%s' has no item whose metadata contains '%s' " +
					"(%d items). list_tool_controls shows what it holds.")
					% [cname, want_meta, count])
		else:
			var want = str(req["item"])
			if want.strip_edges() == "":
				# An empty string MATCHES a blank label, so this used to select
				# item 0 of a texture selector and report success. Refuse: it
				# names nothing.
				_release_tool(tool, was_active)
				return _err(("'item' is empty, which names nothing — it would match " +
					"the first blank-labelled entry. Use item_index, or " +
					"item_metadata to match an asset path."))
			var labelled := 0
			for i in range(count):
				if str(ctrl.get_item_text(i)).strip_edges() != "":
					labelled += 1
				if str(ctrl.get_item_text(i)) == want:
					idx = i
					break
			if idx < 0:
				_release_tool(tool, was_active)
				if labelled == 0:
					return _err(("control '%s' has %d items and NONE of them has a " +
						"visible label, so it cannot be selected by text. Use " +
						"item_index, or item_metadata to match an asset path.")
						% [cname, count])
				return _err("control '" + cname + "' has no item '" + want + "'")
		ctrl.select(idx)
		if ctrl.has_signal("item_selected"): ctrl.emit_signal("item_selected", idx)
		applied = "item"
	# Numeric
	elif req.has("value") and ctrl.has_method("set_value"):
		ctrl.set_value(float(req["value"]))
		if ctrl.has_signal("value_changed"): ctrl.emit_signal("value_changed", float(req["value"]))
		applied = "value"
	else:
		_release_tool(tool, was_active)
		return _err("give one of: pressed (bool), color ('#rrggbb'), item (text), value (number) — and the control must support it")

	if bool(req.get("disable_after", true)):
		_release_tool(tool, was_active)
	return _ok({ "tool": tname, "control": cname, "applied": applied })

func _set_ambient_light(req : Dictionary) -> Dictionary:

	var bad_ambient_color = _bad_color(req, ["color"])
	if bad_ambient_color != null: return bad_ambient_color
	if not Global.Editor.Tools.has("Environment"):
		return _err("this build exposes no Environment tool")
	var env = Global.Editor.Tools["Environment"]
	if not env.has_method("SetAmbientLight"):
		return _err("Environment exposes no SetAmbientLight")
	if not req.has("color") or str(req.get("color", "")) == "":
		return _err("'color' is required, as '#rrggbb'")
	var col = _color(req["color"], Color(1, 1, 1))
	var env_active := _enable_tool("Environment", env)
	env.SetAmbientLight(col)
	var got = null
	if env.has_method("get_AmbientLight"):
		var c = env.get_AmbientLight()
		if c is Color: got = "#" + c.to_html(false)
	_release_tool(env, env_active)
	return _ok({ "ambient_light": got })

func _prefab_controls():
	if not Global.Editor.Tools.has("PrefabTool"):
		return null
	var tool = Global.Editor.Tools["PrefabTool"]
	var controls = tool.get("Controls")
	if controls == null or not controls.has("Set") or not controls.has("List"):
		return null
	return { "tool": tool, "set": controls["Set"], "list": controls["List"] }

func _list_prefabs(req : Dictionary) -> Dictionary:
	var c = _prefab_controls()
	if c == null: return _err("PrefabTool controls unavailable")
	var tool = c["tool"]
	var was_active := _enable_tool("PrefabTool", tool)

	var sets := []
	var setbtn = c["set"]
	if setbtn.has_method("get_item_count"):
		for i in range(setbtn.get_item_count()):
			sets.append(str(setbtn.get_item_text(i)))

	if req.has("set") and str(req["set"]) != "" and setbtn.has_method("select"):
		var want = str(req["set"])
		var found := false
		for i in range(setbtn.get_item_count()):
			if str(setbtn.get_item_text(i)) == want:
				setbtn.select(i)
				if setbtn.has_signal("item_selected"):
					setbtn.emit_signal("item_selected", i)
				found = true
				break
		if not found:
			_release_tool(tool, was_active)
			return _err("no prefab set named '%s'; available: %s" % [want, str(sets)])

	var prefabs := []
	var lst = c["list"]
	if lst.has_method("get_item_count"):
		for i in range(lst.get_item_count()):
			prefabs.append(str(lst.get_item_text(i)))

	var current = ""
	if setbtn.has_method("get_selected") and setbtn.has_method("get_item_text"):
		var si = setbtn.get_selected()
		if si >= 0: current = str(setbtn.get_item_text(si))
	_release_tool(tool, was_active)
	return _ok({ "sets": sets, "current_set": current, "prefabs": prefabs })

func _place_prefab(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var c = _prefab_controls()
	if c == null: return _err("PrefabTool controls unavailable")
	var tool = c["tool"]
	var name = str(req.get("name", ""))
	if name == "": return _err("'name' is required; call list_prefabs to see what is available")

	# Snapshot before touching the tool at all: selecting the list item is what
	# places the prefab, not Confirm, so a count taken after Enable/select
	# misses the objects and wrongly reports placed:false.
	var before = level.Objects.get_child_count()
	var mark := _assign_mark()
	var was_active := _enable_tool("PrefabTool", tool)
	var setbtn = c["set"]
	if req.has("set") and setbtn.has_method("select"):
		var want = str(req["set"])
		for i in range(setbtn.get_item_count()):
			if str(setbtn.get_item_text(i)) == want:
				setbtn.select(i)
				if setbtn.has_signal("item_selected"):
					setbtn.emit_signal("item_selected", i)
				break

	var lst = c["list"]
	var idx = -1
	if lst.has_method("get_item_count"):
		for i in range(lst.get_item_count()):
			if str(lst.get_item_text(i)) == name:
				idx = i
				break
	if idx < 0:
		_release_tool(tool, was_active)
		return _err("no prefab named '" + name + "' in the selected set; call list_prefabs")
	if lst.has_method("select"): lst.select(idx)
	if lst.has_signal("item_selected"): lst.emit_signal("item_selected", idx)

	if tool.has_method("Confirm"): tool.Confirm()
	var after = level.Objects.get_child_count()
	_release_tool(tool, was_active)

	var created := _assigned_since(mark)
	var wants_position = req.has("x") or req.has("y") or float(req.get("rotation", 0.0)) != 0.0
	if _signals.has("OnAssignNode"):
		var out = { "prefab": name, "objects_before": before, "objects_after": after,
			"placed": not created.empty(), "ids": created }
		if wants_position:
			out["placement"] = _place_prefab_at(level, created, req)
		return _ok(out)
	var legacy = { "prefab": name, "objects_before": before, "objects_after": after,
		"placed": after > before }
	if wants_position:
		legacy["note"] = "position ignored: this build cannot identify what a prefab placed"
	return _ok(legacy)

# Centre all supported prefab geometry, then translate/rotate as one rigid group.
func _place_prefab_at(level, created, req : Dictionary) -> Dictionary:
	var group = _movable_group(created)
	var centre = _group_centre(group["nodes"])
	var target = Vector2(float(req.get("x", centre.x)), float(req.get("y", centre.y)))
	var moved = _transform_group(group, target - centre, deg2rad(float(req.get("rotation", 0.0))), centre)
	var skipped = []
	for entry in group["unsupported"]: skipped.append(entry["id"])
	return { "moved": moved.size(), "skipped": skipped, "unsupported": group["unsupported"],
		"centre": _vec(target), "authored_centre": _vec(centre) }

func _save_directory() -> String:
	var cfg = _read_config()
	var dir = _normalise_dir(str(cfg.get("save_directory", "")))
	if dir != "":

		var cfg_dir = Directory.new()
		if cfg_dir.dir_exists(dir):
			return dir
	if Global.Editor != null and Global.Editor.has_method("GetMapDirectory"):

		var dd_dir = _normalise_dir(str(Global.Editor.GetMapDirectory()))
		var dd = Directory.new()
		if dd_dir != "" and dd.dir_exists(dd_dir):
			# Create our subdirectory on demand. This is the one directory the
			# bridge owns, so making it is safe; the parent must already exist,
			# which is why it is checked first rather than created blindly.
			var sub = dd_dir + "/" + SAVE_SUBDIR
			if not dd.dir_exists(sub):
				if dd.make_dir_recursive(sub) != OK:
					return dd_dir
			return sub
	return ""

func _normalise_dir(raw : String) -> String:
	var out = raw.replace("\\", "/").strip_edges()
	while out.length() > 1 and out.ends_with("/") and not out.ends_with(":/"):
		out = out.substr(0, out.length() - 1)
	return out

func _read_config() -> Dictionary:
	var path = _config_path()
	var f = File.new()
	if path == "" or not f.file_exists(path):
		return {}
	if f.open(path, File.READ) != OK:
		return {}
	var text = f.get_as_text()
	f.close()
	var parsed = JSON.parse(text)
	if parsed.error != OK or typeof(parsed.result) != TYPE_DICTIONARY:
		return {}
	return parsed.result

func _write_config(cfg : Dictionary) -> bool:
	var path = _config_path()
	var f = File.new()
	if path == "" or f.open(path, File.WRITE) != OK:
		return false
	f.store_line(JSON.print(cfg, "\t"))
	f.close()
	return true

func _get_save_directory(req : Dictionary) -> Dictionary:
	var cfg = _read_config()
	var configured = str(cfg.get("save_directory", ""))
	var effective = _save_directory()
	var d = Directory.new()
	var configured_missing = (configured != ""
		and not d.dir_exists(_normalise_dir(configured)))
	var out = { "configured": configured, "effective": effective,
		"exists": effective != "" and d.dir_exists(effective),
		"source": ("setting" if configured != "" and not configured_missing
			else "Dungeondraft's map directory / " + SAVE_SUBDIR),
		"configured_missing": configured_missing,
		"config_file": _config_path() }
	if configured_missing:
		out["note"] = ("the configured save directory no longer exists, so saves go to "
			+ effective + " — set_save_directory with a new path, or \"\" to clear it")
	return _ok(out)

func _set_save_directory(req : Dictionary) -> Dictionary:
	var dir = _normalise_dir(str(req.get("path", "")))
	var cfg = _read_config()
	if dir == "":
		cfg.erase("save_directory")
		if not _write_config(cfg):
			return _err("could not write " + _config_path())
		return _ok({ "cleared": true, "effective": _save_directory() })
	var d = Directory.new()
	if not d.dir_exists(dir):
		return _err("no such directory: " + dir)
	cfg["save_directory"] = dir
	if not _write_config(cfg):
		return _err("could not write " + _config_path())
	return _ok({ "configured": dir, "effective": _save_directory() })

# Validate a caller-supplied map filename. Same shape as _output_path's rules:
# a bare name only, so there is no traversal to reason about and the save
# directory is the only place a map can land.
func _map_filename(raw) -> String:
	var name = str(raw).strip_edges()
	if name == "" or name.begins_with("."):
		return ""
	# All of these are illegal on Windows. Reject them on every platform so a
	# map name accepted on macOS never becomes an editor-save failure on Windows.
	var invalid = ["<", ">", ":", "\"", "/", "\\", "|", "?", "*"]
	for character in invalid:
		if name.find(character) != -1:
			return ""
	if name.ends_with(".") or name.ends_with(" "):
		return ""
	for i in range(name.length()):
		var code = name.ord_at(i)
		if code < 0x20 or code == 0x7F:
			return ""
	var base = name.split(".")[0].strip_edges().to_upper()
	var reserved = ["CON", "PRN", "AUX", "NUL"]
	if base in reserved:
		return ""
	var device_numbers = ["1", "2", "3", "4", "5", "6", "7", "8", "9"]
	if base.length() == 4 and base.substr(0, 3) in ["COM", "LPT"] and base.substr(3, 1) in device_numbers:
		return ""
	if not name.to_lower().ends_with(".dungeondraft_map"):
		name += ".dungeondraft_map"
	if name.to_utf8().size() > 255:
		return ""
	return name

func _save_map(req : Dictionary) -> Dictionary:
	if Global.Editor == null:
		return _err("no Editor available")
	var current = _current_map_file()

	if not req.has("filename") or str(req["filename"]).strip_edges() == "":
		if current == "":
			return _err("this map has no path yet. Pass filename= to save it " +
				"into the configured directory (see get_save_directory); " +
				"saving without one would open a modal Save As dialog that " +
				"freezes the bridge until closed by hand.")
		return _do_save(current, "existing path")

	var name = _map_filename(req["filename"])
	if name == "":
		return _err("'filename' must be a Windows-safe bare name — no path separators, " +
			"reserved devices, illegal characters, or trailing dots/spaces")
	var dir = _save_directory()
	if dir == "":
		return _err("no save directory: set one with set_save_directory")
	var d = Directory.new()
	if not d.dir_exists(dir):
		return _err("save directory does not exist: " + dir)
	var target = dir + "/" + name
	var configured_dir = _normalise_dir(str(_read_config().get("save_directory", "")))
	var fell_back = configured_dir != "" and not d.dir_exists(configured_dir)

	var f = File.new()
	if f.file_exists(target) and target != current and not bool(req.get("overwrite", false)):
		return _err(("'%s' already exists and is not the map you have open " +
			"(%s). Refusing to overwrite a file this session did not create or " +
			"open. Choose another name, or pass overwrite=true if you really " +
			"mean to replace it.") % [name, ("nothing open" if current == "" else current)])

	# Say which directory was used when it is not the one that was configured,
	# so a save landing somewhere unexpected explains itself in the reply.
	return _do_save(target, ("default directory — the configured one is gone"
		if fell_back else "configured directory"))

func _current_map_file() -> String:
	if Global.Editor == null:
		return ""
	var value = Global.Editor.get("CurrentMapFile")
	if value == null:
		return ""
	var text = str(value)
	if text == "Null" or text == "<null>":
		return ""
	return text

func _save_not_started_message() -> String:
	if _save_stale_path != "":
		return ("Dungeondraft did not start a save. The previous save (%s) " +
			"started and never finished, which is what a save that crashed " +
			"inside Dungeondraft looks like — and after one of those it refuses " +
			"every save, its own File > Save included. Nothing more can be " +
			"written this session: only a restart recovers, and a restart " +
			"discards every unsaved edit. Stop building and tell the user. The " +
			"last file written was %s (saves_seen %d).") % [_save_stale_path,
			(_last_save_path if _last_save_path != "" else "none"), _saves_seen]
	return ("Dungeondraft did not start a save. It declines while it is " +
		"backing up or busy, so retry in a few seconds. If it keeps declining, " +
		"check get_status.saving and the Dungeondraft log for an exception " +
		"under World.Save.")

func _do_save(path : String, how : String) -> Dictionary:
	if not Global.Editor.has_method("SaveMap"):
		return _err("this build exposes no Editor.SaveMap")
	Global.Editor.set_CurrentMapFile(path)

	var begins_before = _save_begins
	Global.Editor.SaveMap(false, null)
	if _signals.has("OnSaveBegin") and _signals.has("OnSaveEnd"):

		if _save_begins == begins_before:
			return _err(_save_not_started_message())
		return _ok({ "path": path, "via": how, "async": true, "started": true,
			"in_flight": _saving(),
			"note": "poll get_status until saving.in_flight is false, then " +
				"confirm saving.saves_seen rose: that is what proves the file " +
				"was written" })
	return _ok({ "path": path, "via": how, "async": true,
		"note": "Dungeondraft writes the file asynchronously; poll for it " +
			"rather than assuming it is on disk when this returns" })

func _open_map(req : Dictionary) -> Dictionary:
	var path = str(req.get("path", ""))
	if path == "":
		return _err("'path' is required — the .dungeondraft_map file to open")

	if not Global.Editor.has_method("ForceOpenMap"):
		return _err("this build exposes no Editor.ForceOpenMap")

	var f = File.new()
	if not f.file_exists(path):
		return _err("no such map file: " + path)
	Global.Editor.ForceOpenMap(path)
	return _ok({ "opening": path, "async": true,
		"note": "loading replaces the current map; unsaved work is lost" })

func _add_water(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var wm = level.get("WaterMesh")
	if wm == null: return _err("this map has no WaterMesh")
	if not wm.has_method("DrawPolygon"):
		return _err("WaterMesh exposes no DrawPolygon on this Dungeondraft build")

	var pts : PoolVector2Array
	if req.has("rect"):
		var r = req["rect"]
		if typeof(r) != TYPE_ARRAY or r.size() < 4:
			return _err("'rect' must be [x, y, w, h]")
		var x = float(r[0]); var y = float(r[1]); var w = float(r[2]); var h = float(r[3])
		if w <= 0.0 or h <= 0.0:
			return _err("'rect' width and height must be positive")
		pts = _points([[x, y], [x + w, y], [x + w, y + h], [x, y + h]])
	else:
		pts = _points(req.get("points", []))
	if pts.size() < 3:
		return _err("water needs a closed outline: 'rect':[x,y,w,h] or 'points' with >= 3 [x,y] pairs")

	var invert = bool(req.get("invert", false))
	var can_restyle = wm.has_method("Save") and wm.has_method("Load") and wm.has_method("UpdateMesh")
	var before := {}
	if can_restyle:
		before = _water_bodies(wm)
	wm.OnDrawingBegin(invert)
	wm.DrawPolygon(pts, invert)
	wm.OnDrawingEnd()
	if wm.has_method("UpdateMesh"):
		wm.UpdateMesh(false)
	elif wm.has_method("QueueUpdate"):
		wm.QueueUpdate()
	var out := { "added": true, "point_count": pts.size(), "inverted": invert }

	if can_restyle and not invert and before.size() > 0:
		var styles := {}
		for ref in before:
			styles[str(before[ref])] = before[ref]
		if styles.size() == 1:
			var style = styles.values()[0]
			if _recolour_water(wm, Color(style[0]), Color(style[1]),
					float(style[2]), {}) > 0:
				out["matched_level_style"] = true
	return _ok(out)

func _add_floor(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var shapes = level.get("FloorShapes")
	if shapes == null: return _err("this map has no FloorShapes")
	if not shapes.has_method("DrawRect"):
		return _err("FloorShapes exposes no DrawRect on this Dungeondraft build")

	var bad_floor_color = _bad_color(req, ["wall_color"])
	if bad_floor_color != null: return bad_floor_color

	var styling = (str(req.get("wall_asset", "")) != "" or str(req.get("wall_color", "")) != ""
		or req.has("smart_tile_id") or req.has("bevel"))
	if styling and Global.Editor.Tools.has("FloorShapeTool"):
		var floor_tool = Global.Editor.Tools["FloorShapeTool"]
		var floor_active := _enable_tool("FloorShapeTool", floor_tool)
		if req.has("smart_tile_id"):
			floor_tool.set("SmartTileId", int(req["smart_tile_id"]))
		if req.has("bevel"):
			floor_tool.set("Bevel", bool(req["bevel"]))
		if str(req.get("wall_asset", "")) != "":
			var wall_tex = _asset_tex("Walls", req["wall_asset"])
			if wall_tex == null:
				# Hand the tool back before bailing out, or the UI is left
				# holding a tool this handler enabled.
				_release_tool(floor_tool, floor_active)
				return _err("could not load wall asset: " + str(req.get("wall_asset")))
			floor_tool.set("WallTexture", wall_tex)
		if str(req.get("wall_color", "")) != "" and floor_tool.has_method("SetWallColor"):

			floor_tool.SetWallColor(_color(req["wall_color"], Color(1, 1, 1)))
		_release_tool(floor_tool, floor_active)

	var invert = bool(req.get("invert", false))
	var drew = ""
	if req.has("rect"):
		var r = req["rect"]
		if typeof(r) != TYPE_ARRAY or r.size() < 4:
			return _err("'rect' must be [x, y, w, h]")
		var w = float(r[2]); var h = float(r[3])
		if w <= 0.0 or h <= 0.0:
			return _err("'rect' width and height must be positive")
		shapes.DrawRect(Rect2(float(r[0]), float(r[1]), w, h), invert)
		drew = "rect"
	else:
		var pts = _points(req.get("points", []))
		if pts.size() < 3:
			return _err("a floor needs 'rect':[x,y,w,h] or 'points' with >= 3 [x,y] pairs")
		shapes.DrawPolygon(pts, invert)
		drew = "polygon"

	# Outlines are what give a floor its border edge; without this the shape is
	# there but reads as a flat fill.
	if shapes.has_method("FinalizeOutlines"):
		shapes.FinalizeOutlines()
	return _ok({ "added": true, "shape": drew, "inverted": invert })

# Read actual cave rasters. Counts are bounded by the native map raster size.
func _get_cave(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var cave = level.get("CaveMesh")
	if cave == null: return _err("cave mesh unavailable")
	var bm = cave.get_Bitmap()
	var entrances = cave.get("entranceBitmap")
	if not (bm is BitMap) or not (entrances is BitMap): return _err("cave bitmaps unavailable")
	var size = bm.get_size()
	if size != entrances.get_size(): return _err("cave bitmap sizes do not match")
	if size.x * size.y > 4000000: return _err("cave raster exceeds inspection budget")
	var floor_cells = 0
	var entrance_cells = 0
	for y in range(int(size.y)):
		for x in range(int(size.x)):
			var cell = Vector2(x, y)
			if bm.get_bit(cell): floor_cells += 1
			if entrances.get_bit(cell): entrance_cells += 1
	return _ok({ "level_id": level.ID, "bitmap_size": [int(size.x), int(size.y)],
		"cell_size_woxels": cave.get_CellSize(), "floor_cells": floor_cells,
		"entrance_cells": entrance_cells, "ground_color": "#" + cave.get_GroundColor().to_html(false),
		"wall_color": "#" + cave.get_WallColor().to_html(false) })

# A bounded circular blast mask removes cave border art without carving floor.
func _set_cave_entrance(req : Dictionary) -> Dictionary:
	for key in ["x", "y", "radius"]:
		var value = req.get(key, 256.0 if key == "radius" else null)
		if not (typeof(value) in [TYPE_INT, TYPE_REAL]): return _err(key + " must be a finite number")
		if is_nan(float(value)) or is_inf(float(value)): return _err(key + " must be finite")
	var radius = float(req.get("radius", 256.0))
	if radius <= 0 or radius > 2048: return _err("radius must be greater than 0 and at most 2048 woxels")
	if typeof(req.get("open", true)) != TYPE_BOOL: return _err("open must be a boolean")
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var dims = Global.World.WoxelDimensions
	var pos = Vector2(float(req["x"]), float(req["y"]))
	if pos.x < 0 or pos.y < 0 or pos.x > dims.x or pos.y > dims.y:
		return _err("entrance centre must be inside the map")
	var cave = _cave_mesh()
	if cave == null: return _err("cave mesh unavailable")
	var bm = cave.get_Bitmap()
	var entrances = cave.get("entranceBitmap")
	if not (bm is BitMap) or not (entrances is BitMap) or bm.get_size() != entrances.get_size():
		_release_tool_named("CaveBrush")
		return _err("cave bitmaps unavailable or sizes do not match")
	var size = bm.get_size()
	var cell_size = cave.get_CellSize()
	if cell_size <= 0:
		_release_tool_named("CaveBrush")
		return _err("invalid cave cell size")
	var rad = max(int(round(radius / cell_size)), 1)
	if rad > 128:
		_release_tool_named("CaveBrush")
		return _err("entrance exceeds raster edit budget")
	var edited = entrances.duplicate(true)
	var centre = _cave_cell(cave, pos)
	var changed = 0
	for y in range(max(int(centre.y) - rad, 0), min(int(centre.y) + rad + 1, int(size.y))):
		for x in range(max(int(centre.x) - rad, 0), min(int(centre.x) + rad + 1, int(size.x))):
			var cell = Vector2(x, y)
			if cell.distance_to(centre) <= rad and edited.get_bit(cell) != req.get("open", true):
				edited.set_bit(cell, req.get("open", true))
				changed += 1
	if changed > 0:
		cave.SetEntranceBitmap(edited)
		cave.FinalizeMeshAndBorders()
		cave.UpdateMesh()
	_release_tool_named("CaveBrush")
	return _ok({ "open": req.get("open", true), "changed_cells": changed,
		"radius_cells": rad, "bitmap_size": [int(size.x), int(size.y)] })

func _dig_cave(req : Dictionary) -> Dictionary:
	var bad_cave_color = _bad_color(req, ["ground_color", "wall_color"])
	if bad_cave_color != null: return bad_cave_color
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var cave = _cave_mesh()
	if cave == null: return _err("cave brush/mesh unavailable")
	if not cave.has_method("get_Bitmap") or not cave.has_method("SetBitmap"):
		return _err("cave mesh missing BitMap API")

	# Optional cave tints / floor texture (apply before the mesh rebuild).
	if req.has("ground_color") and str(req.get("ground_color", "")) != "":
		var gc = _color(req["ground_color"], Color(0.5, 0.5, 0.45))
		if cave.has_method("SetGroundColor"): cave.call("SetGroundColor", gc)
	if req.has("wall_color") and str(req.get("wall_color", "")) != "":
		var wc = _color(req["wall_color"], Color(0.5, 0.5, 0.45))
		if cave.has_method("SetWallColor"): cave.call("SetWallColor", wc)
	if req.has("texture") and str(req.get("texture", "")) != "":
		var tex = _asset_tex("Caves", req["texture"])
		if tex != null and cave.has_method("SetFloorTexture"):
			cave.call("SetFloorTexture", tex)

	# Path -> cell-space points.
	var pts := []
	if req.has("points"):
		for p in req["points"]:
			pts.append(_cave_cell(cave, Vector2(float(p[0]), float(p[1]))))
	else:
		pts.append(_cave_cell(cave, _xy(req, Global.World.WoxelDimensions * 0.5)))
	if pts.empty(): return _err("provide 'points':[[x,y]...] or x/y")

	var value = bool(req.get("value", req.get("dig", true)))
	var cs = cave.call("get_CellSize")
	var rad_cells = max(int(round(float(req.get("radius", 256.0)) / cs)), 1)

	var bm = cave.call("get_Bitmap")
	if bm == null:
		# _cave_mesh had to Enable the brush to hand back a mesh; do not leave
		# it active on the way out of an error path.
		_release_tool_named("CaveBrush")
		return _err("cave bitmap is null")
	var size = bm.call("get_size")
	var bw = int(size.x)
	var bh = int(size.y)
	# Rasterize the stroke: dab each point, then thicken the segments between them.
	var n := 0
	for cell in pts:
		n += _cave_stamp(bm, cell, rad_cells, value, bw, bh)
	for i in range(pts.size() - 1):
		_cave_stroke_segment(bm, pts[i], pts[i + 1], rad_cells, value, bw, bh)

	cave.call("SetBitmap", bm)
	if cave.has_method("FinalizeMeshAndBorders"):
		cave.call("FinalizeMeshAndBorders")
	cave.call("UpdateMesh")
	return _ok({
		"dug": value, "cells_painted": n, "radius_cells": rad_cells,
		"points": pts.size(), "bitmap_size": [bw, bh],
	})

# Stamp a filled circle of cells into the BitMap. Returns the count set.
func _cave_stamp(bm, c : Vector2, rad : int, value : bool, bw : int, bh : int) -> int:
	var n := 0
	var x0 = max(int(c.x) - rad, 0)
	var y0 = max(int(c.y) - rad, 0)
	var x1 = min(int(c.x) + rad, bw - 1)
	var y1 = min(int(c.y) + rad, bh - 1)
	for iy in range(y0, y1 + 1):
		for ix in range(x0, x1 + 1):
			if Vector2(ix, iy).distance_to(c) <= rad:
				bm.call("set_bit", Vector2(ix, iy), value)
				n += 1
	return n

# Stamp a thick line of cells between two cell-space points (no gaps between dabs).
func _cave_stroke_segment(bm, a : Vector2, b : Vector2, rad : int, value : bool, bw : int, bh : int) -> void:
	var steps = int(ceil(a.distance_to(b)))
	if steps <= 0:
		return
	for s in range(steps + 1):
		_cave_stamp(bm, a.linear_interpolate(b, float(s) / steps), rad, value, bw, bh)

func _clear_caves(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var cave = _cave_mesh()
	if cave == null: return _err("cave brush/mesh unavailable")
	var method = ""
	if cave.has_method("Clear"):
		cave.call("Clear")
		method = "Clear"
	elif cave.has_method("get_Bitmap") and cave.has_method("SetBitmap"):
		var bm = cave.call("get_Bitmap")
		if bm != null:
			var size = bm.call("get_size")
			for iy in range(int(size.y)):
				for ix in range(int(size.x)):
					bm.call("set_bit", Vector2(ix, iy), false)
			cave.call("SetBitmap", bm)
			method = "zero_bitmap"
	else:
		return _err("cave mesh missing Clear/BitMap API")
	if cave.has_method("FinalizeMeshAndBorders"):
		cave.call("FinalizeMeshAndBorders")
	cave.call("UpdateMesh")
	return _ok({ "cleared": true, "method": method })

func _list_elements(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null:
		return _err("no map open")
	var kind = req.get("kind", "objects")
	if not COLLECTIONS.has(kind):
		return _err("unknown kind '%s' (one of: %s)" % [kind, COLLECTIONS.keys()])
	var limit = int(req.get("limit", 200))
	var offset = int(req.get("offset", 0))
	if offset < 0:
		offset = 0
	var out := []

	var total := 0

	if kind == "portals":
		for wall in level.Walls.get_children():
			var wp = wall.get("Portals")
			if wp == null:
				continue
			for portal in wp:
				total += 1
				if total > offset and out.size() < limit:
					out.append(_describe_wall_portal(portal, wall))
	# Points are off unless asked for: this map has 844 paths, and returning
	# every polyline would bury the listing in tens of thousands of coordinates.
	var want_points = bool(req.get("include_points", false))
	for node in _real_children(level, kind):
		total += 1
		if total > offset and out.size() < limit:
			out.append(_describe(node, want_points))
	return _ok({ "kind": kind, "count": out.size(), "total": total,
		"offset": offset, "truncated": (offset + out.size()) < total,
		"elements": out })

func _get_composition_snapshot() -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null:
		return _err("no map open")
	var size = Global.World.WoxelDimensions
	var aggregate = _new_spatial_summary()
	var by_kind := {}
	for kind in COLLECTIONS:
		var summary = _new_spatial_summary()
		if kind == "portals":

			for wall in level.Walls.get_children():
				var wall_portals = wall.get("Portals")
				if wall_portals == null:
					continue
				for portal in wall_portals:
					_snapshot_add_node(summary, aggregate, portal, size)
		for node in _real_children(level, kind):
			_snapshot_add_node(summary, aggregate, node, size)
		by_kind[kind] = _finish_spatial_summary(summary)
	return _ok({
		"level_id": level.ID,
		"map_size_woxels": _vec(size),
		"grid": {
			"columns": 3, "rows": 3,
			"occupied_cells": _occupied_cells(aggregate["occupied_cells"]),
		},
		"by_kind": by_kind,
	})

func _new_spatial_summary() -> Dictionary:
	return { "count": 0, "bounds": null, "occupied_cells": {} }

func _snapshot_add_node(summary : Dictionary, aggregate : Dictionary, node, size : Vector2) -> void:
	summary["count"] += 1
	var points = node.get("Points")
	if points != null and points.size() > 0:
		for point in points:
			if point is Vector2:
				var world_point = node.to_global(point) if node is Node2D else point
				_snapshot_add_point(summary, aggregate, world_point, size)
		return
	var position = node.get("position")
	if node is Control:
		position = node.rect_position
	if position is Vector2:
		_snapshot_add_point(summary, aggregate, position, size)

func _snapshot_add_point(summary : Dictionary, aggregate : Dictionary, point : Vector2, size : Vector2) -> void:
	_extend_spatial_bounds(summary, point)
	_extend_spatial_bounds(aggregate, point)
	var cell = _composition_cell(point, size)
	if cell != "":
		summary["occupied_cells"][cell] = true
		aggregate["occupied_cells"][cell] = true

func _extend_spatial_bounds(summary : Dictionary, point : Vector2) -> void:
	var bounds = summary["bounds"]
	if bounds == null:
		summary["bounds"] = [point.x, point.y, point.x, point.y]
		return
	bounds[0] = min(float(bounds[0]), point.x)
	bounds[1] = min(float(bounds[1]), point.y)
	bounds[2] = max(float(bounds[2]), point.x)
	bounds[3] = max(float(bounds[3]), point.y)
	summary["bounds"] = bounds

func _composition_cell(point : Vector2, size : Vector2) -> String:
	if size.x <= 0.0 or size.y <= 0.0 or point.x < 0.0 or point.y < 0.0 \
			or point.x >= size.x or point.y >= size.y:
		return ""
	var column = min(2, int(point.x / (size.x / 3.0)))
	var row = min(2, int(point.y / (size.y / 3.0)))
	return "r%dc%d" % [row + 1, column + 1]

func _occupied_cells(cells : Dictionary) -> Array:
	var out := []
	for row in range(1, 4):
		for column in range(1, 4):
			var cell = "r%dc%d" % [row, column]
			if cells.has(cell):
				out.append(cell)
	return out

func _finish_spatial_summary(summary : Dictionary) -> Dictionary:
	return {
		"count": summary["count"],
		"bounds": summary["bounds"],
		"occupied_cells": _occupied_cells(summary["occupied_cells"]),
	}

func _describe_wall_portal(portal, wall) -> Dictionary:
	var pos = portal.get("position")
	if pos == null or not (pos is Vector2):
		pos = Vector2()
	var tangent = portal.get("Direction")
	if tangent == null or not (tangent is Vector2) or tangent.length() < 0.001:
		tangent = Vector2(1, 0)
	else:
		tangent = tangent.normalized()
	# Outward normal = tangent rotated 90 degrees, flipped to face away from the
	# wall's centroid (which is inside the enclosed room for a building loop).
	var normal = Vector2(-tangent.y, tangent.x)
	var centroid = _wall_centroid(wall)
	if centroid != null and (pos - centroid).dot(normal) < 0.0:
		normal = -normal
	var d := {
		"id": _id(portal), "kind": "wall_portal", "wall_id": _id(wall),
		"position": _vec(pos), "normal": _vec(normal),
		"facing": rad2deg(normal.angle()),
		"closed": bool(portal.get("Closed")),
	}
	var r = portal.get("Radius")
	if r != null:
		d["radius"] = float(r)
	var tex = portal.get("Texture")
	if tex != null and tex is Texture:
		d["asset"] = tex.resource_path
	return d

# Mean of a wall's points — used to orient a portal's normal outward. Returns
# null for a wall with no usable points.
func _wall_centroid(wall):
	var pts = wall.get("Points")
	if pts == null or pts.size() == 0:
		return null
	var sum = Vector2()
	for p in pts:
		sum += p
	return sum / pts.size()

func _get_element(req : Dictionary) -> Dictionary:
	var node = _resolve(req)
	if node == null:
		return _err("no element with id " + str(req.get("id")))
	var out = _describe(node)
	var effects = _patch_node_effects(node)
	if not effects.empty():
		out["unofficial_patch_effects"] = effects
	return _ok(out)

func _list_levels() -> Dictionary:
	var out := []
	var levels = Global.World.levels
	for i in range(levels.size()):
		var lv = levels[i]
		out.append({ "index": i, "id": lv.ID, "label": lv.Label })

	var current = Global.World.GetCurrentLevel()
	if current == null:
		return _err("no current level")
	var current_id = current.ID
	var current_index = -1
	for i in range(out.size()):
		if out[i]["id"] == current_id:
			current_index = i
			break
	if current_index == -1:
		return _err("current level id %d matches no level in %s" % [current_id, str(out)])
	return _ok({ "current_level_id": current_id, "current_index": current_index,
		"levels": out })

func _delete_level(req : Dictionary) -> Dictionary:
	if not req.has("id"):
		return _err("'id' is required — a level id from list_levels")
	var id = int(req["id"])
	# A map with no levels has nothing to draw on and no UI path back, so this
	# refuses rather than leaving the editor in a state the user cannot undo.
	if Global.World.levels.size() <= 1:
		return _err("refusing to delete the only level — a map must keep at least one")
	var lv = Global.World.GetLevelByID(id)
	if lv == null:
		return _err("no level with id %d" % id)
	var label = str(lv.Label)
	Global.World.DeleteLevel(lv)
	_rearm_active_tool()
	return _ok({ "deleted_id": id, "label": label,
		"level_count": Global.World.levels.size(),
		"note": "not undoable through this bridge" })

func _place_object(req : Dictionary) -> Dictionary:
	var tint_error = _refuse_modulate(req)
	if tint_error != null: return tint_error
	var bad_place_object = _bad_sorting(req)
	if bad_place_object != null: return bad_place_object
	var bad_place_layer = _bad_layer(req)
	if bad_place_layer != null: return bad_place_layer
	var bad_place_color = _bad_color(req, ["color", "modulate"])
	if bad_place_color != null: return bad_place_color
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var tex = _asset_tex("Objects", req.get("asset", ""))
	if tex == null: return _err("could not load object asset: " + str(req.get("asset")))

	var wants_color = req.has("color") and str(req.get("color", "")) != ""
	if wants_color:
		return _place_object_tinted(req, level, tex)

	var prop = _new_object(level, int(req.get("sorting", 0)),
		int(req.get("layer", DEFAULT_OBJECT_LAYER)))
	prop.SetTexture(tex)
	prop.position = _xy(req, Global.World.WoxelDimensions * 0.5)
	var s = float(req.get("scale", 1.0))
	prop.scale = Vector2(s, s)
	prop.rotation = deg2rad(float(req.get("rotation", 0.0)))
	var out = { "id": _id(prop), "position": _vec(prop.position) }

	out["layer"] = prop.z_index
	if req.has("block_light"):
		# Same implementation as modify_object: placing with block_light FALSE
		# used to call UpdateOccluders anyway, which rebuilt the occluders and
		# re-enabled exactly what the caller had asked to turn off.
		_apply_block_light(prop, bool(req["block_light"]))
		out["block_light"] = bool(prop.get("BlockLight"))

	if _mask_fraction(tex) > 0.0:
		out["colorable"] = true
		out["note"] = ("this asset has an unpainted colour mask and will render " +
			"flat RED. Colour is baked at placement, so re-place it with " +
			"color=\"#rrggbb\" — modify_object cannot repaint it.")
	if req.has("modulate") and str(req.get("modulate", "")) != "":
		# Reject rather than fall back: an unusable hex would apply the identity
		# colour and still report modulate_applied.
		if not _modulate_requested(req):
			return _err("'modulate' must be a hex colour like '#3366ff', got: " + str(req["modulate"]))
		if _set_node_modulate(prop, _color(req["modulate"], Color(1, 1, 1))):
			out["modulate_applied"] = true
	return _ok(out)

func _place_objects(req : Dictionary) -> Dictionary:
	var items = req.get("objects", [])
	if typeof(items) != TYPE_ARRAY or items.empty():
		return _err("'objects' must be a non-empty array of {asset, x, y, ...} entries")
	var compact = bool(req.get("compact", false))
	var cap = MAX_FILE_BATCH_ITEMS if compact else MAX_BATCH_ITEMS
	if items.size() > cap:
		return _err("'objects' is capped at %d per call" % cap)
	if Global.World.GetCurrentLevel() == null:
		return _err("no map open")

	for i in range(items.size()):
		var item = items[i]
		if typeof(item) != TYPE_DICTIONARY:
			return _err("objects[%d] must be an object with at least an 'asset'" % i)
		var tint_error = _refuse_modulate(item)
		if tint_error != null:
			return _err("objects[%d]: %s" % [i, tint_error["error"]])
		var asset = str(item.get("asset", ""))
		if asset == "":
			return _err("objects[%d] has no 'asset'" % i)
		if _asset_tex("Objects", asset) == null:
			return _err(("objects[%d]: '%s' is not an Objects asset, so nothing was " +
				"placed. Take paths from list_assets(category='Objects').") % [i, asset])

	var placed := []
	for i in range(items.size()):
		var res = _place_object(items[i])
		if not res.get("ok", false):
			# Roll back, so the batch is all-or-nothing like scatter_objects.
			var stuck := []
			for made in placed:
				if not _delete_element({ "id": int(made["id"]) }).get("ok", false):
					stuck.append(int(made["id"]))
			if stuck.empty():
				return _err(("objects[%d] failed after %d placement(s), all of which were " +
					"removed — nothing remains on the map. Cause: %s")
					% [i, placed.size(), str(res.get("error"))])
			return _err(("objects[%d] failed after %d placement(s); %d could NOT be removed " +
				"(ids %s) and are still on the map — delete them before retrying. " +
				"Cause: %s") % [i, placed.size(), stuck.size(), str(stuck),
				str(res.get("error"))])
		var out = res["result"]
		var entry := { "id": int(out["id"]), "position": out["position"] }
		# Carry the per-item warnings that matter for the next decision: a
		# colourable asset placed without a colour is a flat red shape, and
		# colour cannot be added afterwards.
		if out.get("colorable", false):
			entry["colorable"] = true
		if out.has("layer"):
			entry["layer"] = out["layer"]
		placed.append(entry)

	var colorable := []
	for entry in placed:
		if entry.get("colorable", false):
			colorable.append(entry["id"])
	var out_note = ""
	if not colorable.empty():
		out_note = ("ids %s were placed from colourable assets with no color= and " +
			"render flat RED. Colour is baked at placement: delete them and place " +
			"again with color=\"#rrggbb\".") % str(colorable)
	if compact:
		# Counts and id ranges, not an entry per object: echoing 600 entries
		# back is the token cost the file path exists to avoid.
		var shown = colorable.slice(0, 19) if colorable.size() > 20 else colorable
		if not colorable.empty():
			out_note = ("%d object(s) were placed from colourable assets with no " +
				"color= and render flat RED (ids %s%s). Colour is baked at " +
				"placement: delete them and place again with color=\"#rrggbb\".") \
				% [colorable.size(), str(shown), " ..." if colorable.size() > 20 else ""]
		return _ok({ "placed": placed.size(), "id_ranges": _id_ranges(_ids_of(placed)),
			"colorable_without_color": colorable.size(), "undoable": true,
			"note": out_note })
	return _ok({ "placed": placed.size(), "objects": placed,
		"ids": _ids_of(placed), "undoable": true, "note": out_note })

# [[first, last], ...] for runs of consecutive ids, in placement order.
func _id_ranges(ids : Array) -> Array:
	var out := []
	for id in ids:
		if not out.empty() and int(out[-1][1]) + 1 == int(id):
			out[-1][1] = int(id)
		else:
			out.append([int(id), int(id)])
	return out

func _ids_of(entries : Array) -> Array:
	var out := []
	for entry in entries:
		out.append(entry["id"])
	return out

# Colour-bearing placement through ObjectTool. Kept separate so the common,
# uncoloured path stays direct and cheap.
func _place_object_tinted(req : Dictionary, level, tex) -> Dictionary:
	if not Global.Editor.Tools.has("ObjectTool"):
		return _err("colour requires ObjectTool, which this build does not expose")
	var otool = Global.Editor.Tools["ObjectTool"]
	if not (otool.has_method("Enable") and otool.has_method("set_Texture") and otool.has_method("get_Preview")):
		return _err("ObjectTool lacks Enable/set_Texture/get_Preview; cannot place a tinted object")

	var was_active := _enable_tool("ObjectTool", otool)
	otool.set_Texture(tex)
	var preview = otool.get_Preview()
	if preview == null:
		_release_tool(otool, was_active)
		return _err("ObjectTool exposed no Preview; cannot place a tinted object")
	if not preview.has_method("SetCustomColor"):
		_release_tool(otool, was_active)
		return _err("this asset's Preview exposes no SetCustomColor")

	# Reject a bad modulate BEFORE placing. Colour is baked at placement and
	# cannot be undone, so refusing after the object exists would leave a
	# permanently mis-coloured prop behind with an error return.
	if req.has("modulate") and str(req.get("modulate", "")) != "" and not _modulate_requested(req):
		_release_tool(otool, was_active)
		return _err("'modulate' must be a hex colour like '#3366ff', got: " + str(req["modulate"]))

	# Set the whole transform on the Preview: Confirm commits a copy of it, so
	# this is what carries scale and rotation onto the placed object.
	var scl = float(req.get("scale", 1.0))
	preview.SetCustomColor(_color(req["color"], Color(1, 1, 1)))
	preview.position = _xy(req, Global.World.WoxelDimensions * 0.5)
	preview.scale = Vector2(scl, scl)
	preview.rotation = deg2rad(float(req.get("rotation", 0.0)))

	var known := {}
	for child in level.Objects.get_children():
		known[child.get_instance_id()] = true

	if otool.has_method("Confirm"):
		otool.Confirm()

	var preview_now = otool.get_Preview()
	var old_preview = null
	if is_instance_valid(preview):
		old_preview = preview
	var placed = null
	var kids = level.Objects.get_children()
	for i in range(kids.size() - 1, -1, -1):
		var child = kids[i]
		if preview_now != null and child == preview_now:
			continue
		if known.has(child.get_instance_id()) and child != old_preview:
			continue
		placed = child
		break
	if placed == null:
		_release_tool(otool, was_active)
		return _err("ObjectTool.Confirm did not place the object")

	# Re-apply the transform to the committed node. Confirm carrying it across
	# is what the Preview writes above rely on; doing it again here makes the
	# result independent of that, and is what the response reports.
	placed.position = _xy(req, Global.World.WoxelDimensions * 0.5)
	placed.scale = Vector2(scl, scl)
	placed.rotation = deg2rad(float(req.get("rotation", 0.0)))

	placed.z_index = int(req.get("layer", DEFAULT_OBJECT_LAYER))

	var out = { "id": _id(placed), "position": _vec(placed.position), "placed_via": "ObjectTool" }
	out["layer"] = placed.z_index
	if req.has("block_light"):
		_apply_block_light(placed, bool(req["block_light"]))
		out["block_light"] = bool(placed.get("BlockLight"))
	if req.has("modulate") and str(req.get("modulate", "")) != "":
		if _set_node_modulate(placed, _color(req["modulate"], Color(1, 1, 1))):
			out["modulate_applied"] = true
	_release_tool(otool, was_active)
	return _ok(out)

func _draw_wall(req : Dictionary) -> Dictionary:
	var bad_wall_color = _bad_color(req, ["color"])
	if bad_wall_color != null: return bad_wall_color
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var pts = _points(req.get("points", []))
	if pts.size() < 2: return _err("'points' needs >= 2 [x,y] pairs")
	var tex = _asset_tex("Walls", req.get("asset", ""))
	var wall = level.Walls.AddWall(
		pts, tex, _wall_color(req, tex),
		bool(req.get("loop", false)), bool(req.get("shadow", true)),
		int(req.get("type", 0)), int(req.get("joint", 1)), true)
	if wall == null: return _err("AddWall returned null (bad asset/points?)")
	return _ok({ "id": _id(wall), "point_count": pts.size() })

func _wall_color(req : Dictionary, tex) -> Color:
	if req.has("color") and str(req.get("color", "")) != "":
		return _color(req["color"], Color(1, 1, 1))
	if tex != null and Global.Editor.Tools.has("WallTool"):
		var wt = Global.Editor.Tools["WallTool"]
		if wt.has_method("GetWallColor"):
			var c = wt.GetWallColor(tex)
			if c != null and c is Color:
				return c
	return Color(1, 1, 1)

func _draw_path(req : Dictionary) -> Dictionary:
	var bad_draw_path = _bad_sorting(req)
	if bad_draw_path != null: return bad_draw_path
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var pts = _points(req.get("points", []))
	if pts.size() < 2: return _err("'points' needs >= 2 [x,y] pairs")
	var tex = _asset_tex("Paths", req.get("asset", ""))
	if tex == null: return _err("could not load path asset: " + str(req.get("asset")))
	var path = level.Pathways.CreatePath(
		tex, int(req.get("layer", 0)), int(req.get("sorting", 0)),
		bool(req.get("fade_in", false)), bool(req.get("fade_out", false)),
		bool(req.get("grow", false)), bool(req.get("shrink", false)))
	_mark_saveable(path)
	path.SetEditPoints(pts)
	if req.has("smoothness"):
		path.Smoothness = float(req["smoothness"])
		path.Smooth()
	if req.has("width"):
		path.SetWidthScale(float(req["width"]))
	path.UpdateGradient()
	return _ok({ "id": _id(path), "point_count": pts.size() })

func _add_light(req : Dictionary) -> Dictionary:
	var bad_light_color = _bad_color(req, ["color"])
	if bad_light_color != null: return bad_light_color
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var light = _new_light(level)
	light.position = _xy(req, Global.World.WoxelDimensions * 0.5)
	light.color = _color(req.get("color", ""), Color(1, 0.9, 0.7))
	light.energy = float(req.get("energy", 1.0))
	light.texture_scale = float(req.get("range", 1.0))
	light.shadow_enabled = bool(req.get("shadows", true))
	var tex = _asset_tex("Lights", req.get("asset", ""))
	if tex != null:
		light.texture = tex
	return _ok({ "id": _id(light), "position": _vec(light.position) })

func _nearest_wall_segment(level, pos : Vector2):
	var best = null
	for wall in level.Walls.get_children():
		var pts = wall.get("Points")
		if pts == null or pts.size() < 2:
			continue
		var seg_count = pts.size() - 1
		if wall.get("Loop"):
			seg_count = pts.size()
		for i in range(seg_count):
			var a = pts[i]
			var b = pts[(i + 1) % pts.size()]
			var closest = _closest_point_on_segment(pos, a, b)
			var dist = pos.distance_to(closest)
			if best == null or dist < best.distance:
				var dir = (b - a)
				if dir.length() > 0.001:
					dir = dir.normalized()
				best = {
					"wall": wall, "point_index": i, "closest": closest,
					"direction": dir, "distance": dist,
				}
	return best

func _portal_at(wall, pos : Vector2, tol : float = 1.0):
	var portals = wall.get("Portals")
	if portals == null:
		return null
	for portal in portals:
		var ppos = portal.get("position")
		if ppos != null and ppos is Vector2 and ppos.distance_to(pos) <= tol:
			return portal
	return null

func _closest_point_on_segment(p : Vector2, a : Vector2, b : Vector2) -> Vector2:
	var ab = b - a
	var len2 = ab.dot(ab)
	if len2 < 0.0001:
		return a
	var t = clamp((p - a).dot(ab) / len2, 0.0, 1.0)
	return a + ab * t

func _add_portal(req : Dictionary) -> Dictionary:
	if not (str(req.get("mount", "wall")) in ["wall", "free"]):
		return _err("'mount' must be \"wall\" or \"free\", got: " + str(req.get("mount")))
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var tex = _asset_tex("Portals", req.get("asset", ""))
	if tex == null: return _err("could not load portal asset: " + str(req.get("asset")))
	var pos = _xy(req, Global.World.WoxelDimensions * 0.5)
	var closed = bool(req.get("closed", false))
	var radius = float(req.get("radius", 64.0))
	# mount: "wall" (default) snaps onto the nearest wall and cuts a gap;
	# "free" forces a freestanding portal. snap_max caps how far (woxels) a
	# wall may be and still capture the portal.
	var mount = str(req.get("mount", "wall"))
	var snap_max = float(req.get("snap_max", 256.0))
	if mount != "free":
		var seg = _nearest_wall_segment(level, pos)
		if seg != null and seg.distance <= snap_max:
			# Mount onto the wall: snap to the segment, face along it, and let
			# the wall remake its lines so the portal cuts a gap.
			var flip = bool(req.get("flip", false))
			var portal = seg.wall.AddPortal(
				tex, closed, seg.closest, seg.direction,
				seg.point_index, radius, flip)
			seg.wall.RemakeLines()
			if portal == null:

				var blocker = _portal_at(seg.wall, seg.closest)
				if blocker != null:
					return _err(("a portal is already mounted there: portal %d " +
						"sits at (%d, %d) on wall %d, %d woxel(s) from the " +
						"point asked for. Move along the wall, or delete that " +
						"portal first.") % [
						_id(blocker), int(blocker.position.x),
						int(blocker.position.y), _id(seg.wall),
						int(blocker.position.distance_to(seg.closest))])
				return _err(("could not mount a portal there: snapped to wall " +
					"%d segment %d at (%d, %d), %d woxel(s) from the point " +
					"asked for, radius %d. No portal is already at that point, " +
					"so this is a refusal the bridge cannot yet explain — try " +
					"another point along the same wall.") % [
					_id(seg.wall), seg.point_index, int(seg.closest.x),
					int(seg.closest.y), int(seg.distance), int(radius)])
			return _ok({
				"id": _id(portal), "kind": "wall_portal",
				"position": _vec(seg.closest), "wall_id": _id(seg.wall),
				"snapped": _vec(seg.closest), "snap_distance": seg.distance,
			})
		if mount == "wall" and not req.get("fallback_free", true):
			return _err("no wall within snap_max (%d) of portal position" % int(snap_max))
	# Freestanding fallback (no wall nearby, or mount == "free").
	level.CreateFreestandingPortal(
		tex, pos, closed, radius, deg2rad(float(req.get("rotation", 0.0))))
	# CreateFreestandingPortal returns void; the new portal is the last child.
	var kids = level.Portals.get_children()
	if kids.empty(): return _err("portal was not created")
	var freestanding = _mark_saveable(kids[kids.size() - 1])
	return _ok({ "id": _id(freestanding), "kind": "portal", "position": _vec(pos) })

func _add_roof(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var pts = _points(req.get("points", []))
	if pts.size() < 2: return _err("'points' needs >= 2 [x,y] ridge points")
	var tex = _asset_tex("Roofs", req.get("asset", ""))
	if tex == null: return _err("could not load roof asset: " + str(req.get("asset")))
	var roof = level.Roofs.CreateRoof(int(req.get("sorting", 0)))
	_mark_saveable(roof)
	roof.Set(pts, float(req.get("width", 256.0)), int(req.get("type", 0)))

	if req.has("sunlight") and roof.has_method("SetSunlight"):
		roof.SetSunlight(bool(req["sunlight"]), float(req.get("sun_angle", 315.0)),
			float(req.get("sun_contrast", 0.25)))
	roof.SetTileTexture(tex)
	return _ok({ "id": _id(roof), "ridge_points": pts.size() })

func _pattern_draw_layer(node) -> int:
	var draw_layer := 0
	var current = node
	while current != null:
		if current is Node2D:
			draw_layer += current.z_index
			if not current.z_as_relative:
				break
		current = current.get_parent()
	return draw_layer

func _place_pattern(req : Dictionary) -> Dictionary:
	var bad_pattern_color = _bad_color(req, ["color"])
	if bad_pattern_color != null: return bad_pattern_color
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	if not Global.Editor.Tools.has("PatternShapeTool"):
		return _err("PatternShapeTool not available")
	var category = str(req.get("category", "Patterns"))
	if category in SMART_TILE_CATEGORIES:
		return _err(("category '%s' cannot be drawn as a pattern: a smart tileset " +
			"is an atlas of edge/corner variants that only the tile layer can " +
			"select between, so a pattern fill renders SOLID BLACK. Use " +
			"'Simple Tiles' or 'Materials' instead.") % category)
	var tex = _asset_tex(category, req.get("asset", ""))
	if tex == null: return _err("could not load pattern asset: " + str(req.get("asset")))

	var want_layer = int(req.get("z", -100))
	if want_layer < LAYER_MIN or want_layer > LAYER_MAX or want_layer % LAYER_STEP != 0:
		return _err("'z' must be a persistent layer value: -500..900 in steps of 100")
	# Validate geometry before changing tool state.
	if req.has("rect"):
		if typeof(req["rect"]) != TYPE_ARRAY or req["rect"].size() < 4:
			return _err("'rect' must be [x, y, w, h]")
	elif req.has("points"):
		if _points(req["points"]).size() < 3:
			return _err("'points' needs >= 3 [x,y] pairs for a polygon")
	else:
		return _err("provide 'rect':[x,y,w,h] or 'points':[[x,y]...]")
	var prior_layer = _get_tool_layer({ "tool": "PatternShapeTool" })
	if not prior_layer.get("ok", false): return prior_layer
	var layer_change = _set_tool_layer({ "tool": "PatternShapeTool", "layer": want_layer })
	if not layer_change.get("ok", false): return layer_change
	if not layer_change["result"].get("applied", false):
		return _err("PatternShapeTool did not accept the requested persistent layer")
	var shapes = level.PatternShapes
	var tool = Global.Editor.Tools["PatternShapeTool"]
	tool.Texture = tex

	var color
	var used_default = false
	if req.has("color") and str(req.get("color", "")) != "":
		color = _color(req["color"], DEFAULT_PATTERN_TINT)
	else:
		color = DEFAULT_PATTERN_TINT
		used_default = true
	if color.a < 0.05:
		color = Color(color.r, color.g, color.b, 1.0)
	tool.Color = color
	var rotation = float(req.get("rotation", 0.0))
	if tool.get("Rotation") != null:
		tool.Rotation.value = rotation

	var existing_shapes := {}
	for existing_shape in shapes.GetShapes():
		existing_shapes[existing_shape.get_instance_id()] = true
	var kind : String
	if req.has("rect"):
		var r = req["rect"]
		if typeof(r) != TYPE_ARRAY or r.size() < 4:
			return _err("'rect' must be [x, y, w, h]")
		shapes.DrawRect(Rect2(float(r[0]), float(r[1]), float(r[2]), float(r[3])), false)
		kind = "rect"
	elif req.has("points"):
		var pts = _points(req["points"])
		if pts.size() < 3:
			return _err("'points' needs >= 3 [x,y] pairs for a polygon")
		shapes.DrawPolygon(pts, false)
		kind = "polygon"
	else:
		return _err("provide 'rect':[x,y,w,h] or 'points':[[x,y]...]")

	var all = shapes.GetShapes()
	var result := { "shape": kind, "category": category, "shape_count": all.size() }
	if color is Color:
		result["color"] = "#" + color.to_html(true)
	if used_default:
		# Signal we applied the neutral default (no per-texture tint exists for
		# patterns; pass an explicit `color` for an exact look).
		result["used_default_tint"] = true
	# Enumeration is grouped by layer; the new shape need not be last.
	for shape in all:
		if existing_shapes.has(shape.get_instance_id()):
			continue
		if shape.has_method("SetOptions"):
			shape.SetOptions(tex, color, rotation)
		shape.z_as_relative = true
		shape.z_index = 0
		result["id"] = _id(shape)
		result["z_index"] = _pattern_draw_layer(shape)
	var restored = _set_tool_layer({ "tool": "PatternShapeTool", "layer": prior_layer["result"]["layer"] })
	if not restored.get("ok", false) or not restored.get("result", {}).get("applied", false):
		result["warning"] = "Pattern created, but the previous tool layer could not be restored"
	return _ok(result)

func _scatter_objects(req : Dictionary) -> Dictionary:
	var bad_scatter_objects = _bad_sorting(req)
	if bad_scatter_objects != null: return bad_scatter_objects
	var bad_scatter_layer = _bad_layer(req)
	if bad_scatter_layer != null: return bad_scatter_layer
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")

	var assets = req.get("assets", [])
	if typeof(assets) != TYPE_ARRAY or assets.size() == 0:
		return _err("'assets' must be a non-empty array of Objects asset paths")

	for candidate in assets:
		if _asset_tex("Objects", str(candidate)) == null:
			return _err(("'%s' is not an Objects asset, so nothing was scattered. " +
				"Every entry in 'assets' must come from list_assets(category='Objects').")
				% str(candidate))
	var r = req.get("rect", null)
	if typeof(r) != TYPE_ARRAY or r.size() < 4:
		return _err("'rect' must be [x, y, w, h] in woxels")
	var rx = float(r[0]); var ry = float(r[1]); var rw = float(r[2]); var rh = float(r[3])
	if rw <= 0.0 or rh <= 0.0:
		return _err("'rect' width and height must be positive")

	var count = int(req.get("count", 12))
	if count <= 0 or count > 500:
		return _err("'count' must be between 1 and 500")
	var smin = float(req.get("scale_min", 0.9))
	var smax = float(req.get("scale_max", 1.1))
	if smin <= 0.0 or smax < smin:
		return _err("need 0 < scale_min <= scale_max")
	var rmin = float(req.get("rotation_min", 0.0))
	var rmax = float(req.get("rotation_max", 360.0))
	var min_gap = float(req.get("min_gap", 0.0))
	var color = str(req.get("color", ""))

	var rng = RandomNumberGenerator.new()
	if req.has("seed"):
		rng.seed = int(req["seed"])
	else:
		rng.randomize()

	var placed := []
	var points := []
	var attempts = 0
	var max_attempts = count * 30
	while placed.size() < count and attempts < max_attempts:
		attempts += 1
		var px = rx + rng.randf() * rw
		var py = ry + rng.randf() * rh
		if min_gap > 0.0:
			var too_close = false
			for q in points:
				if Vector2(px, py).distance_to(q) < min_gap:
					too_close = true
					break
			if too_close:
				continue
		var sub := {
			"asset": assets[rng.randi_range(0, assets.size() - 1)],
			"x": px, "y": py,
			"scale": smin + rng.randf() * (smax - smin),
			"rotation": rmin + rng.randf() * (rmax - rmin),
			"sorting": int(req.get("sorting", 0)),
			"layer": int(req.get("layer", DEFAULT_OBJECT_LAYER)),
		}
		if color != "":
			sub["color"] = color
		var res = _place_object(sub)
		if not res.get("ok", false):

			var stuck := []
			for made in placed:
				if not _delete_element({ "id": int(made) }).get("ok", false):
					stuck.append(int(made))
			if stuck.empty():
				return _err(("scatter failed after %d placement(s), all of which were " +
					"removed — nothing remains on the map. Cause: %s")
					% [placed.size(), str(res.get("error"))])
			return _err(("scatter failed after %d placement(s); %d could NOT be removed " +
				"(ids %s) and are still on the map — delete them before retrying. " +
				"Cause: %s") % [placed.size(), stuck.size(), str(stuck),
				str(res.get("error"))])
		points.append(Vector2(px, py))
		placed.append(res["result"]["id"])

	return _ok({ "placed": placed.size(), "ids": placed, "attempts": attempts,
		"requested": count,
		"note": ("min_gap too large for this area; placed fewer than requested" if placed.size() < count else "") })

func _room_rollback(wall_id, floor_error) -> Dictionary:
	var removed = false
	if wall_id != null:
		var del = _delete_element({ "id": int(wall_id) })
		removed = del.get("ok", false)
	if removed:
		return _err(("the room's floor could not be created (%s), so the room was not " +
			"built and the wall drawn for it has been removed. Nothing remains on the map.")
			% str(floor_error))
	return _err(("the room's floor could not be created (%s), and the wall drawn for it " +
		"(id %s) could NOT be removed. Delete that wall before retrying, or the retry " +
		"will leave two walls on top of each other.") % [str(floor_error), str(wall_id)])

func _build_room(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")

	# Normalize the boundary to a list of [x,y] points (rect -> 4 corners).
	var pts_raw := []
	if req.has("rect"):
		var r = req["rect"]
		if typeof(r) != TYPE_ARRAY or r.size() < 4:
			return _err("'rect' must be [x, y, w, h]")
		var x = float(r[0]); var y = float(r[1]); var w = float(r[2]); var h = float(r[3])
		pts_raw = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
	elif req.has("points"):
		if typeof(req["points"]) != TYPE_ARRAY or req["points"].size() < 3:
			return _err("'points' needs >= 3 [x,y] pairs")
		pts_raw = req["points"]
	else:
		return _err("provide 'rect':[x,y,w,h] or 'points':[[x,y]...]")

	var planned_floor = str(req.get("floor", "pattern"))
	# Only a floor asset that was actually NAMED is validated: build_room
	# without floor_asset is supported and lets the pattern handler choose.
	if planned_floor == "pattern" and str(req.get("floor_asset", "")) != "":
		var planned_cat = str(req.get("floor_category", "Simple Tiles"))
		if _asset_tex(planned_cat, req.get("floor_asset", "")) == null:
			return _err(("cannot build this room: floor asset '%s' is not in category " +
				"'%s', so NOTHING was created. Choose one from " +
				"list_assets(category='%s').")
				% [str(req.get("floor_asset", "")), planned_cat, planned_cat])
	elif planned_floor == "terrain" and str(req.get("floor_asset", "")) != "":
		if _asset_tex("Terrain", req.get("floor_asset", "")) == null:
			return _err(("cannot build this room: floor asset '%s' is not a Terrain " +
				"asset, so NOTHING was created. Choose one from " +
				"list_assets(category='Terrain').") % str(req.get("floor_asset", "")))

	var result := {}

	# 1) Wall loop along the boundary.
	var wall_req := {
		"points": pts_raw, "loop": true,
		"asset": req.get("wall_asset", ""),
		"type": req.get("wall_type", 0), "joint": req.get("wall_joint", 1),
		"shadow": req.get("wall_shadow", true),
	}
	var wall_res = _draw_wall(wall_req)
	if not wall_res.get("ok", false):
		return wall_res
	result["wall_id"] = wall_res["result"].get("id")

	# 2) Floor along the SAME boundary (no inset — the wall covers the seam).
	var floor_kind = str(req.get("floor", "pattern"))
	if floor_kind == "pattern":
		var fr := {
			"points": pts_raw,
			"asset": req.get("floor_asset", ""),
			"category": req.get("floor_category", "Simple Tiles"),
		}
		if req.has("floor_color"): fr["color"] = req["floor_color"]
		if req.has("floor_z"): fr["z"] = req["floor_z"]
		var fres = _place_pattern(fr)
		if fres.get("ok", false):
			result["floor_id"] = fres["result"].get("id")
		else:
			return _room_rollback(result.get("wall_id"), fres.get("error"))
	elif floor_kind == "terrain":
		var tr := {
			"points": pts_raw, "slot": int(req.get("floor_slot", 1)),
		}
		if req.has("floor_asset") and str(req.get("floor_asset", "")) != "":
			tr["asset"] = req["floor_asset"]
		var tres = _fill_region(tr)
		if tres.get("ok", false):
			result["floor_pixels"] = tres["result"].get("pixels")
		else:
			return _room_rollback(result.get("wall_id"), tres.get("error"))
	# floor_kind == "none" -> walls only

	result["points"] = pts_raw
	return _ok(result)

# A Dungeondraft Text extends Godot LineEdit: the string is the inherited
# `.text`, position is `rect_position`, and size/color must be applied through
# the TextTool (see below) because UpdateText repaints from the tool's settings.
func _add_text(req : Dictionary) -> Dictionary:
	var bad_text_color = _bad_color(req, ["color"])
	if bad_text_color != null: return bad_text_color
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	# An empty string creates an invisible element that still occupies an id and
	# still counts in get_status — junk the caller cannot see to clean up.
	if str(req.get("text", "")).strip_edges() == "":
		return _err("'text' must not be empty — an empty label is invisible on the map")
	var text = level.Texts.CreateText()
	_mark_saveable(text)
	# A Text extends LineEdit (a Control): place it via rect_position, not the
	# Node2D `.position` (which silently does nothing on a Control).
	text.rect_position = _xy(req, Global.World.WoxelDimensions * 0.5)
	text.text = str(req.get("text", ""))

	var size = int(req.get("size", 32))
	if size <= 0:
		size = 32
	var col = _color(req.get("color", ""), Color(0, 0, 0, 1))
	var font_name = str(req.get("font", text.fontName))
	if req.has("font"):
		text.SetFont(font_name, size)
	if Global.Editor.Tools.has("TextTool"):
		var tt = Global.Editor.Tools["TextTool"]
		var saved_size = tt.FontSize
		var saved_color = tt.FontColor
		tt.FontSize = size
		tt.FontColor = col
		tt.focus = text
		tt.UpdateText(text)
		tt.FontSize = saved_size
		tt.FontColor = saved_color
	else:
		# No tool available: best-effort direct set.
		text.fontSize = size
		text.fontColor = col
		text.SetFont(font_name, size)
		text.SetFontColor(col)
	return _ok({ "id": _id(text), "size": text.fontSize, "color": "#" + text.fontColor.to_html(false) })

# ---------------------------------------------------------------------------
# Terrain
# ---------------------------------------------------------------------------

func _bad_slot(req : Dictionary):
	if not req.has("slot"):
		return null
	var slot = int(req["slot"])
	if slot < 0 or slot > 7:
		return _err("'slot' must be 0-7 (four channels per splat image, two images), got %d" % slot)
	return null

func _bad_color(req : Dictionary, keys : Array):
	for key in keys:
		var name = str(key)
		if not req.has(name) or str(req[name]) == "":
			continue
		if _color_requested(req, name):
			continue
		return _err(("'%s' must be a hex colour like '#3366ff' or [r,g,b] " +
			"floats 0..1, got: %s") % [name, str(req[name])])
	return null

func _bad_sorting(req : Dictionary):
	if not req.has("sorting"):
		return null
	var s = int(req["sorting"])
	if s != 0 and s != 1:
		return _err("'sorting' must be 0 (over) or 1 (under), got %d" % s)
	return null

func _splat_unusable(level):
	if level.Terrain == null:
		return _err("this level has no Terrain")
	if not level.Terrain.has_method("CloneSplatImage"):
		return null
	var img = level.Terrain.CloneSplatImage()
	if img == null or img.get_width() <= 0 or img.get_height() <= 0:
		return _err("this level's terrain splat image is empty, so terrain " +
			"cannot be read or painted; writing to it crashes Dungeondraft. " +
			"A map resized by a bridge older than 1.0.3 saved its splat at " +
			"the wrong size, and Dungeondraft dropped it on load. The " +
			"painted terrain in that file cannot be recovered from here.")
	return null

const SPLAT_PX_PER_TILE := 4

func _blank_splat(px_w : int, px_h : int, base : Color):
	var img = Image.new()
	img.create(px_w, px_h, false, Image.FORMAT_RGBA8)
	img.fill(base)
	return img

func _rebuild_splat(level) -> Dictionary:
	var dims = Global.World.WoxelDimensions
	var px_w = int(dims.x) / WOXELS_PER_TILE * SPLAT_PX_PER_TILE
	var px_h = int(dims.y) / WOXELS_PER_TILE * SPLAT_PX_PER_TILE
	if px_w <= 0 or px_h <= 0:
		return _err("the map has no size, so no splat size can be derived")
	# Slot 0 is not a paintable channel — it is whatever slots 1-3 leave
	# unclaimed — so blank ground is [1, 0, 0, 0], the same thing get_terrain
	# reports for an untouched map.
	var img = _blank_splat(px_w, px_h, Color(1, 0, 0, 0))
	# Slots 4-7 live in a second image and start with nothing claimed at all.
	if level.Terrain.has_method("RestoreSplat2"):
		level.Terrain.RestoreSplat2(img, _blank_splat(px_w, px_h, Color(0, 0, 0, 0)))
	else:
		level.Terrain.RestoreSplat(img)
	level.Terrain.UpdateSplat()
	var after = level.Terrain.CloneSplatImage()
	if after == null or after.get_width() <= 0:
		return _err("rebuilt the splat but the engine still reports it empty")
	return _ok({ "splat_size": [after.get_width(), after.get_height()] })

func _repair_terrain(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	if level.Terrain == null: return _err("this level has no Terrain")
	var existing = level.Terrain.CloneSplatImage()
	var usable = existing != null and existing.get_width() > 0 and existing.get_height() > 0
	if usable and not bool(req.get("force", false)):
		return _ok({ "repaired": false,
			"splat_size": [existing.get_width(), existing.get_height()],
			"note": "the splat is already usable; pass force to blank it anyway" })
	var result = _rebuild_splat(level)
	if result.get("ok") == false:
		return result
	result["repaired"] = true
	result["note"] = ("terrain was blanked, not recovered: the painted data was " +
		"already gone. Repaint it.")
	return result

func _set_terrain_slot(req : Dictionary) -> Dictionary:
	var bad = _bad_slot(req)
	if bad != null: return bad
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var bad_slot_splat = _splat_unusable(level)
	if bad_slot_splat != null: return bad_slot_splat
	var tex = _asset_tex("Terrain", req.get("asset", ""))
	if tex == null: return _err("could not load terrain asset: " + str(req.get("asset")))
	var slot = int(req.get("slot", 0))
	level.Terrain.SetTexture(tex, slot)
	level.Terrain.UpdateSplat()
	return _ok({ "slot": slot })

func _fill_terrain(req : Dictionary) -> Dictionary:
	var bad_fill_terrain = _bad_slot(req)
	if bad_fill_terrain != null: return bad_fill_terrain
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var bad_fill_splat = _splat_unusable(level)
	if bad_fill_splat != null: return bad_fill_splat
	var slot = int(req.get("slot", 0))
	if req.has("asset"):
		var tex = _asset_tex("Terrain", req["asset"])
		if tex == null: return _err("could not load terrain asset: " + str(req["asset"]))
		level.Terrain.SetTexture(tex, slot)
	level.Terrain.Fill(slot)
	level.Terrain.UpdateSplat()
	return _ok({ "filled_slot": slot })

func _paint_terrain(req : Dictionary) -> Dictionary:
	var bad_paint_terrain = _bad_slot(req)
	if bad_paint_terrain != null: return bad_paint_terrain
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var slot = int(req.get("slot", 0))
	var radius = float(req.get("radius", 64.0))
	var rate = clamp(float(req.get("rate", 1.0)), 0.0, 1.0)
	if req.has("asset"):
		var tex = _asset_tex("Terrain", req["asset"])
		if tex == null: return _err("could not load terrain asset: " + str(req["asset"]))
		level.Terrain.SetTexture(tex, slot)
	var world = _xy(req, Global.World.WoxelDimensions * 0.5)
	# Convert the brush center and radius into texture space (radius scales by
	# the woxel->texture ratio along x).
	var center = level.Terrain.WorldToTexture(world)
	var tscale = float(level.Terrain.width) / max(Global.World.WoxelDimensions.x, 1.0)
	var trad = max(radius * tscale, 0.5)

	var sp = _open_splat(level, slot)
	if sp == null: return _err("could not read splat image for slot " + str(slot))
	var img = sp.img
	var ch = sp.ch
	var iw = img.get_width()
	var ih = img.get_height()
	var x0 = int(floor(center.x - trad))
	var y0 = int(floor(center.y - trad))
	var x1 = int(ceil(center.x + trad))
	var y1 = int(ceil(center.y + trad))
	var painted := 0
	img.lock()
	for iy in range(max(y0, 0), min(y1 + 1, ih)):
		for ix in range(max(x0, 0), min(x1 + 1, iw)):
			var d = Vector2(ix + 0.5, iy + 0.5).distance_to(center)
			if d > trad:
				continue
			# Smooth falloff: full strength in the inner half, easing to 0 at the rim.
			var falloff = clamp(1.0 - (d / trad), 0.0, 1.0)
			falloff = falloff * falloff * (3.0 - 2.0 * falloff)
			var w = rate * falloff
			if w <= 0.0:
				continue
			img.set_pixel(ix, iy, _splat_set_channel(img.get_pixel(ix, iy), ch, w))
			painted += 1
	img.unlock()
	_close_splat(level, sp.which, img)
	return _ok({ "painted_slot": slot, "pixels": painted })

func _paint_path(req : Dictionary) -> Dictionary:
	var bad_paint_path = _bad_slot(req)
	if bad_paint_path != null: return bad_paint_path
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var slot = int(req.get("slot", 0))
	var radius = float(req.get("radius", 96.0))
	var rate = clamp(float(req.get("rate", 1.0)), 0.0, 1.0)
	if not req.has("points"):
		return _err("provide 'points':[[x,y]...] (>= 2 points)")
	var pts = req["points"]
	if typeof(pts) != TYPE_ARRAY or pts.size() < 2:
		return _err("'points' needs >= 2 [x,y] pairs for a path")
	if req.has("asset"):
		var tex = _asset_tex("Terrain", req["asset"])
		if tex == null: return _err("could not load terrain asset: " + str(req["asset"]))
		level.Terrain.SetTexture(tex, slot)

	# Map the polyline into texture space; radius scales by the woxel->texture
	# ratio (same conversion paint_terrain uses for a single dab).
	var tscale = float(level.Terrain.width) / max(Global.World.WoxelDimensions.x, 1.0)
	var trad = max(radius * tscale, 0.5)
	var tpts := []
	var mn = Vector2(INF, INF)
	var mx = Vector2(-INF, -INF)
	for p in pts:
		var tp = level.Terrain.WorldToTexture(Vector2(float(p[0]), float(p[1])))
		tpts.append(tp)
		mn.x = min(mn.x, tp.x); mn.y = min(mn.y, tp.y)
		mx.x = max(mx.x, tp.x); mx.y = max(mx.y, tp.y)

	var sp = _open_splat(level, slot)
	if sp == null: return _err("could not read splat image for slot " + str(slot))
	var img = sp.img
	var ch = sp.ch
	var iw = img.get_width()
	var ih = img.get_height()
	# Bounding box of the whole stroke, padded by the brush radius.
	var x0 = max(int(floor(mn.x - trad)), 0)
	var y0 = max(int(floor(mn.y - trad)), 0)
	var x1 = min(int(ceil(mx.x + trad)), iw - 1)
	var y1 = min(int(ceil(mx.y + trad)), ih - 1)
	var painted := 0
	img.lock()
	for iy in range(y0, y1 + 1):
		for ix in range(x0, x1 + 1):
			var pix = Vector2(ix + 0.5, iy + 0.5)
			# Distance to the closest segment of the polyline.
			var d = INF
			for i in range(tpts.size() - 1):
				var sd = _dist_point_segment(pix, tpts[i], tpts[i + 1])
				if sd < d:
					d = sd
				if d <= 0.0:
					break
			if d > trad:
				continue
			# Same smoothstep falloff as paint_terrain, applied once per pixel.
			var falloff = clamp(1.0 - (d / trad), 0.0, 1.0)
			falloff = falloff * falloff * (3.0 - 2.0 * falloff)
			var w = rate * falloff
			if w <= 0.0:
				continue
			img.set_pixel(ix, iy, _splat_set_channel(img.get_pixel(ix, iy), ch, w))
			painted += 1
	img.unlock()
	_close_splat(level, sp.which, img)
	return _ok({ "painted_slot": slot, "segments": tpts.size() - 1, "pixels": painted })

# Shortest distance from point p to segment a-b (all in texture space).
func _dist_point_segment(p : Vector2, a : Vector2, b : Vector2) -> float:
	var ab = b - a
	var len2 = ab.x * ab.x + ab.y * ab.y
	if len2 <= 0.0000001:
		return p.distance_to(a)
	var t = clamp((p - a).dot(ab) / len2, 0.0, 1.0)
	return p.distance_to(a + ab * t)

func _fill_region(req : Dictionary) -> Dictionary:
	var bad_fill_region = _bad_slot(req)
	if bad_fill_region != null: return bad_fill_region
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var slot = int(req.get("slot", 0))
	var rate = float(req.get("rate", 1.0))
	if req.has("asset"):
		var tex = _asset_tex("Terrain", req["asset"])
		if tex == null: return _err("could not load terrain asset: " + str(req["asset"]))
		level.Terrain.SetTexture(tex, slot)

	# Gather the shape's world-space polygon (rect -> 4 corners).
	var poly := []
	if req.has("rect"):
		var r = req["rect"]
		if typeof(r) != TYPE_ARRAY or r.size() < 4:
			return _err("'rect' must be [x, y, w, h]")
		var x = float(r[0]); var y = float(r[1]); var w = float(r[2]); var h = float(r[3])
		poly = [Vector2(x, y), Vector2(x + w, y), Vector2(x + w, y + h), Vector2(x, y + h)]
	elif req.has("points"):
		for p in req["points"]:
			poly.append(Vector2(float(p[0]), float(p[1])))
		if poly.size() < 3:
			return _err("'points' needs >= 3 [x,y] pairs for a polygon")
	else:
		return _err("provide 'rect':[x,y,w,h] or 'points':[[x,y]...]")

	# Map the polygon into texture space and find its pixel bounding box.
	var tpoly := []
	var mn = Vector2(INF, INF)
	var mx = Vector2(-INF, -INF)
	for wp in poly:
		var tp = level.Terrain.WorldToTexture(wp)
		tpoly.append(tp)
		mn.x = min(mn.x, tp.x); mn.y = min(mn.y, tp.y)
		mx.x = max(mx.x, tp.x); mx.y = max(mx.y, tp.y)
	var origin = Vector2(floor(mn.x), floor(mn.y))
	var bw = int(ceil(mx.x - origin.x))
	var bh = int(ceil(mx.y - origin.y))
	if bw < 1 or bh < 1:
		return _err("region is too small in texture space")

	var local := []
	for tp in tpoly:
		local.append(tp - origin)
	rate = clamp(rate, 0.0, 1.0)
	var sp = _open_splat(level, slot)
	if sp == null: return _err("could not read splat image for slot " + str(slot))
	var img = sp.img
	var iw = img.get_width()
	var ih = img.get_height()
	var painted := 0

	var ox = int(origin.x)
	var oy = int(origin.y)
	var y_from = int(max(0, oy))
	var y_to = int(min(ih, oy + bh))
	var x_from = int(max(0, ox))
	var x_to = int(min(iw, ox + bw))
	img.lock()
	for iy in range(y_from, y_to):
		for ix in range(x_from, x_to):
			if not _point_in_poly(Vector2(ix - ox + 0.5, iy - oy + 0.5), local):
				continue
			img.set_pixel(ix, iy, _splat_set_channel(img.get_pixel(ix, iy), sp.ch, rate))
			painted += 1
	img.unlock()
	_close_splat(level, sp.which, img)

	return _ok({
		"filled_slot": slot, "shape": ("rect" if req.has("rect") else "polygon"),
		"texture_bbox": [_vec(origin), [origin.x + bw, origin.y + bh]],
		"pixels": painted,
	})

func _open_splat(level, slot : int):
	var which = 0 if slot < 4 else 1

	if which == 1 and level.Terrain.has_method("ExpandSlots"):
		level.Terrain.ExpandSlots(true)
	var img = level.Terrain.CloneSplatImage() if which == 0 else level.Terrain.CloneSplatImage2()
	if img == null:
		return null

	if img.get_width() <= 0 or img.get_height() <= 0:
		return null
	return { "img": img, "ch": slot % 4, "which": which }

func _close_splat(level, which : int, img) -> void:
	if which == 0:
		level.Terrain.RestoreSplat(img)
	else:

		level.Terrain.RestoreSplat2(level.Terrain.CloneSplatImage(), img)
	level.Terrain.UpdateSplat()

# Push channel `ch` (0=R,1=G,2=B,3=A) of an RGBA splat weight toward 1 by `rate`,
# scaling the remaining channels down so the four weights still sum to ~1.
func _splat_set_channel(c : Color, ch : int, rate : float) -> Color:
	var w = [c.r, c.g, c.b, c.a]
	var target = w[ch] + (1.0 - w[ch]) * rate
	var rest = 1.0 - target
	var others = (w[0] + w[1] + w[2] + w[3]) - w[ch]
	for i in range(4):
		if i == ch:
			w[i] = target
		elif others > 0.0001:
			w[i] = w[i] / others * rest
		else:
			w[i] = 0.0
	return Color(w[0], w[1], w[2], w[3])

# Even-odd point-in-polygon test (ray cast). `poly` is an array of Vector2.
func _point_in_poly(pt : Vector2, poly : Array) -> bool:
	var inside = false
	var n = poly.size()
	var j = n - 1
	for i in range(n):
		var a = poly[i]
		var b = poly[j]
		if ((a.y > pt.y) != (b.y > pt.y)) and \
				(pt.x < (b.x - a.x) * (pt.y - a.y) / (b.y - a.y) + a.x):
			inside = not inside
		j = i
	return inside

# ---------------------------------------------------------------------------
# Modify / delete
# ---------------------------------------------------------------------------

func _move_element(req : Dictionary) -> Dictionary:
	var node = _resolve(req)
	if node == null: return _err("no element with id " + str(req.get("id")))
	if _is_text(node):
		node.rect_position = _xy(req, node.rect_position)
		return _ok({ "id": req.get("id"), "position": _vec(node.rect_position) })
	if not (node is Node2D): return _err("element is not movable")
	node.position = _xy(req, node.position)
	return _ok({ "id": req.get("id"), "position": _vec(node.position) })

# Resolve once, deduplicate, and do not detach a mounted portal from its wall.
func _movable_group(ids) -> Dictionary:
	var nodes = []
	var moved_ids = []
	var missing = []
	var unsupported = []
	var attached = []
	var seen = {}
	for raw_id in ids:
		if not (typeof(raw_id) in [TYPE_INT, TYPE_REAL]) or float(raw_id) != floor(float(raw_id)):
			missing.append(raw_id)
			continue
		var id = int(raw_id)
		if seen.has(id): continue
		seen[id] = true
		var node = Global.World.GetNodeByID(id)
		if node == null:
			missing.append(id)
			continue
		var kind = "text" if _is_text(node) else KIND_NAMES.get(Global.Editor.Tools["SelectTool"].GetSelectableType(node), "unknown")
		# Native selectable type codes differ between free and mounted portals.
		# Ownership is authoritative; a free portal also carries a dummy WallID.
		if node.get_parent() == Global.World.GetCurrentLevel().Portals:
			kind = "portal"
		elif node.get("WallID") != null and node.get("Direction") != null:
			kind = "wall_portal"
		if kind == "wall_portal":
			attached.append(node)
		elif kind == "wall" and int(node.Type) == 2:
			unsupported.append({ "id": id, "reason": "cave walls belong to the cave bitmap" })
		elif kind in ["wall", "path", "roof", "pattern", "object", "light", "portal", "text"]:
			nodes.append(node)
			moved_ids.append(id)
		else:
			unsupported.append({ "id": id, "reason": "unsupported element kind" })
	for portal in attached:
		if portal.get_parent() in nodes:
			moved_ids.append(_id(portal))
		else:
			unsupported.append({ "id": _id(portal), "reason": "include the mounted portal's wall in the group" })
	for node in nodes:
		if node.has_method("set_Points") and node.has_method("RemakeLines"):
			for portal in node.Portals:
				if not (_id(portal) in moved_ids): moved_ids.append(_id(portal))
	return { "nodes": nodes, "moved": moved_ids, "missing": missing, "unsupported": unsupported }

# Geometry bounds, not wall/roof origins (which are commonly [0, 0]).
func _group_centre(nodes) -> Vector2:
	var found = false
	var lo = Vector2()
	var hi = Vector2()
	for node in nodes:
		var description = _describe(node)
		var points = description.get("points", [])
		if points.empty(): points = [description.get("position", [0, 0])]
		for point in points:
			var pos = Vector2(point[0], point[1])
			if not found:
				lo = pos
				hi = pos
				found = true
			else:
				lo = Vector2(min(lo.x, pos.x), min(lo.y, pos.y))
				hi = Vector2(max(hi.x, pos.x), max(hi.y, pos.y))
	return (lo + hi) * 0.5

func _transform_group(group, offset : Vector2, angle : float, centre : Vector2) -> Array:
	for node in group["nodes"]:
		if node.has_method("set_Points") and node.has_method("RemakeLines"):

			var pts = PoolVector2Array()
			for point in node.Points:
				pts.append(centre + offset + (node.to_global(point) - centre).rotated(angle))
			var portals = []
			for portal in node.Portals:
				portals.append({ "node": portal,
					"position": centre + offset + (node.to_global(portal.position) - centre).rotated(angle),
					"direction": node.global_transform.basis_xform(portal.Direction).rotated(angle).normalized(),
					"rotation": portal.global_rotation + angle })
			node.position = Vector2()
			node.rotation = 0
			node.scale = Vector2(1, 1)
			node.Points = pts
			for entry in portals:
				var portal = entry["node"]
				portal.position = entry["position"]
				portal.Direction = entry["direction"]
				portal.rotation = entry["rotation"]
			node.RemakeLines()
		elif _is_text(node):
			# Keep text labels upright while moving their anchors.
			node.rect_position = centre + offset + (node.rect_position - centre).rotated(angle)
		else:
			node.position = centre + offset + (node.position - centre).rotated(angle)
			node.rotation += angle
			if node.get("Direction") != null: node.Direction = node.Direction.rotated(angle)
	return group["moved"]

# Move and optionally rotate a mixed group in one undo step.
func _move_elements(req : Dictionary) -> Dictionary:
	var ids = req.get("ids", [])
	if typeof(ids) != TYPE_ARRAY or ids.empty(): return _err("'ids' must be a non-empty array of element ids")
	if ids.size() > 1000: return _err("'ids' is capped at 1000 per call")
	for key in ["dx", "dy", "rotation", "pivot_x", "pivot_y"]:
		if not req.has(key): continue
		var value = req[key]
		if not (typeof(value) in [TYPE_INT, TYPE_REAL]): return _err(key + " must be a finite number")
		if is_nan(float(value)) or is_inf(float(value)): return _err(key + " must be finite")
	if req.has("pivot_x") != req.has("pivot_y"): return _err("provide both pivot_x and pivot_y")
	var offset = Vector2(float(req.get("dx", 0.0)), float(req.get("dy", 0.0)))
	var group = _movable_group(ids)
	var centre = _group_centre(group["nodes"])
	if req.has("pivot_x"): centre = Vector2(req["pivot_x"], req["pivot_y"])
	var angle = deg2rad(float(req.get("rotation", 0.0)))
	var moved = _transform_group(group, offset, angle, centre)
	return _ok({ "moved": moved, "missing": group["missing"], "unsupported": group["unsupported"],
		"offset": _vec(offset), "rotation": rad2deg(angle), "pivot": _vec(centre) })

func _modify_object(req : Dictionary) -> Dictionary:
	var tint_error = _refuse_modulate(req)
	if tint_error != null: return tint_error
	var bad_modify_color = _bad_color(req, ["modulate"])
	if bad_modify_color != null: return bad_modify_color
	var bad_modify_layer = _bad_layer(req)
	if bad_modify_layer != null: return bad_modify_layer
	var node = _resolve(req)
	if node == null: return _err("no element with id " + str(req.get("id")))

	if req.has("color") and str(req.get("color", "")) != "":
		return _err("colour is baked at placement and cannot be changed after: " +
			"pass color to place_object when creating the object")

	if (req.has("scale") or req.has("rotation")) and _patch_is_sheared(node):
		if not _patch_verified():
			return _err("this object has an Unofficial Patch Free Transform (skew or " +
				"distort), and this version of the patch is not one the bridge has " +
				"checked, so it will not rotate or scale it: that would lose the " +
				"skew. Moving it is fine. No changes were made.")
		_patch_rotate_scale(node, req.get("rotation"), req.get("scale"))
	else:
		if req.has("scale"):
			var s = float(req["scale"]); node.scale = Vector2(s, s)
		if req.has("rotation"):
			node.rotation = deg2rad(float(req["rotation"]))
	if req.has("shadow"):
		node.set("HasShadow", bool(req["shadow"]))

	if req.has("block_light") and node.has_method("SetBlockLight"):

		_apply_block_light(node, bool(req["block_light"]))
	var modulated = false
	if req.has("modulate") and str(req.get("modulate", "")) != "":
		if not _modulate_requested(req):
			return _err("'modulate' must be a hex colour like '#3366ff', got: " + str(req["modulate"]))
		modulated = _set_node_modulate(node, _color(req["modulate"], Color(1, 1, 1)))

	if req.has("layer") and node is Node2D:
		node.z_index = int(req["layer"])
	var out = _describe(node)
	if modulated:
		out["modulate_applied"] = true
	return _ok(out)

func _duplicate_object(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var src = _resolve(req)
	if src == null: return _err("no element with id " + str(req.get("id")))
	if src.get("Texture") == null: return _err("element has no Texture to duplicate")
	var source_tint = _read_node_modulate(src)
	if source_tint != null and source_tint != Color(1, 1, 1, 1):
		return _err("cannot duplicate an object with modulate: the tint does not survive saving and reopening. No changes were made.")
	var prop = _new_object(level, 0, src.z_index)
	prop.SetTexture(src.Texture)
	prop.position = src.position + Vector2(float(req.get("dx", 64.0)), float(req.get("dy", 0.0)))
	prop.scale = src.scale
	prop.rotation = src.rotation
	if _patch_is_sheared(src):
		prop.transform = Transform2D(src.transform.x, src.transform.y, prop.position)

	var src_mod = _read_node_modulate(src)
	if src_mod != null:
		_set_node_modulate(prop, src_mod)
	var src_shadow = src.get("HasShadow")
	if src_shadow != null:
		prop.set("HasShadow", src_shadow)
	var copied = ["scale", "rotation", "modulate", "shadow"]
	copied.append_array(_patch_copy_node_data(src, prop))
	return _ok({ "id": _id(prop), "position": _vec(prop.position),
		"copied": copied,
		"note": "colour is baked at placement and cannot be copied" })

func _delete_elements(req : Dictionary) -> Dictionary:
	var ids = req.get("ids", [])
	if typeof(ids) != TYPE_ARRAY or ids.empty():
		return _err("'ids' must be a non-empty array of element ids")
	if ids.size() > MAX_BATCH_ITEMS:
		return _err("'ids' is capped at %d per call" % MAX_BATCH_ITEMS)
	var seen := {}
	var order := []
	var unknown := []
	for raw in ids:
		if not (typeof(raw) in [TYPE_INT, TYPE_REAL]):
			return _err("every id must be an integer, got: " + str(raw))
		var id = int(raw)
		if seen.has(id):
			continue
		var node = Global.World.GetNodeByID(id)
		if node == null:
			unknown.append(id)
			continue
		seen[id] = true
		order.append({ "id": id, "node": node, "parent": node.get_parent() })
	if not unknown.empty():
		return _err(("no element with id %s, so nothing was deleted. Read the ids " +
			"back with list_elements: an element deleted earlier is already gone, " +
			"and ids are not reused.") % str(unknown))
	for entry in order:
		var blocked = _prop_detach_error(entry["node"])
		if blocked != "": return _err(blocked)
	for entry in order:
		_detach_node(entry["node"], int(entry["id"]))
	return _ok({ "deleted": order.size(), "ids": seen.keys(), "undoable": true,
		"note": "one undo() restores all of them" })

func _delete_element(req : Dictionary) -> Dictionary:
	var ident = req.get("id")
	if ident == null: return _err("missing 'id'")
	var id = int(ident)
	var node = Global.World.GetNodeByID(id)
	if node == null:
		return _err("no element with id %d" % id)
	var blocked = _prop_detach_error(node)
	if blocked != "": return _err(blocked)
	var parent = node.get_parent()
	_detach_node(node, id)
	return _ok({ "deleted": true, "id": id, "undoable": true })

# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------

func _add_level(req : Dictionary) -> Dictionary:
	var lv = Global.World.CreateLevel(str(req.get("label", "Level")))
	if lv == null:
		return _err("CreateLevel returned nothing")
	_rearm_active_tool()
	var current = Global.World.GetCurrentLevel()
	return _ok({ "id": lv.ID, "label": lv.Label,
		"level_count": Global.World.levels.size(),
		"current_level_id": current.ID if current != null else -1,
		"note": "the new level is NOT selected — call set_level(id) to draw on it" })

func _set_level(req : Dictionary) -> Dictionary:
	if not req.has("id"):
		return _err("'id' is required — a level id from list_levels (not its index)")
	var id = int(req["id"])
	var known := []
	for lv in Global.World.levels:
		known.append(lv.ID)
	if not (id in known):
		return _err("no level with id %d; known ids: %s" % [id, str(known)])
	var index = -1
	for i in range(Global.World.levels.size()):
		if Global.World.levels[i].ID == id:
			index = i
			break
	if index == -1:
		return _err("no level with id %d" % id)
	Global.World.SetLevel(index, false)
	_rearm_active_tool()

	var now = Global.World.GetCurrentLevel()
	if now == null:
		return _err("no current level after SetLevel(%d)" % index)
	if now.ID != id:
		return _err("SetLevel(%d) selected level %d (%s) instead of %d"
			% [index, now.ID, str(now.Label), id])
	return _ok({ "current_level_id": now.ID, "label": now.Label })

const MAP_SIZE_WINDOW := "ChangeMapSize"
const MAP_TILES_MIN := 8
const MAP_TILES_MAX := 128
const MAP_SIZE_HANDLERS := ["_on_ChangeMapSizeWindow_about_to_show",
	"_on_TopSpinBox_value_changed", "_on_BottomSpinBox_value_changed",
	"_on_LeftSpinBox_value_changed", "_on_RightSpinBox_value_changed",
	"_on_OkayButton_pressed"]

func _map_size_window():
	var windows = Global.Editor.get("Windows") if Global.Editor != null else null

	if typeof(windows) != TYPE_DICTIONARY or not windows.has(MAP_SIZE_WINDOW):
		return null
	var win = windows[MAP_SIZE_WINDOW]
	if win == null or not is_instance_valid(win):
		return null
	for m in MAP_SIZE_HANDLERS:
		if not win.has_method(m):
			return null
	for side in ["Top", "Bottom", "Left", "Right"]:
		if win.find_node(side + "SpinBox", true, false) == null:
			return null
	return win

func _map_size_side(win, side : String, value : int, own_handler := true) -> void:
	var spin = win.find_node(side + "SpinBox", true, false)

	spin.set_value(float(value))
	if own_handler:
		win.call("_on_%sSpinBox_value_changed" % side, float(value))

func _signal_reaches(source, signal_name : String, target, method : String) -> bool:
	for connection in source.get_signal_connection_list(signal_name):
		if connection.get("target") == target and str(connection.get("method")) == method:
			return true
	return false

func _set_map_size(req : Dictionary) -> Dictionary:
	if not req.has("width") or not req.has("height"):
		return _err("'width' and 'height' are required, in tiles")
	var w = int(req["width"])
	var h = int(req["height"])

	var patch = _patch_loaded()
	var tiles_min = PATCH_MAP_TILES_MIN if patch else MAP_TILES_MIN
	var tiles_max = PATCH_MAP_TILES_MAX if patch else MAP_TILES_MAX
	if w < tiles_min or h < tiles_min or w > tiles_max or h > tiles_max:
		return _err("width and height must each be %d to %d tiles; %s allows no other size"
			% [tiles_min, tiles_max, "the Unofficial Patch's resize" if patch else "Dungeondraft's resize"])
	var win = _map_size_window()
	if win == null:
		# Never fall back to the property setters: that is the path that wrote
		# maps Dungeondraft could not reopen.
		return _err("this Dungeondraft build does not expose the Change Map " +
			"Size window, so the map cannot be resized safely. Create the map " +
			"at the size you need from Dungeondraft's New Map dialog instead")
	var old_w = int(Global.World.Width)
	var old_h = int(Global.World.Height)
	var right : int = w - old_w
	var bottom : int = h - old_h
	var steps := 0

	var limit := 64
	var probe = win.find_node("RightSpinBox", true, false)
	if probe != null and probe.get("max_value") != null:
		limit = max(1, int(min(abs(probe.min_value), probe.max_value)))

	var ok_button = win.find_node("OkayButton", true, false)
	var rewired = ok_button != null and not _signal_reaches(ok_button, "pressed", win, "_on_OkayButton_pressed")
	if rewired:
		limit = 1000000
	while (right != 0 or bottom != 0) and steps < 32:
		var dr = int(clamp(right, -limit, limit))
		var db = int(clamp(bottom, -limit, limit))
		if rewired:
			win.emit_signal("about_to_show")
		else:
			win.call("_on_ChangeMapSizeWindow_about_to_show")
		_map_size_side(win, "Top", 0, not rewired)
		_map_size_side(win, "Left", 0, not rewired)
		_map_size_side(win, "Right", dr, not rewired)
		_map_size_side(win, "Bottom", db, not rewired)
		if rewired:
			ok_button.emit_signal("pressed")
		else:
			win.call("_on_OkayButton_pressed")
		right -= dr
		bottom -= db
		steps += 1
	# Read back rather than trusting the dialog: the size, and every level's
	# splat, which is what the saver writes and what broke before.
	var now_w = int(Global.World.Width)
	var now_h = int(Global.World.Height)
	if now_w != w or now_h != h:
		return _err("resize did not take: asked for %dx%d, the map is %dx%d"
			% [w, h, now_w, now_h])
	var stale := []
	var checked := 0
	for lvl in Global.World.levels:
		if lvl == null or lvl.Terrain == null or not lvl.Terrain.has_method("CloneSplatImage"):
			continue
		var img = lvl.Terrain.CloneSplatImage()
		checked += 1
		if img == null or img.get_width() != w * SPLAT_PX_PER_TILE \
				or img.get_height() != h * SPLAT_PX_PER_TILE:
			stale.append(lvl.ID)
	if stale.size() > 0:
		return _err("the map is %dx%d but the terrain of level(s) %s was not " % [w, h, str(stale)] +
			"resized with it; do not save this map. Reopen it and create the " +
			"map at size from Dungeondraft's New Map dialog")
	return _ok({ "width_tiles": w, "height_tiles": h,
		"previous_tiles": [old_w, old_h],
		"map_size_woxels": [Global.World.WoxelDimensions.x,
			Global.World.WoxelDimensions.y],
		"levels_resized": checked,
		"steps": steps,
		"note": "the top-left origin is kept: the map grows or shrinks on the " +
			"right and bottom. Nothing placed is moved, and shrinking does not " +
			"delete what now lies outside the map" })

# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

# Everything the bridge writes lands in one directory the mod owns. Callers pass
# a bare filename, never a path: anything containing a separator is refused, so
# there is no traversal to validate and no caller-supplied directory to honour.
const OUTPUT_SUBDIR := "mcp_output"

func _output_path(raw) -> String:
	var name = str(raw)
	# Reject rather than normalize. A caller that sent a path has a bug, and
	# silently rewriting it to a different location hides that from them — they
	# would look for the file where they asked for it and not find it.
	if name.find("/") != -1 or name.find("\\") != -1:
		return ""
	if name == "" or name.begins_with("."):
		return ""

	if name.find(":") != -1:
		return ""
	# Filesystems cap a single component around 255 bytes, and a name at that
	# edge fails at save time with an error that says nothing useful. 128 is
	# well clear of it and far longer than any real output name.
	if name.length() > 128:
		return ""

	for i in range(name.length()):
		var code = name.ord_at(i)
		if code < 0x20 or code == 0x7F:
			return ""

	var allowed = [".png", ".jpg", ".jpeg", ".webp", ".json", ".vtt", ".dd2vtt"]
	var has_ext = false
	for e in allowed:
		if name.to_lower().ends_with(e):
			has_ext = true
			break
	if not has_ext:
		name += ".png"
	var base = OS.get_environment("BATTLEMAP_MCP_CAPTURE_DIR")
	if base == "": base = _state_directory().plus_file(OUTPUT_SUBDIR)
	if not base.is_abs_path(): return ""
	var dir = Directory.new()
	if not dir.dir_exists(base):
		if dir.make_dir_recursive(base) != OK:
			return ""
	return base + "/" + name

# Grab the current window (what's on screen) to a PNG. Synchronous: the texture
# holds the last drawn frame, so no yield is needed inside update().
func _screenshot(req : Dictionary) -> Dictionary:
	var path = _output_path(req.get("name", "screenshot.png"))
	if path == "": return _err("invalid 'name': pass a bare filename, not a path")
	var img = Global.World.get_viewport().get_texture().get_data()
	if img == null: return _err("viewport capture returned null")
	img.flip_y()
	var err = img.save_png(path)
	if err != OK: return _err("save_png failed (err %d): %s" % [err, path])
	return _ok({ "path": path, "width": img.get_width(), "height": img.get_height() })

const EXPORT_MAX_PIXELS := 16384
# Longest seen before the first chunk: well under a second. Generous on purpose.
const EXPORT_START_GRACE_MS := 20000
# After the camera returns, the file lands in the same frame. Seconds of margin.
const EXPORT_RETURN_GRACE_MS := 5000
const EXPORT_OVERDUE_MS := 600000
const OPERATION_HISTORY := 16

var _export_job = null
const EXPORT_DEFAULT_QUALITY := 90
var _operations := []
var _operation_serial := 0

func _export_running() -> bool:
	_tick_export_job()
	return _export_job != null

func _export_pixels(ppi : int) -> Array:
	var dims = Global.World.WoxelDimensions
	return [int(ceil(dims.x / 256.0 * ppi)), int(ceil(dims.y / 256.0 * ppi))]

func _camera_key() -> Array:
	var cam = _camera()
	if cam == null: return []
	return [cam.global_position.x, cam.global_position.y, cam.zoom.x, cam.zoom.y]

func _operation_view(job : Dictionary) -> Dictionary:
	var end_ms = job["finished_ms"] if job["finished_ms"] >= 0 else OS.get_ticks_msec()
	var view := { "operation_id": job["operation_id"], "kind": job["kind"],
		"state": job["state"], "path": job["path"], "format": job["format"],
		"ppi": job["ppi"], "pixels": job["pixels"],
		"chunks_rendered": job["chunks_rendered"],
		"elapsed_ms": end_ms - job["started_ms"] }
	if job["error"] != "": view["error"] = job["error"]
	if job["overdue"]:
		view["overdue"] = true
		view["recovery"] = ("rendering for over %d s with the camera away from where " +
			"it started, so the exporter cannot be confirmed stopped and edits stay " +
			"refused. The lock releases by itself if the export finishes. If it " +
			"does not, restart Dungeondraft, saving from its File menu first if the " +
			"map has unsaved work.") % [EXPORT_OVERDUE_MS / 1000]
	return view

func _settle_export(state : String, error : String) -> void:
	var job = _export_job
	# Give back the quality the user's Export window chose. The unset 0 is not
	# worth restoring: it is what produced the broken JPGs.
	var before = int(job.get("quality_before", -1))
	if before >= 1 and before <= 100 and Global.Exporter.has_method("set_Quality"):
		Global.Exporter.set_Quality(before)
	job["state"] = state
	job["error"] = error
	job["finished_ms"] = OS.get_ticks_msec()
	_operations.append(job)
	while _operations.size() > OPERATION_HISTORY:
		_operations.pop_front()
	_export_job = null
	print("[mcp-bridge] export %s %s after %d ms, %d chunks%s" % [job["operation_id"],
		state, job["finished_ms"] - job["started_ms"], job["chunks_rendered"],
		(": " + error) if error != "" else ""])

func _tick_export_job() -> void:
	if _export_job == null:
		return
	var job = _export_job
	var now = OS.get_ticks_msec()
	var key = _camera_key()
	var moved = key != job["camera_before"]
	if moved:
		var k = str(key)
		if not job["seen"].has(k):
			job["seen"][k] = true
			job["chunks_rendered"] = job["seen"].size()
		job["last_move_ms"] = now
	if File.new().file_exists(job["path"]):
		_settle_export("completed", "")
	elif job["chunks_rendered"] == 0 and now - job["started_ms"] > EXPORT_START_GRACE_MS:
		_settle_export("failed", ("the exporter never started: the camera did not " +
			"move in %d s and no file was written. Dungeondraft abandons an export " +
			"silently when it cannot render it.") % [EXPORT_START_GRACE_MS / 1000])
	elif job["chunks_rendered"] > 0 and not moved \
			and now - job["last_move_ms"] > EXPORT_RETURN_GRACE_MS:
		_settle_export("failed", ("the exporter rendered %d chunks and restored the " +
			"camera without writing %s") % [job["chunks_rendered"], job["path"]])
	elif not job["overdue"] and now - job["started_ms"] > EXPORT_OVERDUE_MS:
		# Flag it, and keep the lock: see the note above EXPORT_MAX_PIXELS.
		job["overdue"] = true
		print("[mcp-bridge] export %s overdue after %d ms, %d chunks; still locked"
			% [job["operation_id"], now - job["started_ms"], job["chunks_rendered"]])

func _export_map(req : Dictionary) -> Dictionary:
	_operation_serial += 1
	var name = str(req.get("name", ""))
	if name == "":
		name = "export-%d-%d.png" % [OS.get_unix_time(), _operation_serial]
	var path = _output_path(name)
	if path == "": return _err("invalid 'name': pass a bare filename, not a path")
	# Completion is the file appearing, so a file that already exists would
	# settle the operation before a single chunk rendered.
	if File.new().file_exists(path):
		return _err("%s already exists; export to a new filename" % name)
	var ppi = int(req.get("ppi", 40))
	if ppi < 1:
		return _err("ppi must be at least 1")

	var fmt = str(req.get("format", "png")).to_lower()
	var mode = 0
	if fmt == "png": mode = 0
	elif fmt == "jpg" or fmt == "jpeg": mode = 1
	elif fmt == "webp": mode = 2
	else: return _err("unknown format '" + fmt + "'; use png, jpg or webp. " +
		"Universal VTT only exports from Dungeondraft's own export window.")
	var pixels = _export_pixels(ppi)
	if pixels[0] > EXPORT_MAX_PIXELS or pixels[1] > EXPORT_MAX_PIXELS:
		var tiles = max(Global.World.WoxelDimensions.x, Global.World.WoxelDimensions.y) / 256.0
		return _err(("%d ppi renders %dx%d px, and Dungeondraft silently abandons " +
			"exports over %d px on a side. The most this map allows is %d ppi.")
			% [ppi, pixels[0], pixels[1], EXPORT_MAX_PIXELS,
			int(floor(EXPORT_MAX_PIXELS / tiles))])

	var quality = int(req.get("quality", EXPORT_DEFAULT_QUALITY))
	if quality < 1 or quality > 100:
		return _err("quality must be 1 to 100")
	if _camera() == null:
		return _err("no editor camera; the exporter renders through it")
	var quality_before = -1
	if Global.Exporter.has_method("get_Quality") and Global.Exporter.has_method("set_Quality"):
		quality_before = int(Global.Exporter.get_Quality())
		Global.Exporter.set_Quality(quality)
	_export_job = { "operation_id": "export-%d-%d" % [OS.get_unix_time(), _operation_serial],
		"kind": "export", "state": "rendering", "path": path, "format": fmt,
		"ppi": ppi, "pixels": pixels, "chunks_rendered": 0, "seen": {},
		"camera_before": _camera_key(), "started_ms": OS.get_ticks_msec(),
		"last_move_ms": -1, "finished_ms": -1, "error": "", "overdue": false,
		"quality": quality, "quality_before": quality_before }
	Global.Exporter.Start(mode, ppi, path)
	return _ok(_operation_view(_export_job))

# Status of an export: the one rendering, or one of the last OPERATION_HISTORY
# settled. Without an id, lists them all.
func _get_operation(req : Dictionary) -> Dictionary:
	_tick_export_job()
	var wanted = str(req.get("operation_id", ""))
	if wanted == "":
		var recent := []
		for job in _operations:
			recent.append(_operation_view(job))
		return _ok({ "current": _operation_view(_export_job) if _export_job != null else null,
			"recent": recent })
	if _export_job != null and _export_job["operation_id"] == wanted:
		return _ok(_operation_view(_export_job))
	for job in _operations:
		if job["operation_id"] == wanted:
			return _ok(_operation_view(job))
	return _err(("unknown operation %s: the bridge keeps the last %d, and forgets " +
		"all of them when a map is opened or Dungeondraft restarts")
		% [wanted, OPERATION_HISTORY])

func _camera():
	return Global.get("Camera")

func _viewport_size() -> Vector2:
	return Global.World.get_viewport().get_visible_rect().size

func _apply_zoom(cam, z : float) -> void:
	z = max(0.01, z)
	_patch_release_zoom()
	cam.zoom = Vector2(z, z)
	# Keep DD's bottom-bar zoom dropdown in sync with the raw zoom value.
	if Global.Editor.has_method("SetZoomOptionByRaw"):
		Global.Editor.SetZoomOptionByRaw(z)

func _camera_state(cam) -> Dictionary:
	return {
		"position": _vec(cam.global_position),
		"zoom": cam.zoom.x,
		"viewport_size": _vec(_viewport_size()),
	}

func _get_camera() -> Dictionary:
	var cam = _camera()
	if cam == null: return _err("camera not available")
	return _ok(_camera_state(cam))

func _set_camera(req : Dictionary) -> Dictionary:
	var cam = _camera()
	if cam == null: return _err("camera not available")
	if req.has("x") or req.has("y"):
		cam.global_position = _xy(req, cam.global_position)
	if req.has("zoom"):
		_apply_zoom(cam, float(req["zoom"]))
	return _ok(_camera_state(cam))

# Center the camera on a single element (any kind, incl. text). Optional zoom.
func _focus_element(req : Dictionary) -> Dictionary:
	var cam = _camera()
	if cam == null: return _err("camera not available")
	var node = _resolve(req)
	if node == null: return _err("no element with id " + str(req.get("id")))
	var pos = _element_position(node)
	if pos == null: return _err("element has no position to focus")
	cam.global_position = pos
	if req.has("zoom"):
		_apply_zoom(cam, float(req["zoom"]))
	return _ok({ "id": req.get("id"), "focused": _vec(pos), "camera": _camera_state(cam) })

func _fit_elements(req : Dictionary) -> Dictionary:
	var cam = _camera()
	if cam == null: return _err("camera not available")
	# With no ids, frame the whole map. Calling fit_elements() to see what you
	# have just built is the obvious thing to do, and it used to fail with
	# "no elements with bounds to fit" on a map holding 569 objects.
	var ids = req.get("ids", [])
	if ids.size() == 0:
		var cam0 = _camera()
		var dims = Global.World.WoxelDimensions
		cam0.global_position = Vector2(dims.x * 0.5, dims.y * 0.5)
		var vp = cam0.get_viewport().size
		var pad0 = 1.0 + float(req.get("pad", 0.05))
		cam0.zoom = Vector2(max(dims.x / vp.x, dims.y / vp.y) * pad0,
			max(dims.x / vp.x, dims.y / vp.y) * pad0)
		# Same response shape as the id path below, so a caller can parse one
		# thing. These used to differ — {fitted, position, zoom} here versus
		# {fit, missing, center, bounds, camera} there — for the same tool.
		return _ok({ "fit": "whole map", "missing": [],
			"center": _vec(cam0.global_position),
			"bounds": [[0, 0], [dims.x, dims.y]],
			"camera": { "position": _vec(cam0.global_position),
				"zoom": cam0.zoom.x,
				"viewport_size": [vp.x, vp.y] } })

	var mn = Vector2(INF, INF)
	var mx = Vector2(-INF, -INF)
	var used := 0
	var missing := []
	for ident in ids:
		var node = Global.World.GetNodeByID(int(ident))
		var rect = null
		if node != null:
			rect = _element_rect(node)
		if rect == null:
			missing.append(ident)
			continue
		mn.x = min(mn.x, rect.position.x); mn.y = min(mn.y, rect.position.y)
		mx.x = max(mx.x, rect.end.x); mx.y = max(mx.y, rect.end.y)
		used += 1
	if used == 0:
		return _err("no elements with bounds to fit")
	var center = (mn + mx) * 0.5
	cam.global_position = center
	# Zoom so the box fits: zoom (Camera2D) = world_span / viewport_span.
	var pad = 1.0 + float(req.get("pad", 0.15))
	var raw = mx - mn
	var vp = _viewport_size()
	var z
	if raw.length() < 1.0:
		# Degenerate box (one point, no derivable bounds): use a sane close zoom
		# instead of slamming to the minimum and burying the camera in a pixel.
		z = 1.0
	else:
		var span = raw * pad
		z = max(span.x / max(vp.x, 1.0), span.y / max(vp.y, 1.0))
	_apply_zoom(cam, z)
	return _ok({
		"fit": used, "missing": missing,
		"center": _vec(center), "bounds": [_vec(mn), _vec(mx)],
		"camera": _camera_state(cam),
	})

# A representative world point for any element kind: the center of its bounding
# rect (so walls/large props focus on their middle, not their anchor).
func _element_position(node):
	var rect = _element_rect(node)
	if rect != null:
		return rect.position + rect.size * 0.5
	return null

func _element_rect(node):
	if _is_text(node):
		return node.get_global_rect()

	if node.get("WallID") != null and node.get("Direction") != null:
		var ppos = node.get("position")
		if ppos != null and ppos is Vector2:
			var pradius = node.get("Radius")
			var half = float(pradius) if pradius != null else 64.0
			return Rect2(ppos - Vector2(half, half), Vector2(half * 2.0, half * 2.0))
	var grect = node.get("GlobalRect")
	if grect != null and grect is Rect2 and grect.size.length() > 0.0:
		return grect
	var prect = node.get("Rect")
	if prect != null and prect is Rect2 and prect.size.length() > 0.0:
		return prect
	# A prop's Rect can be empty until DD computes it; derive bounds from the
	# Sprite's texture size * node scale, centered on the node position.
	if node is Node2D:
		var spr = node.get("Sprite")
		if spr != null and spr.has_method("get_texture") and spr.get_texture() != null:
			var tsize = spr.get_texture().get_size() * node.scale
			if tsize.length() > 0.0:
				return Rect2(node.position - tsize * 0.5, tsize)
	var pts = node.get("Points")
	if pts != null and pts is PoolVector2Array and pts.size() > 0:
		var mn = Vector2(INF, INF)
		var mx = Vector2(-INF, -INF)
		for p in pts:
			mn.x = min(mn.x, p.x); mn.y = min(mn.y, p.y)
			mx.x = max(mx.x, p.x); mx.y = max(mx.y, p.y)
		return Rect2(mn, mx - mn)
	if node is Node2D:
		return Rect2(node.position, Vector2())
	return null

# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

func _select_elements(req : Dictionary) -> Dictionary:
	var stool = Global.Editor.Tools["SelectTool"]

	stool.Enable()
	_select_tool_enabled = true
	stool.DeselectAll()
	var n := 0
	for ident in req.get("ids", []):
		var node = Global.World.GetNodeByID(int(ident))
		if node != null:
			stool.SelectThing(node, true)
			n += 1
	stool.EnableTransformBox(true)
	# Report what could NOT be selected. Asking for 5 ids and getting 2 is a
	# fact the caller needs; "selected: 2" alone does not say which vanished.
	var missing := []
	for ident in req.get("ids", []):
		if Global.World.GetNodeByID(int(ident)) == null:
			missing.append(int(ident))
	return _ok({ "selected": n, "missing": missing })

func _clear_selection() -> Dictionary:
	# Safe only once the tool has been enabled; see _select_elements.
	if not _select_tool_enabled:
		return _ok({ "cleared": false,
			"reason": "nothing selected through this bridge yet" })
	Global.Editor.Tools["SelectTool"].DeselectAll()
	return _ok({ "cleared": true })

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

func _collection(level, kind : String) -> Node:
	return level.get(COLLECTIONS[kind])

func _is_preview(node) -> bool:
	return node.has_meta("preview") and bool(node.get_meta("preview"))

func _wall_mounted_portals(level) -> Array:
	var out := []
	for wall in level.Walls.get_children():
		var wall_portals = wall.get("Portals")
		if wall_portals == null:
			continue
		for portal in wall_portals:
			out.append(portal)
	return out

# Real children of a collection: everything a caller placed, and none of the
# tool previews sharing the node with them.
func _real_children(level, kind : String) -> Array:
	var out := []
	for node in _collection(level, kind).get_children():
		if not _is_preview(node):
			out.append(node)
	return out

func _new_object(level, sorting : int, layer : int = DEFAULT_OBJECT_LAYER):
	var prop = level.Objects.CreateObject(sorting)
	if prop == null:
		return null
	prop.set_meta("preview", false)

	prop.z_index = layer
	return prop

func _mark_saveable(node):
	if node != null and is_instance_valid(node):
		node.set_meta("preview", false)
	return node

func _new_light(level):
	var light = level.Lights.CreateLight(false)
	if light != null:
		light.set_meta("preview", false)
	return light

func _id(node) -> int:
	if node.has_meta("node_id"):
		return int(node.get_meta("node_id"))
	var nid = Global.World.AssignNodeID(node)
	if nid != null:
		return int(nid)
	if node.has_meta("node_id"):
		return int(node.get_meta("node_id"))
	return -1

func _resolve(req : Dictionary):
	if not req.has("id"):
		return null
	return Global.World.GetNodeByID(int(req["id"]))

# A DD Text node extends LineEdit (a Control), so GetSelectableType doesn't
# classify it and it has no Node2D `.position` — special-case it up front.
func _is_text(node) -> bool:
	return (node is Control) and node.has_method("SetFontSize")

func _describe(node, want_points : bool = true) -> Dictionary:
	# A wall-mounted portal carries a WallID script var and lives under its wall;
	# describe it richly (position + outward normal) like list_elements does.
	if node.get("WallID") != null and node.get("Direction") != null \
			and node.get_parent() != Global.World.GetCurrentLevel().Portals:
		var parent = node.get_parent()
		if parent != null:
			return _describe_wall_portal(node, parent)
	if _is_text(node):
		# DD Text extends LineEdit (Control): position is rect_position, the
		# string is the inherited `.text`, and size/color are the `fontSize` /
		# `fontColor` members. LineEdit has no rotation, so none is reported.
		var td := {
			"id": _id(node), "kind": "text",
			"position": _vec(node.rect_position),
			"text": node.text,
		}
		var fsize = node.get("fontSize")
		if fsize != null:
			td["size"] = int(fsize)
		var fcolor = node.get("fontColor")
		if fcolor != null and fcolor is Color:
			td["color"] = "#" + fcolor.to_html(false)
		var fname = node.get("fontName")
		if fname != null and str(fname) != "":
			td["font"] = str(fname)
		return td
	var stool = Global.Editor.Tools["SelectTool"]
	var t = stool.GetSelectableType(node)
	var d := { "id": _id(node), "kind": KIND_NAMES.get(t, "unknown") }
	if node.get_parent() == Global.World.GetCurrentLevel().Portals: d["kind"] = "portal"
	if node is Node2D:
		d["position"] = _vec(node.position)
		d["rotation"] = rad2deg(node.rotation)
		d["scale"] = node.scale.x

		d["layer"] = _pattern_draw_layer(node) if d.get("kind") == "pattern" else node.z_index
	var tex = _texture_of(node, t)
	if tex != null:
		d["asset"] = tex.resource_path

		var tex_size = tex.get_size()
		if tex_size.x > 0 and tex_size.y > 0:
			d["texture_size"] = _vec(tex_size)
	var col = _read_node_color(node)
	if col != null:
		d["color"] = "#" + col.to_html(false)

	var shadow = node.get("HasShadow")
	if shadow != null:
		d["shadow"] = shadow
	var blocks_light = node.get("BlockLight")
	if blocks_light != null:
		d["block_light"] = bool(blocks_light)

	if d.get("kind") == "object" and node is Node2D:
		d["layer"] = node.z_index

	if d.get("kind") == "roof":
		var ridge = node.get("points")
		if ridge != null:
			var ridge_out := []
			for ridge_point in ridge:
				if ridge_point is Vector2:
					ridge_out.append(_vec(node.to_global(ridge_point) if node is Node2D
						else ridge_point))
			d["points"] = ridge_out
		var roof_width = node.get("width")
		if roof_width != null:
			d["width"] = float(roof_width)
		var roof_type = node.get("type")
		if roof_type != null:
			d["roof_type"] = int(roof_type)
		var shaded = node.get("shade")
		if shaded != null:
			d["sunlight"] = bool(shaded)
		var contrast = node.get("shadeContrast")
		if contrast != null:
			d["sun_contrast"] = float(contrast)

	# Lights are Light2D: everything add_light writes should read back, or the
	# model cannot check its own lighting without a screenshot. These were all
	# settable and none was readable.
	var energy = node.get("energy")
	if energy != null:
		d["energy"] = float(energy)
		var lc = node.get("color")
		if lc != null and lc is Color:
			d["color"] = "#" + lc.to_html(false)
		var reach = node.get("texture_scale")
		if reach != null:
			d["range"] = float(reach)
		var sh = node.get("shadow_enabled")
		if sh != null:
			d["shadows"] = bool(sh)
	var mod_tint = _read_node_modulate(node)
	if mod_tint != null:

		d["modulate"] = "#" + mod_tint.to_html(false)

	var loop = node.get("Loop")
	if loop != null:
		d["loop"] = bool(loop)

	if want_points:
		var pts = node.get("Points")
		if node is Polygon2D: pts = node.polygon
		if pts != null and pts.size() > 0:
			var out := []

			for pt in pts:
				if node is Node2D:
					out.append(_vec(node.to_global(pt)))
				else:
					out.append(_vec(pt))
			d["points"] = out
	return d

# The Texture behind a node, or null. Where the texture lives depends on the
# kind: most engine types expose a `Texture` member, paths and lights answer
# get_texture(), and a roof keeps its own under TilesTexture.
func _texture_of(node, kind : int):
	var tex = null
	if kind in [1, 2, 3, 4]:
		tex = node.get("Texture")
	elif kind in [5, 6]:
		if node.has_method("get_texture"):
			tex = node.get_texture()
	elif kind == 8:
		tex = node.get("TilesTexture")
	if tex != null and tex is Texture:
		return tex
	return null

func _texture_path(node, kind : int) -> String:
	var tex = _texture_of(node, kind)
	if tex != null:
		return tex.resource_path
	return ""

# Cache of category -> { asset_path: true }, built lazily on first use.
var _asset_index := {}
var _asset_index_packs := ""

func _mask_stats(tex) -> Dictionary:
	if tex == null or not tex.has_method("get_data"):
		return {}
	var img = tex.get_data()
	if img == null:
		return {}
	var tw = img.get_width()
	var th = img.get_height()
	if tw < 2 or th < 2:
		return {}
	img.lock()
	var hues := []
	var sats := []
	for j in range(24):
		for i in range(24):
			var px = int(float(i) / 23.0 * float(tw - 1))
			var py = int(float(j) / 23.0 * float(th - 1))
			var col = img.get_pixel(px, py)
			if col.a < 0.5:
				continue
			if col.r > 0.25 and col.r > col.g * 1.8 and col.r > col.b * 1.8:
				hues.append(col.h)
				sats.append(col.s)
	img.unlock()
	if hues.size() == 0:
		return {}
	var hmin = 1.0
	var hmax = 0.0
	var hsum = 0.0
	for hv in hues:
		var v = hv
		if v > 0.5:
			v -= 1.0
		hmin = min(hmin, v)
		hmax = max(hmax, v)
		hsum += v
	var ssum = 0.0
	for sv in sats:
		ssum += sv
	return { "n": hues.size(), "hue_spread": hmax - hmin,
		"hue_mean": hsum / float(hues.size()),
		"sat_mean": ssum / float(sats.size()) }

func _mask_fraction(tex) -> float:
	if tex == null or not tex.has_method("get_data"):
		return -1.0
	var img = tex.get_data()
	if img == null:
		return -1.0
	var tw = img.get_width()
	var th = img.get_height()
	if tw < 2 or th < 2:
		return -1.0
	img.lock()
	var steps := 24
	var opaque := 0
	var masked := 0
	for j in range(steps):
		for i in range(steps):
			var px = int(float(i) / float(steps - 1) * float(tw - 1))
			var py = int(float(j) / float(steps - 1) * float(th - 1))
			var col = img.get_pixel(px, py)
			if col.a < 0.5:
				continue
			opaque += 1

			if col.g <= 0.004 and col.b <= 0.004 and col.r > 0.02:
				masked += 1
	img.unlock()
	if opaque == 0:
		return 0.0
	return float(masked) / float(opaque)

func _asset_tex(category : String, asset):
	if typeof(asset) != TYPE_STRING or asset == "":
		return null
	# GetAssetList is cached per category, but opening a map re-scopes the
	# library while the packs themselves stay mounted. Without this, the cache
	# keeps offering assets the newly opened map cannot keep.
	var signature = _manifest_signature()
	if signature != _asset_index_packs:
		_asset_index = {}
		_asset_index_packs = signature
	if not _asset_index.has(category):

		if not (category in ASSET_CATEGORIES):
			return null
		var known := {}
		var all = Script.GetAssetList(category)
		if all != null:
			for path in all:
				known[str(path)] = true
		_asset_index[category] = known
	if not _asset_index[category].has(asset):
		return null
	return Script.GetAssetTexture(category, asset)

func _xy(req : Dictionary, fallback : Vector2) -> Vector2:
	if req.has("x") and req.has("y"):
		return Vector2(float(req["x"]), float(req["y"]))
	return fallback

func _vec(v : Vector2) -> Array:
	return [v.x, v.y]

func _points(raw) -> PoolVector2Array:
	var pts := PoolVector2Array()
	if typeof(raw) != TYPE_ARRAY:
		return pts
	for p in raw:
		if typeof(p) == TYPE_ARRAY and p.size() >= 2:
			pts.append(Vector2(float(p[0]), float(p[1])))
	return pts

func _is_hex_color(t : String) -> bool:
	var h = t
	if h.begins_with("#"):
		h = h.substr(1)
	if not (h.length() in [3, 4, 6, 8]):
		return false
	for i in range(h.length()):
		var ch = h.substr(i, 1).to_lower()
		if "0123456789abcdef".find(ch) == -1:
			return false
	return true

func _color(v, fallback : Color) -> Color:
	if typeof(v) == TYPE_STRING and v != "":
		if not _is_hex_color(v):
			return fallback
		return Color(v)
	if typeof(v) == TYPE_ARRAY and v.size() >= 3:
		var a = 1.0
		if v.size() >= 4:
			a = float(v[3])
		return Color(float(v[0]), float(v[1]), float(v[2]), a)
	return fallback

func _set_node_color(node, color : Color) -> String:
	if node.has_method("SetColor"):
		node.SetColor(color)
		return "SetColor"
	if node.has_method("SetCustomColor"):
		node.SetCustomColor(color)
		return "SetCustomColor"
	return ""

func _refuse_modulate(req : Dictionary):
	if req.has("modulate") and str(req.get("modulate", "")) != "":
		return _err("modulate is unavailable because Dungeondraft does not preserve it when saving and reopening. No changes were made.")
	return null

func _modulate_requested(req : Dictionary) -> bool:
	return _color_requested(req, "modulate")

# Is req[key] a colour this bridge can actually use? _color() falls back to a
# default rather than failing, so every caller that cares must ask first.
func _color_requested(req : Dictionary, key : String) -> bool:
	if not req.has(key):
		return false
	var v = req[key]
	if typeof(v) == TYPE_STRING:
		return v != "" and _is_hex_color(v)
	return typeof(v) == TYPE_ARRAY and v.size() >= 3

func _set_node_modulate(node, color : Color) -> bool:
	if node.has_method("set_modulate"):
		node.set_modulate(color)
		return true
	return false

func _read_node_color(node):
	if node.has_method("get_Color"):
		var c = node.get_Color()
		if c is Color:
			return c
	if node.has_method("HasCustomColor") and node.has_method("GetCustomColor"):
		if node.HasCustomColor():
			var cc = node.GetCustomColor()
			if cc is Color:
				return cc

	var prop_color = node.get("Color")
	if prop_color is Color:
		return prop_color
	return null

# Reports a node's multiplicative tint only when it has actually been changed
# from the identity, so an untinted object does not carry noise in every read.
func _read_node_modulate(node):
	if node.has_method("get_modulate"):
		var m = node.get_modulate()
		if m is Color and not (m.r == 1.0 and m.g == 1.0 and m.b == 1.0 and m.a == 1.0):
			return m
	return null

func _connect_one(source, signal_name : String, method : String) -> void:
	if source == null or not source.has_signal(signal_name):
		return
	if source.is_connected(signal_name, self, method):
		_signals[signal_name] = true
		return
	if source.connect(signal_name, self, method) == OK:
		_signals[signal_name] = true

func _connect_signals() -> void:
	_signals = {}
	_connect_one(Global.Editor, "OnSaveBegin", "_on_save_begin")
	_connect_one(Global.Editor, "OnSaveEnd", "_on_save_end")
	_connect_one(Global.World, "OnAssignNode", "_on_assign_node")

func _on_save_begin(path, is_backing_up) -> void:
	# A save that begins while another never ended means the earlier one died.
	if _save_in_flight and _save_path != "" and _save_path != str(path):
		_save_failed_path = _save_path
	# A new attempt at the failed file; if it dies too, it is recorded again.
	if str(path) == _save_failed_path:
		_save_failed_path = ""
	_save_in_flight = true
	_save_begins += 1
	_save_stale_path = ""
	_save_path = str(path)
	_save_is_backup = bool(is_backing_up)
	_save_started_ms = OS.get_ticks_msec()
	if _verbose:
		print("[mcp-bridge] save begin: %s (backup: %s)" % [_save_path, str(_save_is_backup)])

func _on_save_end() -> void:
	_save_in_flight = false
	_save_stale_path = ""
	_saves_seen += 1
	if _save_path != "":
		_last_save_path = _save_path
	if _save_path == _save_failed_path:
		_save_failed_path = ""
	if _verbose:
		print("[mcp-bridge] save end: %s" % _last_save_path)

func _on_assign_node(node) -> void:
	_assign_seq += 1
	_assigned.append({ "seq": _assign_seq, "ref": weakref(node) })
	while _assigned.size() > ASSIGN_LOG_MAX:
		_assigned.pop_front()

# True while Dungeondraft is writing the map. Self-expiring: see SAVE_STALE_MS.
func _saving() -> bool:
	if not _save_in_flight:
		return false
	if OS.get_ticks_msec() - _save_started_ms > SAVE_STALE_MS:
		_save_in_flight = false
		_save_stale_path = _save_path
		_save_failed_path = _save_path
		print("[mcp-bridge] save of %s never reported an end; clearing the guard" % _save_path)
		return false
	return true

func _save_state() -> Dictionary:
	# Call _saving() first: expiring the guard is what records staleness.
	var in_flight = _saving()
	var state := {
		"in_flight": in_flight,
		"path": _save_path,
		"is_backup": _save_is_backup,
		"last_saved": _last_save_path,
		"saves_seen": _saves_seen,
		"tracked": _signals.has("OnSaveBegin") and _signals.has("OnSaveEnd"),
	}
	if _save_failed_path != "":
		state["last_failed"] = _save_failed_path
	if _save_stale_path != "":
		state["last_result"] = "stale"
		state["stale_path"] = _save_stale_path

		state["note"] = ("a save of %s started but Dungeondraft never " +
			"reported finishing it, which almost always means its serializer " +
			"threw — look in the Dungeondraft log for an exception under " +
			"World.Save. The file was probably NOT written. Call save_map once: " +
			"if it reports that no save started, Dungeondraft's saving is " +
			"wedged and only a restart recovers, losing unsaved work.") \
			% _save_stale_path
	return state

# Node ids Dungeondraft has assigned since `since`. The id is resolved here
# rather than at signal time because OnAssignNode can fire before the node_id
# metadata is written; entries whose node is gone are reported as freed.
func _get_recent_nodes(req : Dictionary) -> Dictionary:
	if not _signals.has("OnAssignNode"):
		return _err("this build does not emit World.OnAssignNode; " +
			"node ids can only be discovered by placing things yourself")
	var since = int(req.get("since", 0))
	var limit = int(req.get("limit", 200))
	if limit < 1: limit = 1
	if limit > ASSIGN_LOG_MAX: limit = ASSIGN_LOG_MAX

	var nodes := []
	var dropped := false
	if _assigned.size() > 0 and int(_assigned[0]["seq"]) > since + 1:
		dropped = true
	for entry in _assigned:
		if int(entry["seq"]) <= since:
			continue
		if nodes.size() >= limit:
			break
		var node = entry["ref"].get_ref()
		var row := { "seq": int(entry["seq"]) }
		if node == null:
			row["freed"] = true
		else:
			row["id"] = _node_id_or(node, -1)
			row["class"] = node.get_class()
			if node.get("name") != null:
				row["name"] = str(node.name)
		nodes.append(row)
	return _ok({ "nodes": nodes, "next_since": _assign_seq, "dropped_older": dropped,
		"log_capacity": ASSIGN_LOG_MAX })

func _node_id_or(node, fallback : int) -> int:
	if node != null and node.has_meta("node_id"):
		return int(node.get_meta("node_id"))
	return fallback

# Mark the current point in the assignment log, so a handler can report exactly
# which nodes ITS call caused Dungeondraft to create.
func _assign_mark() -> int:
	return _assign_seq

func _assigned_since(mark : int, limit : int = 500) -> Array:
	var ids := []
	var seen := {}
	for entry in _assigned:
		if int(entry["seq"]) <= mark:
			continue
		var node = entry["ref"].get_ref()
		if node == null:
			continue
		var nid = _node_id_or(node, -1)
		if nid >= 0 and not seen.has(nid):
			seen[nid] = true
			ids.append(nid)
		if ids.size() >= limit:
			break
	return ids

func _checkpoint_key(session : String, label : String) -> String:
	return session + "\n" + label

func _checkpoint(req : Dictionary) -> Dictionary:
	var label = str(req.get("label", "")).strip_edges()
	if label == "" or label.length() > 64:
		return _err("'label' is required, up to 64 characters")
	var key = _checkpoint_key(_current_session, label)
	if not _checkpoints.has(key) and _checkpoints.size() >= MAX_CHECKPOINTS:
		return _err("%d checkpoints are open; roll back or reuse a label" % MAX_CHECKPOINTS)
	_checkpoints[key] = { "label": label, "session": _current_session,
		"after": _op_serial, "unrecorded": [], "opened": _clock() }
	return _ok({ "label": label, "history_limit": MAX_UNDO_OPS,
		"note": "rollback_checkpoint(label) undoes this session's edits from here, " +
			"in one call, while history still reaches back this far" })

func _steps_since(cp : Dictionary) -> Array:
	var out := []
	for op in _undo_stack:
		if int(op.get("serial", 0)) > int(cp["after"]):
			out.append(op)
	return out

func _checkpoint_view(cp : Dictionary) -> Dictionary:
	var steps = _steps_since(cp)
	var foreign := 0
	for op in steps:
		if str(op.get("session", "")) != str(cp["session"]):
			foreign += 1
	return { "label": cp["label"], "mine": str(cp["session"]) == _current_session,
		"opened": cp["opened"], "steps_since": steps.size(),
		"other_sessions_steps": foreign,
		"reachable": _lost_serial <= int(cp["after"]),
		"not_reversible": cp["unrecorded"] }

func _list_checkpoints(req : Dictionary) -> Dictionary:
	var out := []
	for key in _checkpoints:
		out.append(_checkpoint_view(_checkpoints[key]))
	return _ok({ "checkpoints": out })

func _rollback_checkpoint(req : Dictionary) -> Dictionary:
	var label = str(req.get("label", "")).strip_edges()
	var key = _checkpoint_key(_current_session, label)
	if not _checkpoints.has(key):
		var mine := []
		for other in _checkpoints.values():
			if str(other["session"]) == _current_session:
				mine.append(other["label"])
		return _err("no checkpoint '%s' in this session; open ones: %s" % [label, str(mine)])
	var cp = _checkpoints[key]
	if _lost_serial > int(cp["after"]):
		return _err(("history no longer reaches checkpoint '%s': a step made after it " +
			"was dropped (history keeps %d steps, and %d MB of terrain and cave " +
			"snapshots). Nothing was changed. Undo step by step what remains, or " +
			"restore the last saved map.")
			% [label, MAX_UNDO_OPS, SNAPSHOT_BUDGET_BYTES / (1024 * 1024)])
	var steps = _steps_since(cp)
	var foreign := {}
	for op in steps:
		if str(op.get("session", "")) != str(cp["session"]):
			var who = str(op.get("session", ""))
			foreign[who] = int(foreign.get(who, 0)) + 1
	if not foreign.empty():
		var count := 0
		for who in foreign: count += int(foreign[who])
		return _err(("another session made %d of the %d edits since checkpoint '%s' " +
			"(another assistant, or a second chat). Rolling back would undo their " +
			"work, so nothing was changed.") % [count, steps.size(), label])
	var undone := []
	var stopped = ""
	var more := false

	var restored := {}
	while not _undo_stack.empty() and int(_undo_stack.back().get("serial", 0)) > int(cp["after"]):
		var top = _undo_stack.back()
		var pending := false
		for node in _op_nodes(top):
			if restored.has(node):
				pending = true
		if pending:
			more = true
			break
		var result = _do_undo()
		if not result.get("ok", false):
			stopped = str(result.get("error", ""))
			break
		if not result["result"].get("undone", false):
			break
		undone.append(result["result"]["kind"])
		if str(top.get("kind", "")) in ["delete", "delete_many"]:
			for node in _op_nodes(top):
				restored[node] = true
	var out = { "label": label, "rolled_back": undone.size(), "kinds": undone,
		"continue": more, "not_reversible": cp["unrecorded"],
		"undo_depth": _undo_stack.size(), "redo_depth": _redo_stack.size() }
	if stopped != "":
		out["stopped"] = ("stopped after %d of %d steps: %s. The rest are still on " +
			"the map; undo them step by step.") % [undone.size(), steps.size(), stopped]
	if not more and not cp["unrecorded"].empty():
		out["note"] = ("these changes since the checkpoint are not in history and " +
			"were not reversed: %s") % str(cp["unrecorded"])
	if not more:
		cp["unrecorded"] = []
	return _ok(out)

# The nodes an op attaches or detaches, for rollback's same-frame check.
func _op_nodes(op) -> Array:
	var kind = str(op.get("kind", ""))
	if kind in ["create", "delete"] and op.has("node"):
		return [op["node"]]
	if kind in ["group", "delete_many"]:
		var nodes := []
		for entry in op.get("entries", []):
			nodes.append(entry.get("node"))
		return nodes
	return []

func _note_unrecorded(cmd : String) -> void:
	for cp in _checkpoints.values():
		if str(cp["session"]) == _current_session and not (cmd in cp["unrecorded"]):
			cp["unrecorded"].append(cmd)

# Warn in an edit's reply while an open checkpoint of this session is about to
# lose its oldest step: history drops the oldest step past MAX_UNDO_OPS.
func _checkpoint_warning(result) -> void:
	if typeof(result) != TYPE_DICTIONARY or typeof(result.get("result")) != TYPE_DICTIONARY:
		return
	for cp in _checkpoints.values():
		if str(cp["session"]) != _current_session:
			continue
		if _lost_serial > int(cp["after"]):
			result["result"]["checkpoint_warning"] = ("checkpoint '%s' can no longer be " +
				"rolled back: history has dropped a step made after it") % cp["label"]
			return
		var first := -1
		for i in range(_undo_stack.size()):
			if int(_undo_stack[i].get("serial", 0)) > int(cp["after"]):
				first = i
				break
		if first < 0:
			continue
		var left = MAX_UNDO_OPS - _undo_stack.size() + first
		if left <= CHECKPOINT_WARN_STEPS:
			result["result"]["checkpoint_warning"] = ("checkpoint '%s' loses its oldest " +
				"step after %d more edit(s); save_map now, or a rollback will not reach " +
				"it") % [cp["label"], left]
			return

const SNAP_MOD_TOOL := "snappy_mod"
const SNAP_MOD_FIELDS := ["custom_snap_enabled", "active_geometry", "snap_interval",
	"snap_offset", "radial_mode_to_corner"]

func _snap_mod_instance():
	if Global.Editor == null or not Global.Editor.Tools.has(SNAP_MOD_TOOL):
		return null
	var wrapper = Global.Editor.Tools[SNAP_MOD_TOOL]
	if wrapper == null or not wrapper.has_method("get_ScriptInstance"):
		return null
	var instance = wrapper.get_ScriptInstance()
	if instance == null or typeof(instance) != TYPE_OBJECT:
		return null
	return instance

func _snap_value(value):
	if typeof(value) == TYPE_VECTOR2:
		return [value.x, value.y]
	return value

func _get_snap_settings(req : Dictionary) -> Dictionary:
	var out := { "vanilla_snapping": null, "mod_loaded": false }
	if Global.Editor != null and Global.Editor.has_method("get_IsSnapping"):
		out["vanilla_snapping"] = bool(Global.Editor.get_IsSnapping())
	var mod = _snap_mod_instance()
	if mod == null:
		return _ok(out)
	out["mod_loaded"] = true
	var settings := {}
	for field in SNAP_MOD_FIELDS:
		var value = mod.get(field)
		if value == null:
			# A different version of the mod: report what could not be read
			# rather than a grid built from half of it.
			out["unreadable"] = field
			return _ok(out)
		settings[field] = _snap_value(value)
	out["settings"] = settings
	var presets = mod.get("preset_options")
	var chosen = mod.get("preset_menu_setting")
	if typeof(presets) == TYPE_ARRAY and typeof(chosen) == TYPE_INT \
			and chosen >= 0 and chosen < presets.size() \
			and typeof(presets[chosen]) == TYPE_DICTIONARY:
		out["preset"] = str(presets[chosen].get("preset_name", ""))

	var points = req.get("points", [])
	if typeof(points) == TYPE_ARRAY and not points.empty():
		if points.size() > 200:
			return _err("'points' is capped at 200")
		if not mod.has_method("get_snapped_position"):
			out["mod_snapped"] = null
			return _ok(out)
		var snapped := []
		for point in _points(points):
			snapped.append(_snap_value(mod.get_snapped_position(point)))
		out["mod_snapped"] = snapped
	return _ok(out)

const PATCH_ID := "Moulk.BugFixes"
const PATCH_VERIFIED := ["1.7"]
const PATCH_ABOVE_LIGHTS_LAYER := 1100
const PATCH_MAP_TILES_MIN := 1
# The patch's resize allows 500 but warns above 200 ("can cause unexpected
# behavior"); the bridge stays inside the range it calls safe.
const PATCH_MAP_TILES_MAX := 200
# Commands that write Dungeondraft's two terrain splats.
const TERRAIN_PAINT_CMDS := ["paint_terrain", "fill_terrain", "fill_region", "repair_terrain"]

func _patch_info() -> Dictionary:
	var version = null
	if Engine.has_meta("_moulk_upd_registry"):
		var registry = Engine.get_meta("_moulk_upd_registry")
		if typeof(registry) == TYPE_DICTIONARY and registry.has(PATCH_ID) \
				and typeof(registry[PATCH_ID]) == TYPE_DICTIONARY:
			version = str(registry[PATCH_ID].get("local", ""))

	if version == null and Engine.has_meta("terrain_slots_extended_singleton"):
		version = ""
	if version == null:
		return { "loaded": false }
	var parts = version.split(".")
	var minor = "%s.%s" % [parts[0], parts[1]] if parts.size() >= 2 else ""
	return { "loaded": true, "version": version, "verified": minor in PATCH_VERIFIED }

func _patch_loaded() -> bool:
	return _patch_info().loaded

func _patch_verified() -> bool:
	var info = _patch_info()
	return info.loaded and info.verified

# The object behind one of the patch's Engine metadata entries: either the
# object itself or a listener node whose `handler` is the patch script.
func _patch_handler(meta : String):
	if not _patch_verified() or not Engine.has_meta(meta):
		return null
	var node = Engine.get_meta(meta)
	if node == null or typeof(node) != TYPE_OBJECT or not is_instance_valid(node):
		return null
	var handler = node.get("handler")
	if handler == null:
		return node
	if typeof(handler) != TYPE_OBJECT or not is_instance_valid(handler):
		return null
	return handler

func _layer_allowed(layer : int) -> bool:
	if layer >= LAYER_MIN and layer <= LAYER_MAX and layer % LAYER_STEP == 0:
		return true
	return layer == PATCH_ABOVE_LIGHTS_LAYER and _patch_loaded()

func _bad_layer(req : Dictionary):
	if not req.has("layer"):
		return null
	var value = req["layer"]
	if not (typeof(value) in [TYPE_INT, TYPE_REAL]) or not _layer_allowed(int(value)):
		return _err("'layer' must be %s; got %s" % [_layer_rule(), str(value)])
	return null

func _layer_rule() -> String:
	var rule = "a multiple of %d from %d to %d" % [LAYER_STEP, LAYER_MIN, LAYER_MAX]
	if _patch_loaded():
		rule += ", or %d (the Unofficial Patch's Above Lights layer)" % PATCH_ABOVE_LIGHTS_LAYER
	return rule

func _patch_release_zoom() -> void:
	var zoom = _patch_handler("up_zoomunlock_listener")
	if zoom == null or zoom.get("_extended") != true:
		return
	var options = Global.Editor.get("ZoomOptions")
	if options == null or not is_instance_valid(options) or not options.has_signal("item_selected"):
		return
	options.emit_signal("item_selected", int(options.selected))

func _patch_adopt_text() -> void:
	var fix = _patch_handler("_TextToolFixListener")
	if fix == null or fix.get("_prev_text_count") == null:
		return
	var level = Global.World.GetCurrentLevel()
	if level == null or level.Texts == null:
		return
	fix.set("_prev_text_count", level.Texts.get_child_count())

func _patch_wall_ids() -> Dictionary:
	var ids := {}
	var level = Global.World.GetCurrentLevel()
	if level == null or level.Walls == null:
		return ids
	ids["level"] = level.get_instance_id()
	for wall in level.Walls.get_children():
		ids[wall.get_instance_id()] = true
	return ids

# Runs the frame after a bridge edit, once deferred attaches have landed.
func _patch_after_edit(walls_before : Dictionary, groups_touched := 0) -> void:
	_patch_adopt_text()
	if groups_touched == 1 or (groups_touched == 2 and _patch_map_has_groups()):
		_patch_save_groups()
	var level = Global.World.GetCurrentLevel()
	if level == null or level.Walls == null:
		return
	# After a level switch every wall would look new, the user's included.
	if walls_before.get("level") != level.get_instance_id():
		return
	for wall in level.Walls.get_children():
		if not walls_before.has(wall.get_instance_id()):
			_patch_adopt_wall(wall)

const PATCH_GROUP_MIN_ID := 10000

func _patch_group_handler():
	if not _patch_verified() or Global.World == null:
		return null
	var listener = Global.World.get_node_or_null("GroupAssetsListener")
	if listener == null or not is_instance_valid(listener):
		return null
	var handler = listener.get("handler")
	if handler == null or not is_instance_valid(handler) or not handler.has_method("_save_groups"):
		return null
	return handler

func _patch_touches_group(req : Dictionary) -> bool:
	var ids := []
	if req.has("id"):
		ids.append(req["id"])
	if typeof(req.get("ids")) == TYPE_ARRAY:
		ids.append_array(req["ids"])
	for raw in ids:
		if not (typeof(raw) in [TYPE_INT, TYPE_REAL]):
			continue
		var node = Global.World.GetNodeByID(int(raw))
		if node != null and node.has_meta("prefab_id") \
				and int(node.get_meta("prefab_id")) >= PATCH_GROUP_MIN_ID:
			return true
	return false

func _patch_map_has_groups() -> bool:
	var handler = _patch_group_handler()
	if handler == null or not handler.has_method("_get_all_groupable_nodes"):
		return false
	for node in handler._get_all_groupable_nodes():
		if node != null and is_instance_valid(node) and node.has_meta("prefab_id") \
				and int(node.get_meta("prefab_id")) >= PATCH_GROUP_MIN_ID:
			return true
	return false

func _patch_save_groups() -> void:
	var handler = _patch_group_handler()
	if handler != null:
		handler._save_groups()

func _patch_adopt_wall(wall) -> void:
	if wall == null or not is_instance_valid(wall) or not Engine.has_meta("wal_timer"):
		return
	if not _patch_verified():
		return
	var timer = Engine.get_meta("wal_timer")
	if timer == null or typeof(timer) != TYPE_OBJECT or not is_instance_valid(timer):
		return
	for connection in timer.get_signal_connection_list("timeout"):
		var target = connection.get("target")
		if target != null and is_instance_valid(target) \
				and typeof(target.get("_known_wall_ids")) == TYPE_DICTIONARY:
			target._known_wall_ids[wall.get_instance_id()] = true

func _patch_terrain_extended() -> bool:
	var tse = _patch_handler("terrain_slots_extended_singleton")
	if tse == null or not tse.has_method("is_extended_active"):
		return false
	return tse.is_extended_active() == true

const PATCH_NODE_EFFECTS := {
	"_ft_transforms": "skew", "_ft_distort": "distort", "_ft_crop": "crop",
	"_ft_edgecrop": "edge_crop", "_ft_blur": "blur", "_ft_pattern_orig": "pattern_transform",
	"object_keep_lit": "keep_lit",
}
# What the patch's own paste copies to a pasted node; the position-bound
# pattern stores are rebuilt by the patch instead.
const PATCH_COPIED_STORES := ["_ft_transforms", "_ft_distort", "_ft_pattern_orig",
	"_ft_pattern_reset", "_ft_crop", "_ft_crop_soft", "_ft_crop_feather",
	"_ft_crop_opacity", "_ft_edgecrop", "_ft_blur", "object_keep_lit"]

func _patch_node_key(node) -> String:
	if node == null or not is_instance_valid(node) or not node.has_meta("node_id"):
		return ""
	return "node-id-%s" % str(node.get_meta("node_id"))

func _patch_store(store : String):
	var data = Global.get("ModMapData")
	if typeof(data) != TYPE_DICTIONARY or not data.has(store) \
			or typeof(data[store]) != TYPE_DICTIONARY:
		return null
	return data[store]

func _patch_node_effects(node) -> Array:
	var effects := []
	if not _patch_loaded():
		return effects
	var key = _patch_node_key(node)
	if key == "":
		return effects
	for store in PATCH_NODE_EFFECTS:
		var entries = _patch_store(store)
		if entries != null and entries.has(key):
			effects.append(PATCH_NODE_EFFECTS[store])
	var styles = _patch_store("TextStyleExtra")
	if styles != null and styles.has(str(node.get_meta("node_id"))):
		effects.append("text_style")
	return effects

func _patch_is_sheared(node) -> bool:
	var key = _patch_node_key(node)
	if key == "" or not _patch_loaded():
		return false
	for store in ["_ft_transforms", "_ft_distort"]:
		var entries = _patch_store(store)
		if entries != null and entries.has(key):
			return true
	return false

# Rotate and scale the whole transform, keeping the skew, and write the result
# where the patch keeps it (its own fold does the same when the user rotates).
func _patch_rotate_scale(node, rotation_deg, scale) -> void:
	var t : Transform2D = node.transform
	var basis = Transform2D(t.x, t.y, Vector2.ZERO)
	if rotation_deg != null:
		basis = Transform2D(deg2rad(float(rotation_deg)) - t.get_rotation(), Vector2.ZERO) * basis
	if scale != null and basis.x.length() > 0.0:
		var k = float(scale) / basis.x.length()
		basis = Transform2D(basis.x * k, basis.y * k, Vector2.ZERO)
	node.transform = Transform2D(basis.x, basis.y, t.origin)
	_patch_write_shear(node)

func _patch_write_shear(node) -> void:
	var entries = _patch_store("_ft_transforms")
	var key = _patch_node_key(node)
	if entries == null or key == "" or not entries.has(key):
		return
	var t : Transform2D = node.transform
	entries[key] = { "xx": t.x.x, "xy": t.x.y, "yx": t.y.x, "yy": t.y.y,
		"ox": t.origin.x, "oy": t.origin.y }
	_patch_persist_effects()

func _patch_persist_effects() -> void:
	if not _patch_verified():
		return
	var data = Global.get("ModMapData")
	if typeof(data) != TYPE_DICTIONARY or not data.has("_free_transform"):
		return
	var ft = data["_free_transform"]
	if ft != null and typeof(ft) == TYPE_OBJECT and is_instance_valid(ft) \
			and ft.has_method("_save_ft_data"):
		ft._save_ft_data()

# The patch's own paste copies these entries to the pasted node; a bridge
# duplicate does the same, or the copy loses them when the map reopens.
func _patch_copy_node_data(src, dst) -> Array:
	var copied := []
	# A fresh node has no node_id until one is assigned.
	if dst != null and is_instance_valid(dst):
		_id(dst)
	var from = _patch_node_key(src)
	var to = _patch_node_key(dst)
	if from == "" or to == "" or not _patch_verified():
		return copied
	var delta = dst.position - src.position
	for store in PATCH_COPIED_STORES:
		var entries = _patch_store(store)
		if entries == null or not entries.has(from):
			continue
		var value = entries[from]
		if typeof(value) == TYPE_DICTIONARY or typeof(value) == TYPE_ARRAY:
			value = value.duplicate(true)
		if store == "_ft_transforms" and typeof(value) == TYPE_DICTIONARY:
			value["ox"] = float(value.get("ox", 0.0)) + delta.x
			value["oy"] = float(value.get("oy", 0.0)) + delta.y
		entries[to] = value
		if PATCH_NODE_EFFECTS.has(store):
			copied.append(PATCH_NODE_EFFECTS[store])
	if not copied.empty():
		_patch_persist_effects()
	return copied

func _patch_terrain_refusal():
	if not _patch_terrain_extended():
		return null
	return _err("this level has the Unofficial Patch's 24 terrain slots turned on, " +
		"and the bridge paints only Dungeondraft's own 8. Painting here would leave " +
		"the patch's extra slots showing through, so nothing was changed. Paint this " +
		"level in Dungeondraft, or turn the extra slots off for it")

func _layer_tool(name : String):
	if name == "":
		return null
	if not Global.Editor.Tools.has(name):
		return null
	var candidate = Global.Editor.Tools[name]
	if not candidate.has_method("get_ActiveLayer"):
		return null
	return candidate

func _get_tool_layer(req : Dictionary) -> Dictionary:
	var name = str(req.get("tool", ""))
	var target = _layer_tool(name)
	if target == null:
		return _err("no tool '%s' with a layer on this build; layers exist on: %s"
			% [name, str(_layers_supported())])
	var out := { "tool": name, "layer": int(target.get_ActiveLayer()),
		"min": LAYER_MIN, "max": LAYER_MAX, "step": LAYER_STEP }
	if _patch_loaded():
		out["extra_layers"] = [PATCH_ABOVE_LIGHTS_LAYER]
	return _ok(out)

func _set_tool_layer(req : Dictionary) -> Dictionary:
	var name = str(req.get("tool", ""))
	var target = _layer_tool(name)
	if target == null:
		return _err("no tool '%s' with a layer on this build; layers exist on: %s"
			% [name, str(_layers_supported())])
	if not req.has("layer"):
		return _err("'layer' is required (an integer); call get_tool_layer to read the current one")
	var want = int(req["layer"])
	if not _layer_allowed(want):
		return _err("'layer' must be %s; got %d" % [_layer_rule(), want])
	if not target.has_method("SetLayer"):
		return _err("tool '%s' exposes no SetLayer" % name)

	var was_active = _enable_tool(name, target)
	var before = int(target.get_ActiveLayer())
	target.SetLayer(_layer_index(want))

	var raw = target.get_ActiveLayer()
	if typeof(raw) != TYPE_INT and typeof(raw) != TYPE_REAL:
		target.SetLayer(_layer_index(before))
		_release_tool(target, was_active)
		return _err(("setting layer %d left ActiveLayer unset even with '%s' " +
			"enabled, so this build does not lay the menu out as %d..%d by %d. " +
			"Restored %d.") % [want, name, LAYER_MIN, LAYER_MAX, LAYER_STEP, before])
	var after = int(raw)
	_release_tool(target, was_active)
	var out = { "tool": name, "layer": after, "was": before, "requested": want }
	if after != want:
		out["applied"] = false
		out["note"] = "Dungeondraft did not accept layer %d; it kept %d" % [want, after]
	else:
		out["applied"] = true
	return _ok(out)

func _layer_index(layer : int) -> int:
	# The patch appends its Above Lights layer after 900, as the menu's 16th.
	if layer == PATCH_ABOVE_LIGHTS_LAYER:
		return int((LAYER_MAX - LAYER_MIN) / LAYER_STEP) + 1
	return int((layer - LAYER_MIN) / LAYER_STEP)

func _layers_supported() -> Array:
	var names := []
	for name in Global.Editor.Tools.keys():
		if _layer_tool(str(name)) != null:
			names.append(str(name))
	names.sort()
	return names

func _select_tool(req : Dictionary) -> Dictionary:
	var name = str(req.get("tool", ""))
	if name == "":
		return _err("'tool' is required; call list_tool_controls to see the names")
	if not Global.Editor.Tools.has(name):
		return _err("no tool named '%s'" % name)
	if not Global.Editor.has_method("OnSelectTool"):
		return _err("this build exposes no Editor.OnSelectTool")
	var before = Global.Editor.ActiveToolName

	Global.Editor.OnSelectTool(name)
	var after = Global.Editor.ActiveToolName
	return _ok({ "tool": str(after), "was": str(before),
		"applied": str(after) == name })

func _list_tool_controls(req : Dictionary) -> Dictionary:
	var tname = str(req.get("tool", ""))
	if not Global.Editor.Tools.has(tname):
		return _err("unknown tool: " + tname)
	var tool = Global.Editor.Tools[tname]
	var controls = tool.get("Controls")
	if controls == null:
		return _ok({ "tool": tname, "controls": [], "note": "tool exposes no Controls dictionary" })
	var out := []
	for key in controls.keys():
		var c = controls[key]
		var cls = "?"
		if c != null and c.has_method("get_class"):
			cls = str(c.get_class())
		var entry = str(key) + " : " + cls
		# Option-like controls are useless without knowing their valid values —
		# guessing an item name ("Square" for GridStyle) simply fails.
		if c != null and c.has_method("get_item_count") and c.has_method("get_item_text"):
			var items := []
			var n = c.get_item_count()
			for i in range(min(n, 40)):
				items.append(str(c.get_item_text(i)))
			entry += " = [" + PoolStringArray(items).join(", ") + "]"
			if n > 40:
				entry += " (+" + str(n - 40) + " more)"
		out.append(entry)
	out.sort()
	return _ok({ "tool": tname, "controls": out })

const DD_SCRIPT_HEADER := "var Global = {}\nvar Script=null\n\n"
var _bridge_sha := ""

func _bridge_sha256() -> String:
	if _bridge_sha != "":
		return _bridge_sha
	var script = get_script()
	if script == null or not script.has_method("get_source_code"):
		return ""
	var src = str(script.get_source_code())
	if not src.begins_with(DD_SCRIPT_HEADER):
		return ""
	# Carriage returns are dropped on both sides, so a CRLF checkout agrees.
	_bridge_sha = src.substr(DD_SCRIPT_HEADER.length()).replace("\r", "").sha256_text()
	return _bridge_sha

func _ok(result) -> Dictionary:
	return { "ok": true, "result": result }

func _err(msg) -> Dictionary:
	return { "ok": false, "error": msg }

const SNAP_DEFAULT_LABELS := ["Place exactly where asked", "Snap to my grid"]
const SNAP_DEFAULT_VALUES := ["none", "auto"]

func _register_tool():
	# CreateButton loads its icon argument: "" logged "Error opening file ''"
	# once per button (Windows, 2026-09-24), so buttons reuse the panel icon,
	# as the Custom Snap Mod gives every button a real one.
	var icon = _panel_icon()
	var panel = Global.Editor.Toolset.CreateModTool(self, "Settings", "mcp_bridge", "Battlemap MCP Bridge", icon)
	if panel == null:
		return
	_panel = panel
	_panel_labels = {}
	_panel_controls = {}
	var settings = _read_settings()

	_panel_label(panel, "listening", "Listening on %s:%d" % [HOST, _port])
	_panel_label(panel, "bridge", "Bridge protocol %d, build %s" % [PROTOCOL_VERSION, _bridge_sha256().left(12)])
	_panel_label(panel, "last", "No requests yet")
	_panel_label(panel, "history", "")
	panel.CreateSeparator()

	var pause = panel.CreateCheckButton("Pause AI edits", "mcp_pause", _paused)
	if pause != null:
		pause.connect("toggled", self, "_on_panel_pause")
		_panel_controls["pause"] = pause
	var undo = panel.CreateButton("Undo the assistant's last step", icon)
	if undo != null:
		undo.connect("pressed", self, "_on_panel_undo")
	panel.CreateSeparator()

	var updates = panel.CreateCheckButton("Check for updates", "mcp_update_check",
		bool(settings.get("update_check", true)))
	if updates != null:
		updates.connect("toggled", self, "_on_panel_update_check")
	var chosen = SNAP_DEFAULT_VALUES.find(str(settings.get("snap_default", "none")))
	var snap = panel.CreateLabeledDropdownMenu("mcp_snap_default", "Placements",
		SNAP_DEFAULT_LABELS, SNAP_DEFAULT_LABELS[max(chosen, 0)])
	if snap != null:
		snap.connect("item_selected", self, "_on_panel_snap_default")
	var keep = int(settings.get("capture_retention", 20))
	_panel_label(panel, "captures", _captures_text(keep))
	var slider = panel.CreateSlider("mcp_capture_retention", float(keep), 0.0, 100.0, 1.0, false)
	if slider != null:
		slider.connect("value_changed", self, "_on_panel_captures")
	panel.CreateSeparator()

	var verbose = panel.CreateCheckButton("Verbose log", "mcp_verbose", _verbose)
	if verbose != null:
		verbose.connect("toggled", self, "_on_panel_verbose")
		_panel_controls["verbose"] = verbose
	var folder = panel.CreateButton("Open output folder", icon)
	if folder != null:
		folder.connect("pressed", self, "_on_panel_open_output")
	_panel_label(panel, "output", "")
	panel.CreateNote("These settings belong to you. Your assistant can read " +
		"them but cannot change them.")
	_refresh_panel()

func _panel_icon() -> String:
	var shipped = str(Global.get("Root", "")) + PANEL_ICON
	if File.new().file_exists(shipped):
		return shipped
	var path = "user://mcp_bridge.png"
	if not File.new().file_exists(path):
		var img = Image.new()
		img.create(32, 32, false, Image.FORMAT_RGBA8)
		img.fill(Color(0.96, 0.96, 0.96))
		img.save_png(path)
	return path

# CreateLabel returns nothing, so find the Label it just added by its text,
# within this panel only, to update it later.
func _panel_label(panel, key : String, text : String) -> void:
	var marker = "__mcp_%s__" % key
	panel.CreateLabel(marker)
	var found = _find_label(panel, marker, 0)
	if found != null:
		found.text = text
		_panel_labels[key] = found

func _find_label(node, text : String, depth : int):
	if depth > 6 or node == null:
		return null
	for child in node.get_children():
		if child is Label and child.text == text:
			return child
		var deeper = _find_label(child, text, depth + 1)
		if deeper != null:
			return deeper
	return null

func _set_panel_text(key : String, text : String) -> void:
	var label = _panel_labels.get(key)
	if label != null and is_instance_valid(label):
		label.text = text

func _note_request(cmd : String) -> void:
	if cmd == "" or cmd == "ping":
		return
	_last_request = "%s at %s" % [cmd, _clock()]
	_refresh_panel()

func _clock() -> String:
	var t = OS.get_time()
	return "%02d:%02d:%02d" % [t["hour"], t["minute"], t["second"]]

func _refresh_panel() -> void:
	if _panel == null:
		return
	_set_panel_text("last", "Last request: " + (_last_request if _last_request != "" else "none yet"))
	_set_panel_text("history", "Assistant history: %d of %d steps" % [_undo_stack.size(), MAX_UNDO_OPS])
	var verbose = _panel_controls.get("verbose")
	if verbose != null and is_instance_valid(verbose) and verbose.pressed != _verbose:
		verbose.set_pressed_no_signal(_verbose)

func _captures_text(keep : int) -> String:
	return "Keep the last %d screenshots and exports" % keep

func _settings_path() -> String:
	var base = _state_directory()
	return base.plus_file(SETTINGS_FILE) if base != "" else ""

func _read_settings() -> Dictionary:
	var path = _settings_path()
	var f = File.new()
	if path == "" or not f.file_exists(path) or f.open(path, File.READ) != OK:
		return {}
	var parsed = JSON.parse(f.get_as_text())
	f.close()
	if parsed.error != OK or typeof(parsed.result) != TYPE_DICTIONARY:
		return {}
	return parsed.result

# Only the _on_panel_* handlers call this; check_engine_guards enforces it.
func _panel_write_setting(key : String, value) -> void:
	var settings = _read_settings()
	settings[key] = value
	var path = _settings_path()
	var f = File.new()
	if path == "" or f.open(path, File.WRITE) != OK:
		print("[mcp-bridge] could not write %s" % path)
		return
	f.store_line(JSON.print(settings, "\t"))
	f.close()

func _on_panel_pause(pressed : bool) -> void:
	_paused = pressed
	print("[mcp-bridge] AI edits %s from the panel" % ("paused" if pressed else "resumed"))

func _on_panel_undo() -> void:
	if _saving() or _export_running():
		_set_panel_text("last", "Cannot undo while Dungeondraft is saving or exporting")
		return
	var result = _do_undo()
	if result.get("ok", false) and result["result"].get("undone", false):
		_set_panel_text("last", "Undid the assistant's %s at %s" % [result["result"]["kind"], _clock()])
	elif result.get("ok", false):
		_set_panel_text("last", "Nothing of the assistant's to undo")
	else:
		_set_panel_text("last", "Could not undo: " + str(result.get("error", "")))
	_set_panel_text("history", "Assistant history: %d of %d steps" % [_undo_stack.size(), MAX_UNDO_OPS])

func _on_panel_update_check(pressed : bool) -> void:
	_panel_write_setting("update_check", pressed)

func _on_panel_snap_default(index : int) -> void:
	if index >= 0 and index < SNAP_DEFAULT_VALUES.size():
		_panel_write_setting("snap_default", SNAP_DEFAULT_VALUES[index])

func _on_panel_captures(value : float) -> void:
	_set_panel_text("captures", _captures_text(int(value)))
	_panel_write_setting("capture_retention", int(value))

func _on_panel_verbose(pressed : bool) -> void:
	_verbose = pressed

func _on_panel_open_output() -> void:
	var folder = _state_directory().plus_file(OUTPUT_SUBDIR)
	if folder == "":
		return
	Directory.new().make_dir_recursive(folder)

	if OS.get_name() == "OSX":
		OS.execute("/usr/bin/open", [folder], false)
	elif OS.get_name() == "Windows":
		OS.shell_open(folder)
	else:
		_open_folder_unix(folder)

func _open_folder_unix(folder : String) -> void:
	var found = []
	OS.execute("/bin/sh", ["-c", "command -v xdg-open || command -v wslpath || true"], true, found)
	var opener = str(found[0]).strip_edges() if found.size() > 0 else ""
	if opener.ends_with("/xdg-open"):
		OS.execute(opener, [folder], false)
	elif opener.ends_with("/wslpath"):
		OS.execute("/bin/sh", ["-c", "explorer.exe \"$(wslpath -w \"$1\")\"", "sh", folder], false)
	elif _panel_labels.has("output"):
		_panel_labels["output"].text = "No file manager found. Captures are in: " + folder

# A create/group record can age out while a later merge still owns its detached
# wall. Keep that node alive until the merge itself leaves history.
func _held_by_wall_merge(node, excluding) -> bool:
	for op in _undo_stack + _redo_stack:
		if op != excluding and op.get("kind") == "wall_merge" and op.get("absorbed") == node:
			return true
	return false

func _wall_merge_history_error(op, undoing : bool) -> String:
	if op.get("kind") != "wall_merge": return ""
	var level = Global.World.GetCurrentLevel()
	if level == null or int(level.ID) != int(op.level):
		return "switch to the original level before undoing/redoing this wall merge"
	if not is_instance_valid(op.survivor) or not is_instance_valid(op.absorbed):
		return "wall merge history references a wall that no longer exists"
	if Global.World.GetNodeByID(int(op.id)) != op.survivor:
		return "wall merge survivor no longer resolves; history was not changed"
	for entry in op.portals:
		if not is_instance_valid(entry.node) or Global.World.GetNodeByID(int(entry.id)) != entry.node:
			return "wall merge portal no longer resolves; history was not changed"
	if not undoing and Global.World.GetNodeByID(int(op.absorbed_id)) != op.absorbed:
		return "wall merge source no longer resolves; history was not changed"
	return ""

func _merge_walls(req : Dictionary) -> Dictionary:
	var ids = req.get("ids")
	if typeof(ids) != TYPE_ARRAY or ids.size() != 2:
		return _err("ids must contain exactly two distinct wall IDs")
	for value in ids:
		if (typeof(value) != TYPE_INT and typeof(value) != TYPE_REAL) or is_nan(float(value)) or is_inf(float(value)) or float(value) != float(int(value)) or float(value) < 0:
			return _err("wall IDs must be nonnegative integers")
	if int(ids[0]) == int(ids[1]): return _err("ids must contain two distinct walls")
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var walls := []
	for value in ids:
		var wall = Global.World.GetNodeByID(int(value))
		if wall == null or wall.get_parent() != level.Walls or not wall.has_method("InsertPortal"):
			return _err("each ID must identify a wall on the current level")
		if not (int(wall.Type) in [0, 1]) or wall.Loop:
			return _err("merge supports open automatic/manual walls, not loops or cave walls")
		if wall.position != Vector2() or wall.rotation != 0 or wall.scale != Vector2(1, 1):
			return _err("merge requires wall geometry baked into its points")
		if wall.Points.size() < 2 or wall.Points.size() > 512:
			return _err("each wall must have 2..512 points")
		walls.append(wall)
	var first = walls[0]
	var second = walls[1]
	for property in ["Type", "Joint", "Color", "HasShadow", "NormalizeUV", "z_index", "modulate", "self_modulate"]:
		if first.get(property) != second.get(property):
			return _err("wall styles differ: " + property)
	for property in ["Texture", "EndTexture"]:
		var atex = first.get(property)
		var btex = second.get(property)
		if atex != btex and (atex == null or btex == null or atex.resource_path == "" or atex.resource_path != btex.resource_path):
			return _err("wall styles differ: " + property)
	var a = Array(first.Points)
	var b = Array(second.Points)
	var matches := 0
	var ai := -1
	var bi := -1
	for i in [0, a.size() - 1]:
		for j in [0, b.size() - 1]:
			if a[i].distance_to(b[j]) <= 0.01:
				matches += 1
				ai = i
				bi = j
	if matches != 1: return _err("walls must share exactly one endpoint; T-junctions and loops are unsupported")
	# Preserve the first wall's direction, including when the second is prepended.
	var joined := []
	if ai == a.size() - 1:
		if bi != 0: b.invert()
		joined = a.duplicate()
		for i in range(1, b.size()): joined.append(b[i])
	else:
		if bi == 0: b.invert()
		joined = b.duplicate()
		joined.pop_back()
		joined += a
	if not _simple_wall_run(joined):
		return _err("merged run would overlap, cross itself, or contain degenerate segments")
	var entries := []
	for wall in walls:
		for portal in wall.Portals:
			var anchor = _merge_portal_anchor(joined, portal.position)
			if anchor < 0: return _err("a mounted portal does not lie on the merged run")

			entries.append({ "node": portal, "id": _id(portal), "wall": wall,
				"wall_id": int(portal.WallID), "index": int(portal.WallPointIndex),
				"distance": float(portal.WallDistance), "new_index": anchor,
				"new_distance": anchor + portal.position.distance_to(joined[anchor]) / joined[anchor].distance_to(joined[anchor + 1]) })
	for i in range(entries.size()):
		for j in range(i + 1, entries.size()):
			if abs(entries[i].new_distance - entries[j].new_distance) < 0.00001:
				return _err("two portals occupy the same merged anchor; move one before merging")
	var op = { "kind": "wall_merge", "level": int(level.ID), "id": int(ids[0]),
		"survivor": first, "absorbed": second, "absorbed_id": int(ids[1]),
		"parent": second.get_parent(), "before": PoolVector2Array(first.Points),
		"after": PoolVector2Array(joined), "portals": entries }
	_apply_wall_merge(op, false)
	_push_undo(op)
	var portal_ids := []
	for entry in entries: portal_ids.append(entry.id)
	return _ok({ "id": int(ids[0]), "removed_ids": [int(ids[1])],
		"portal_ids": portal_ids, "point_count": joined.size() })

func _merge_portal_anchor(points, position) -> int:
	for i in range(points.size() - 1):
		if _closest_point_on_segment(position, points[i], points[i + 1]).distance_to(position) <= 0.01:
			return i
	return -1

func _simple_wall_run(points) -> bool:
	for point in points:
		if is_nan(point.x) or is_inf(point.x) or is_nan(point.y) or is_inf(point.y): return false
	for i in range(points.size() - 1):
		var a = points[i]
		var b = points[i + 1]
		if a.distance_to(b) <= 0.01: return false
		for j in range(i + 1, points.size() - 1):
			var c = points[j]
			var d = points[j + 1]
			if j == i + 1:
				# Adjacent straight segments are fine; doubling back is not.
				if abs((b-a).normalized().cross((d-c).normalized())) < 0.00001 and (b-a).dot(d-c) < 0: return false
				continue
			if Geometry.segment_intersects_segment_2d(a, b, c, d) != null: return false
			if _closest_point_on_segment(c, a, b).distance_to(c) <= 0.01 or _closest_point_on_segment(d, a, b).distance_to(d) <= 0.01 or _closest_point_on_segment(a, c, d).distance_to(a) <= 0.01: return false
	return true

func _apply_wall_merge(op, undoing : bool):
	var survivor = op.survivor

	for entry in op.portals:
		entry.node.get_parent().remove_child(entry.node)
	if undoing: _attach_node(op.absorbed, op.parent, int(op.absorbed_id), false)
	survivor.Points = op.before if undoing else op.after
	for entry in op.portals:
		var portal = entry.node
		var destination = entry.wall if undoing else survivor
		portal.WallID = int(entry.wall_id) if undoing else int(op.id)
		portal.WallPointIndex = int(entry.index) if undoing else int(entry.new_index)
		portal.WallDistance = entry.distance if undoing else entry.new_distance
		# InsertPortal adds membership and defers parenting; do not add twice.
		destination.InsertPortal(portal, true)
		Global.World.SetNodeID(portal, int(entry.id))
	# Native portal insertion rebuilds its destination. Only refresh walls
	# without portals explicitly; a duplicate rebuild corrupts pending children.
	if survivor.Portals.empty(): survivor.RemakeLines()
	if undoing and op.absorbed.Portals.empty(): op.absorbed.call_deferred("RemakeLines")
	if not undoing: _detach_node(op.absorbed, int(op.absorbed_id))
