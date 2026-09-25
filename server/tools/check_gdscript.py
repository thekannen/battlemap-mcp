#!/usr/bin/env python3
"""Check bridge source for common GDScript syntax and consistency errors.

Run this offline check before starting Dungeondraft with an edited bridge."""

from __future__ import annotations

import pathlib
import re
import sys

KEYWORDS = {
    "return",
    "if",
    "elif",
    "else",
    "for",
    "while",
    "match",
    "pass",
    "break",
    "continue",
    "var",
    "const",
    "func",
    "yield",
    "assert",
    "print",
    "and",
    "or",
    "not",
    "in",
    "is",
    "as",
    "self",
    "null",
    "true",
    "false",
}

# GDScript's own reserved words, as its tokenizer sees them. A local `var tool`
# happens to parse (this mod has several), but a PARAMETER named `tool` is a hard
# parse error — "The identifier "tool" isn't declared in the current scope" —
# which takes down Dungeondraft's entire mod subsystem for the session. That
# asymmetry is exactly why it is easy to write: the same word is fine one line
# up. Checked on parameters only, because that is the form that actually fails.
RESERVED = {
    "and",
    "as",
    "assert",
    "break",
    "breakpoint",
    "case",
    "class",
    "class_name",
    "const",
    "continue",
    "do",
    "elif",
    "else",
    "enum",
    "export",
    "extends",
    "false",
    "for",
    "func",
    "if",
    "in",
    "is",
    "master",
    "mastersync",
    "match",
    "not",
    "null",
    "onready",
    "or",
    "pass",
    "preload",
    "puppet",
    "puppetsync",
    "remote",
    "remotesync",
    "return",
    "self",
    "setget",
    "signal",
    "slave",
    "static",
    "switch",
    "sync",
    "tool",
    "true",
    "var",
    "void",
    "while",
    "yield",
}

ROOT = pathlib.Path(__file__).resolve().parents[2]
MOD = ROOT / "mod/battlemap-mcp-bridge/scripts/tools/mcp_bridge.gd"
# Every .gd file in the mod is parsed by Dungeondraft at launch, and a failure in
# any one of them takes the whole mod down — not just that script. So they all
# get checked, not only the bridge.
MOD_DIR = ROOT / "mod/battlemap-mcp-bridge/scripts"


