#!/usr/bin/env python3
"""Validate Dudley Brewfile declarations against Homebrew metadata and assets."""

from __future__ import annotations

import argparse
import concurrent.futures
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BREW_DIR = ROOT / "system_files"
DECLARATION = re.compile(
    r'^\s*(?P<kind>tap|brew|cask)\s+"(?P<token>[^"]+)"(?:\s*(?:#.*)?)?$'
)
VERSION = re.compile(r'\bversion\s+"([^"]+)"')
URL = re.compile(r'\burl\s+"((?:#\{[^}]*\}|[^"])*)"')
SHA256 = re.compile(r"\bsha256\b")
INTERPOLATION = re.compile(r"#\{([^}]+)\}")
TERNARY = re.compile(
    r"^\(\s*(?P<key>[a-z][\w.]*)\s*==\s*"
    r"(?P<comparison>:[A-Za-z]\w*|['\"][^'\"]+['\"])\s*\)\s*\?\s*"
    r"(?P<true>['\"][^'\"]*['\"])\s*:\s*"
    r"(?P<false>['\"][^'\"]*['\"])$"
)
PLACEHOLDER = re.compile(r"\b(?:TODO|FIXME|placeholder|example)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Declaration:
    kind: str
    token: str
    path: Path
    line: int


@dataclass(frozen=True)
class Metadata:
    declaration: Declaration
    source_url: str
    source: str


def parse_brewfiles() -> tuple[list[Declaration], list[str]]:
    declarations: list[Declaration] = []
    errors: list[str] = []

    for path in sorted(BREW_DIR.glob("**/*.Brewfile")):
        seen: set[tuple[str, str]] = set()
        for line_number, raw_line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            match = DECLARATION.match(raw_line)
            if not match:
                if re.match(r"^\s*(?:tap|brew|cask)\b", raw_line):
                    errors.append(f"{path}:{line_number}: invalid declaration syntax")
                continue

            declaration = Declaration(
                match.group("kind"), match.group("token"), path, line_number
            )
            key = (declaration.kind, declaration.token)
            if key in seen:
                errors.append(
                    f"{path}:{line_number}: duplicate {declaration.kind} "
                    f"{declaration.token!r}"
                )
            seen.add(key)
            if PLACEHOLDER.search(declaration.token):
                errors.append(
                    f"{path}:{line_number}: placeholder token {declaration.token!r}"
                )
            declarations.append(declaration)

    taps = {
        declaration.token
        for declaration in declarations
        if declaration.kind == "tap"
    }
    referenced_taps = set()
    for declaration in declarations:
        if declaration.kind == "tap":
            continue
        try:
            tap, _ = split_token(declaration.token)
        except ValueError as exc:
            errors.append(
                f"{declaration.path}:{declaration.line}: {declaration.token!r}: {exc}"
            )
            continue
        if tap is not None:
            referenced_taps.add(tap)
            if tap not in taps:
                errors.append(
                    f"{declaration.path}:{declaration.line}: {declaration.token!r} "
                    f"uses undeclared tap {tap!r}"
                )
    for tap in sorted(taps - referenced_taps):
        errors.append(f"tap {tap!r} has no formula or cask declarations")

    return declarations, errors


def tap_repository(tap: str) -> tuple[str, str]:
    owner, name = tap.split("/", 1)
    repository = {
        "tap": "homebrew-tap",
        "tools": "homebrew-tools",
        "experimental-tap": "homebrew-experimental-tap",
        "bbrew": "homebrew-bbrew",
    }.get(name, f"homebrew-{name}")
    return owner, repository


def split_token(token: str) -> tuple[str | None, str]:
    parts = token.split("/")
    if len(parts) == 1:
        return None, token
    if len(parts) < 3:
        raise ValueError("expected owner/tap/name")
    return "/".join(parts[:2]), "/".join(parts[2:])


def metadata_candidates(declaration: Declaration) -> list[str]:
    tap, name = split_token(declaration.token)
    if tap is None:
        owner, repository = (
            ("Homebrew", "homebrew-core")
            if declaration.kind == "brew"
            else ("Homebrew", "homebrew-cask")
        )
        prefix = "Formula" if declaration.kind == "brew" else "Casks"
        return [
            f"https://raw.githubusercontent.com/{owner}/{repository}/HEAD/"
            f"{prefix}/{name[0]}/{name}.rb",
            f"https://raw.githubusercontent.com/{owner}/{repository}/HEAD/"
            f"{prefix}/{name}.rb",
        ]

    owner, repository = tap_repository(tap)
    prefix = "Formula" if declaration.kind == "brew" else "Casks"
    candidates = []
    for branch in ("main", "master"):
        candidates.extend(
            [
                f"https://raw.githubusercontent.com/{owner}/{repository}/{branch}/"
                f"{prefix}/{name[0]}/{name}.rb",
                f"https://raw.githubusercontent.com/{owner}/{repository}/{branch}/"
                f"{prefix}/{name}.rb",
                f"https://raw.githubusercontent.com/{owner}/{repository}/{branch}/"
                f"{name}.rb",
            ]
        )
    return candidates


def validate_tap(tap: str, *, timeout: float) -> str | None:
    # Each tap is also required by at least one formula or cask declaration.
    # Those metadata fetches below validate the tap without relying on the
    # rate-limited GitHub API.
    if "/" not in tap:
        return f"invalid tap name {tap!r}"
    return None


def fetch(url: str, *, timeout: float, method: str = "GET") -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "dsb-common-brewfile-validator/1"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_metadata(
    declaration: Declaration, *, timeout: float
) -> tuple[Metadata | None, str | None]:
    try:
        candidates = metadata_candidates(declaration)
    except ValueError as exc:
        return None, (
            f"{declaration.path}:{declaration.line}: {declaration.token!r}: {exc}"
        )

    for url in candidates:
        try:
            source = fetch(url, timeout=timeout)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            continue
        if declaration.kind == "brew" and "class " not in source:
            continue
        if declaration.kind == "cask" and "cask " not in source:
            continue
        return Metadata(declaration, url, source), None

    return None, (
        f"{declaration.path}:{declaration.line}: no Homebrew metadata for "
        f"{declaration.kind} {declaration.token!r}"
    )


def interpolation_values(source: str) -> dict[str, str]:
    version_match = VERSION.search(source)
    version = version_match.group(1) if version_match else ""
    parts = version.split(".")
    values = {
        "version": version,
        "version.major": parts[0] if parts else "",
        "version.minor": parts[1] if len(parts) > 1 else "",
        "version.patch": parts[2] if len(parts) > 2 else "",
        "os": "linux",
        "arch": "x64",
    }
    arch_match = re.search(r'\bintel:\s*"([^"]+)"', source)
    if arch_match:
        values["arch"] = arch_match.group(1)
    os_match = re.search(r'\blinux:\s*"([^"]+)"', source)
    if os_match:
        values["os"] = os_match.group(1)
    if len(parts) >= 2:
        values["version.csv.first"] = parts[0]
        values["version.csv.second"] = parts[1]
    return values


def resolved_urls(source: str) -> list[str]:
    values = interpolation_values(source)
    urls = []
    for match in URL.finditer(source):
        url = match.group(1)
        for expression in INTERPOLATION.findall(url):
            value = values.get(expression, "")
            ternary = TERNARY.match(expression)
            if ternary:
                comparison = ternary.group("comparison").strip(":'\"")
                branch = (
                    "true"
                    if values.get(ternary.group("key")) == comparison
                    else "false"
                )
                value = ternary.group(branch).strip("'\"")
            if not value:
                url = ""
                break
            url = url.replace(f"#{{{expression}}}", value)
        if url:
            urls.append(url)
    return urls


def validate_source(metadata: Metadata) -> list[str]:
    declaration = metadata.declaration
    errors: list[str] = []
    source = metadata.source

    if declaration.kind == "cask":
        if (
            "on_linux" not in source
            and "on arch: :linux" not in source
            and not re.search(r"\bos\s+[^\n]*linux:", source)
            and not declaration.token.endswith("-linux")
        ):
            errors.append(
                f"{declaration.path}:{declaration.line}: {declaration.token!r} "
                "does not declare a Linux cask branch"
            )
        if not VERSION.search(source):
            errors.append(
                f"{declaration.path}:{declaration.line}: {declaration.token!r} "
                "has no pinned cask version"
            )
        if not SHA256.search(source) or (
            ":no_check" not in source
            and not re.search(r'"[0-9a-fA-F]{64}"', source)
        ):
            errors.append(
                f"{declaration.path}:{declaration.line}: {declaration.token!r} "
                "has no checksum declaration"
            )

    if not resolved_urls(source):
        errors.append(
            f"{declaration.path}:{declaration.line}: {declaration.token!r} "
            "has no resolvable source URL"
        )

    return errors


def validate_artifact(metadata: Metadata, *, timeout: float) -> str | None:
    declaration = metadata.declaration
    urls = resolved_urls(metadata.source)
    failures = []
    for url in urls:
        try:
            fetch(url, timeout=timeout, method="HEAD")
            return None
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "Range": "bytes=0-0",
                        "User-Agent": "dsb-common-brewfile-validator/1",
                    },
                )
                with urllib.request.urlopen(request, timeout=timeout):
                    return None
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
                failures.append(f"{url} ({exc})")

    return (
        f"{declaration.path}:{declaration.line}: no published Linux artifact for "
        f"{declaration.token!r}: {'; '.join(failures)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--network",
        action="store_true",
        help="fetch Homebrew tap metadata instead of only checking declarations",
    )
    parser.add_argument(
        "--artifacts",
        action="store_true",
        help="also check that a resolved source artifact is published",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    declarations, errors = parse_brewfiles()
    if not declarations:
        errors.append(f"no Brewfile declarations found below {BREW_DIR}")

    if args.artifacts and not args.network:
        errors.append("--artifacts requires --network")

    if not args.network:
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 1
        print(f"Validated {len(declarations)} Brewfile declarations syntactically.")
        return 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        taps = sorted(
            {
                declaration.token
                for declaration in declarations
                if declaration.kind == "tap"
            }
        )
        tap_errors = pool.map(
            lambda tap: validate_tap(tap, timeout=args.timeout), taps
        )
        errors.extend(error for error in tap_errors if error)

    network_declarations = [
        declaration for declaration in declarations if declaration.kind != "tap"
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        metadata_results = list(
            pool.map(
                lambda declaration: fetch_metadata(
                    declaration, timeout=args.timeout
                ),
                network_declarations,
            )
        )

    metadata: list[Metadata] = []
    for result, error in metadata_results:
        if error:
            errors.append(error)
        elif result:
            errors.extend(validate_source(result))
            metadata.append(result)

    if args.artifacts:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            artifact_errors = pool.map(
                lambda item: validate_artifact(item, timeout=args.timeout), metadata
            )
            errors.extend(error for error in artifact_errors if error)

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    mode = "metadata and artifacts" if args.artifacts else "metadata"
    print(f"Validated {len(declarations)} Brewfile declarations against {mode}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
