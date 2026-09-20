#!/usr/bin/env python3
"""Check that Python tool request keys match their GDScript handlers.

Report unused request keys and required keys that callers can omit."""

from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
SERVER = ROOT / "server/battlemap_mcp/server.py"
MOD = ROOT / "mod/battlemap-mcp-bridge/scripts/tools/mcp_bridge.gd"

# Injected by BridgeClient.request, never by a tool.
IMPLICIT = {"cmd", "token"}


def sent_keys() -> dict[str, set[str]]:
    """cmd -> keys the Python side can send."""
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        # Which local dict is splatted into bridge.request(**...)? Only that one
        # holds params. Collecting every subscript assignment instead swept up
        # writes to the RESPONSE — `result["after"] = ...` — and reported them
        # as parameters the handler fails to read.
        splatted = {
            kw.value.id
            for node in ast.walk(fn)
            if isinstance(node, ast.Call)
            for kw in node.keywords
            if kw.arg is None and isinstance(kw.value, ast.Name)
        }

        # Keys accumulated into that params dict inside this function.
        bag: set[str] = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign):
                tgt = node.targets[0]
                if (
                    isinstance(tgt, ast.Name)
                    and tgt.id in splatted
                    and isinstance(node.value, ast.Dict)
                ):
                    bag |= {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
                elif (
                    isinstance(tgt, ast.Subscript)
                    and isinstance(tgt.value, ast.Name)
                    and tgt.value.id in splatted
                    and isinstance(tgt.slice, ast.Constant)
                ):
                    bag.add(tgt.slice.value)
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not (isinstance(f, ast.Attribute) and f.attr == "request"):
                continue
            if not (node.args and isinstance(node.args[0], ast.Constant)):
                continue
            cmd = node.args[0].value
            keys = {kw.arg for kw in node.keywords if kw.arg}
            if any(kw.arg is None for kw in node.keywords):
                keys |= bag
            out.setdefault(cmd, set()).update(keys)
    return out


def read_keys() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """cmd -> (all keys read, keys read unguarded via req["k"])."""
    src = MOD.read_text(encoding="utf-8")
    # Only the `match cmd:` block, so a `!= "yes":` guard followed by a return
    # on the next line cannot be mistaken for a dispatch entry.
    body = src.split("\tmatch cmd:\n", 1)[1]
    dispatch = dict(re.findall(r'\t\t"(\w+)":\s*return\s+(_\w+)\(', body))

    bodies: dict[str, str] = {}
    for block in re.split(r"\n(?=func )", src):
        m = re.match(r"func (_\w+)", block)
        if m:
            bodies[m.group(1)] = block

    def keys_in(handler: str, seen: set[str]) -> tuple[set[str], set[str]]:
        if handler in seen or handler not in bodies:
            return set(), set()
        seen.add(handler)
        body = bodies[handler]
        allk = set(re.findall(r'req(?:uest)?[\.\[]\s*"?(?:get\(")?(\w+)', body))
        allk |= set(re.findall(r'req\.(?:get|has)\("(\w+)"', body))
        hard = set(re.findall(r'req\["(\w+)"\]', body))
        guarded = set(re.findall(r'req\.has\("(\w+)"\)', body))
        guarded |= set(re.findall(r'req\.get\("(\w+)"', body))
        # Helpers that take req and read more keys out of it.
        for helper in re.findall(r"(_\w+)\(req[,)]", body):
            a, h = keys_in(helper, seen)
            allk |= a
            hard |= h
        return allk, hard - guarded

    read: dict[str, set[str]] = {}
    unguarded: dict[str, set[str]] = {}
    for cmd, handler in dispatch.items():
        a, h = keys_in(handler, set())
        read[cmd] = a
        unguarded[cmd] = h
    return read, unguarded


def main() -> int:
    sent = sent_keys()
    read, unguarded = read_keys()
    problems = []

    for cmd, keys in sorted(sent.items()):
        if cmd not in read:
            continue  # handler not found by the dispatch regex; check_gdscript covers this
        for k in sorted(keys - read[cmd] - IMPLICIT):
            problems.append(f"UNREAD  {cmd}.{k} — tool sends it, handler never reads it")
        for k in sorted(unguarded[cmd] - keys - IMPLICIT):
            problems.append(
                f'MISSING {cmd}.{k} — handler reads req["{k}"] unguarded, tool never sends it'
            )

    for cmd in sorted(set(read) - set(sent)):
        if cmd.startswith("debug_"):
            continue  # deliberately not exposed as tools; see the debug_ handlers
        problems.append(f"UNREACHABLE {cmd} — handler exists, no MCP tool calls it")

    for p in problems:
        print(p)
    if problems:
        print(f"\n{len(problems)} command-contract problem(s).")
        return 1
    print(
        f"command contract: {len(sent)} commands, every key sent is read and every "
        f"unguarded key is sent"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
