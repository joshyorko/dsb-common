"""Command-line interface for the Dudley theme transaction engine."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Sequence

from .compat import translate
from .engine import EXIT_USAGE, Result, StatusReport, ThemeEngine


USAGE = """Usage:
  dudley-theme on
  dudley-theme off
  dudley-theme list
  dudley-theme set <theme-id>
  dudley-theme undo
  dudley-theme status [--json]
  dudley-theme repair [--adopt-current-baseline]"""


def default_engine() -> ThemeEngine:
    home = Path.home()
    state_home = Path(os.environ.get("XDG_STATE_HOME", home / ".local/state"))
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    runtime_dir = Path(runtime) if runtime else Path(f"/run/user/{os.getuid()}")
    return ThemeEngine(
        state_root=state_home / "dudley/theme",
        runtime_dir=runtime_dir,
        home=home,
        catalog_root=Path(
            os.environ.get("DUDLEY_THEMES_DIR", "/usr/share/dudley/themes")
        ),
        default_theme=os.environ.get("DUDLEY_DEFAULT_THEME", "wellness-floor"),
    )


def main(
    argv: Sequence[str] | None = None, *, engine: ThemeEngine | None = None
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    compatibility = translate(arguments)
    arguments = list(compatibility.argv)
    if compatibility.warning:
        print(compatibility.warning, file=sys.stderr)
    if not arguments:
        return _usage()
    command, *options = arguments
    runtime = engine or default_engine()

    if command == "list" and not options:
        for theme_id, name in runtime.list_themes():
            print(f"{theme_id}\t{name}")
        return 0
    if command == "on" and not options:
        return _print_result(runtime.on())
    if command == "off" and not options:
        return _print_result(runtime.off())
    if command == "undo" and not options:
        return _print_result(runtime.undo())
    if command == "set" and len(options) == 1:
        return _print_result(runtime.set(options[0]))
    if command == "status" and options in ([], ["--json"]):
        return _print_status(runtime.status(), as_json=options == ["--json"])
    if command == "repair" and options in (
        [],
        ["--adopt-current-baseline"],
    ):
        return _print_result(
            runtime.repair(
                adopt_current_baseline=options == ["--adopt-current-baseline"]
            )
        )
    return _usage()


def _print_result(result: Result) -> int:
    output = sys.stdout if result.exit_code == 0 else sys.stderr
    print(result.message, file=output)
    for detail in result.details:
        print(f"- {detail}", file=output)
    return result.exit_code


def _print_status(report: StatusReport, *, as_json: bool) -> int:
    if as_json:
        print(json.dumps(report.to_dict(), sort_keys=True))
    else:
        theme = report.theme_id or "none"
        print(f"{report.state}\t{theme}")
        for adapter_id, status in sorted(report.surfaces.items()):
            print(f"{adapter_id}\t{status}")
        if report.message:
            print(report.message, file=sys.stderr)
    return 3 if report.state == "CONFLICTED" or report.read_only else 0


def _usage() -> int:
    print(USAGE, file=sys.stderr)
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
