"""check_gdscript catches format-precedence mistakes that only fail at runtime."""

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_gdscript", Path(__file__).resolve().parents[1] / "tools" / "check_gdscript.py"
)
assert _SPEC and _SPEC.loader
check_gdscript = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_gdscript)


def _format_problems(src: str) -> list[str]:
    return [p for p in check_gdscript.check(src) if "last string" in p]


def test_unparenthesised_concatenation_before_format_is_flagged():
    src = 'func f(a, b):\n\treturn ("x %d " +\n\t\t"y %s" % [a, b])\n'
    assert len(_format_problems(src)) == 1


def test_parenthesised_concatenation_is_accepted():
    src = 'func f(a, b):\n\treturn (("x %d " +\n\t\t"y %s") % [a, b])\n'
    assert _format_problems(src) == []


def test_single_literal_format_is_accepted():
    src = 'func f(a):\n\treturn "x %d" % [a]\n'
    assert _format_problems(src) == []