def check(src: str) -> list[str]:
    problems: list[str] = []
    lines = src.splitlines()

    defined = set(re.findall(r"^func\s+(\w+)", src, re.M))

    # A redefined function is a parse error that kills the whole mod at load:
    # "The function X already exists in this class". GDScript has no overloading,
    # and a real GDScript parser will not catch it either — it is a semantic
    # error, not a syntax one. This file is ~3600 lines with many small helpers,
    # so adding a helper whose name is already taken is easy and costs a full
    # Dungeondraft restart to discover.
    seen: dict[str, int] = {}
    for n, line in enumerate(lines, 1):
        m = re.match(r"^func\s+(\w+)", line)
        if not m:
            continue
        if m.group(1) in seen:
            problems.append(
                f"{MOD.name}:{n}: func {m.group(1)}() is already defined at line "
                f"{seen[m.group(1)]} — the mod will not load"
            )
        else:
            seen[m.group(1)] = n
    # Bare calls to snake_case names are script-local functions. Anything after
    # a dot is a method on some object and is a runtime concern, not a parse one.
    for n, line in enumerate(lines, 1):
        code = line.split("#", 1)[0]
        for name in re.findall(r"(?<![\w.\"'])(_[a-z]\w*)\s*\(", code):
            if name not in defined:
                problems.append(f"{MOD.name}:{n}: calls undefined function {name}()")

    # GDScript re-declaration is a parse error — "Variable X already defined in
    # the scope" — and it kills the whole mod at load. A real GDScript parser
    # does not catch it (semantic, not syntactic), and it is easy to hit when
    # adding a guard to the top of a long handler that declares the same name
    # further down.
    #
    # Scope is per BLOCK, not per function: `var peer` inside a `while` and
    # again inside a later `for` is legal, because the first left scope when its
    # block ended. So track active declarations with their indent and drop any
    # deeper than the current line before checking.
    fn_name = None
    active: list[tuple[int, str, int]] = []  # (indent, name, line_no)
    for n, raw in enumerate(lines, 1):
        code = raw.split("#", 1)[0]
        if not code.strip():
            continue
        fm = re.match(r"^func\s+(\w+)", code)
        if fm:
            fn_name, active = fm.group(1), []
            continue
        if fn_name is None:
            continue
        indent = len(code) - len(code.lstrip("\t "))
        active = [d for d in active if d[0] <= indent]
        vm = re.match(r"[\t ]+var\s+(\w+)", code)
        if not vm:
            continue
        var = vm.group(1)
        prior = next((d for d in active if d[1] == var), None)
        if prior:
            problems.append(
                f"{MOD.name}:{n}: var {var} is already in scope from line "
                f"{prior[2]} in {fn_name}() — GDScript rejects this at parse "
                f"time and the mod will not load"
            )
        else:
            active.append((indent, var, n))

    # Dispatch entries must have a handler behind them.
    for n, line in enumerate(lines, 1):
        m = re.match(r'\s*"([\w]+)":\s*return\s+(\w+)\(', line)
        if m and m.group(2) not in defined:
            problems.append(
                f"{MOD.name}:{n}: command '{m.group(1)}' dispatches to undefined {m.group(2)}()"
            )

    # Locals used before they are declared. This is what actually took the mod
    # down: an edit anchored on the wrong function inserted `out["modulate"]`
    # into a function whose local was named `s`, and Godot refused to load the
    # whole script with "The identifier \"out\" isn't declared in the current
    # scope." The undefined-function check above did not see it.
    class_names: set[str] = set(re.findall(r"^(?:var|const|onready var)\s+(\w+)", src, re.M))
    func_bounds: list[tuple[int, int, str]] = []
    starts = [
        (m.start(), m.group(1), m.group(2))
        for m in re.finditer(r"^func\s+(\w+)\(([^)]*)\)", src, re.M)
    ]
    for k, (pos, _name, params) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(src)
        func_bounds.append((pos, end, params))

    for pos, end, params in func_bounds:
        body = src[pos:end]
        first_line = src[:pos].count("\n") + 1
        # Every parameter, typed or not: `func f(op)` declares `op` as surely
        # as `func f(op : Dictionary)`. Only the typed form used to count.
        declared = {
            m.group(1) for part in params.split(",") if (m := re.match(r"\s*(\w+)", part))
        } | {"self"}
        for offset, line in enumerate(body.splitlines()):
            code = line.split("#", 1)[0]
            for d in re.findall(r"^\s*var\s+(\w+)", code):
                declared.add(d)
            for d in re.findall(r"\bfor\s+(\w+)\s+in\b", code):
                declared.add(d)
            # subscript-assignment targets are the reliable signal: `name[...] =`
            for used in re.findall(r"^\s*(\w+)\s*\[", code):
                if used in KEYWORDS or used in declared or used in class_names:
                    continue
                if not used[0].isupper():
                    problems.append(
                        f"{MOD.name}:{first_line + offset}: '{used}' used before it is "
                        f"declared in this function"
                    )

    # A reserved word as a parameter name is a parse error; see RESERVED.
    for n, line in enumerate(lines, 1):
        m = re.match(r"^func\s+\w+\s*\((.*)\)", line)
        if not m:
            continue
        for param in m.group(1).split(","):
            pname = param.strip().split(":")[0].split("=")[0].strip()
            if pname in RESERVED:
                problems.append(
                    f"{MOD.name}:{n}: parameter named '{pname}' is a GDScript "
                    f"reserved word — the script will not parse"
                )

    depth = 0
    for n, line in enumerate(lines, 1):
        code = line.split("#", 1)[0]
        # Strip string literals so brackets and operators inside them do not count.
        code = re.sub(r'"(?:[^"\\]|\\.)*"', '""', code)
        # Brackets opened on THIS line count before the end-of-line test: the
        # common correct form opens its bracket and wraps in the same line.
        depth += code.count("(") + code.count("[")
        depth -= code.count(")") + code.count("]")
        depth = max(depth, 0)
        stripped = code.rstrip()
        if depth == 0 and stripped.endswith(("+", "-", "*", "/", "%", "&&", "||")):
            problems.append(
                f"{MOD.name}:{n}: line ends with an operator outside any ( or [ "
                f"— GDScript will not continue it onto the next line, and a {{ "
                f"does not count. Wrap the expression in parentheses."
            )

    # `%` binds tighter than `+`, so in `"a %d " + "b %s" % [x, y]` the format
    # applies to the LAST literal alone. That parses, then raises "not all
    # arguments converted" when the line runs — and error messages are exactly
    # the lines that only run once something has already gone wrong.
    for m in re.finditer(r'\+\s*"(?:[^"\\]|\\.)*"\s*%\s*[\[A-Za-z_]', src):
        n = src.count("\n", 0, m.start()) + 1
        problems.append(
            f"{MOD.name}:{n}: `%` formats only the last string of a `+` "
            f"concatenation. Parenthesise the whole concatenation before `%`."
        )

    # Mixed indentation inside one line breaks Godot's parser.
    for n, line in enumerate(lines, 1):
        indent = line[: len(line) - len(line.lstrip())]
        if " " in indent and "\t" in indent:
            problems.append(f"{MOD.name}:{n}: mixed tab/space indentation")

    return problems


def main() -> int:
    if not MOD.exists():
        print(f"mod not found at {MOD}", file=sys.stderr)
        return 2
    scripts = sorted(MOD_DIR.rglob("*.gd"))
    problems: list[str] = []
    for script in scripts:
        for problem in check(script.read_text(encoding="utf-8")):
            problems.append(problem.replace(MOD.name, script.name, 1))
    for p in problems:
        print(p)
    if problems:
        print(f"\n{len(problems)} problem(s) — the mod would fail to load.")
        return 1
    print(
        f"{len(scripts)} script(s): no undefined calls, no reserved-word "
        f"parameters, no function or "
        f"variable redefinitions, "
        f"dispatch entries resolve, no dangling line continuations, "
        f"indentation consistent"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
