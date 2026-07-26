"""Curated, ownership-safe adapters for Dudley-themed applications."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from dudley_theme.model import ResourceRecord

from .base import Adapter, AdapterResult, AdapterStatus, ThemeContext
from .files import (
    FileResource,
    LineResource,
    capture_file,
    capture_line,
    expected_managed_line,
    expected_managed_link,
    restore_file,
    restore_line,
    write_managed_file,
    write_managed_line,
    write_managed_link,
)


@dataclass(frozen=True)
class JsoncResource:
    path: Path
    key_path: tuple[str, ...]
    existed: bool
    value: Any = None
    raw_value: str | None = None
    missing_parents: tuple[tuple[str, ...], ...] = ()

    @property
    def fingerprint(self) -> str:
        if not self.existed:
            return "absent"
        return json.dumps(self.value, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class _Member:
    key: str
    key_start: int
    value_start: int
    value_end: int
    comma_start: int | None
    comma_end: int | None


def _skip_trivia(text: str, index: int) -> int:
    while index < len(text):
        if text[index].isspace():
            index += 1
        elif text.startswith("//", index):
            newline = text.find("\n", index + 2)
            index = len(text) if newline < 0 else newline + 1
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                raise ValueError("unterminated JSONC block comment")
            index = end + 2
        else:
            break
    return index


def _string_end(text: str, start: int) -> int:
    index = start + 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text[index] == '"':
            return index + 1
        else:
            index += 1
    raise ValueError("unterminated JSONC string")


def _matching_close(text: str, start: int) -> int:
    pairs = {"{": "}", "[": "]"}
    if start >= len(text) or text[start] not in pairs:
        raise ValueError("JSONC collection expected")
    stack = [pairs[text[start]]]
    index = start + 1
    while index < len(text):
        if text[index] == '"':
            index = _string_end(text, index)
        elif text.startswith("//", index) or text.startswith("/*", index):
            index = _skip_trivia(text, index)
        elif text[index] in pairs:
            stack.append(pairs[text[index]])
            index += 1
        elif text[index] == stack[-1]:
            stack.pop()
            if not stack:
                return index
            index += 1
        else:
            index += 1
    raise ValueError("unterminated JSONC collection")


def _value_end(text: str, start: int) -> int:
    if text[start] == '"':
        return _string_end(text, start)
    if text[start] in "[{":
        return _matching_close(text, start) + 1
    index = start
    while index < len(text) and text[index] not in ",}":
        if text.startswith("//", index) or text.startswith("/*", index):
            break
        index += 1
    return index


def _members(text: str, start: int) -> tuple[int, dict[str, _Member]]:
    close = _matching_close(text, start)
    result: dict[str, _Member] = {}
    index = _skip_trivia(text, start + 1)
    while index < close:
        key_start = index
        if text[index] != '"':
            raise ValueError("JSONC object keys must be quoted")
        key_end = _string_end(text, index)
        key = json.loads(text[index:key_end])
        index = _skip_trivia(text, key_end)
        if index >= close or text[index] != ":":
            raise ValueError(f"missing colon after JSONC key {key!r}")
        value_start = _skip_trivia(text, index + 1)
        value_end = _value_end(text, value_start)
        index = _skip_trivia(text, value_end)
        comma_start: int | None = None
        comma_end: int | None = None
        if index < close and text[index] == ",":
            comma_start = index
            comma_end = index + 1
            index = _skip_trivia(text, comma_end)
        elif index < close:
            raise ValueError(f"missing comma after JSONC key {key!r}")
        result[key] = _Member(
            key=key,
            key_start=key_start,
            value_start=value_start,
            value_end=value_end,
            comma_start=comma_start,
            comma_end=comma_end,
        )
    return close, result


def _root_start(text: str) -> int:
    root = _skip_trivia(text, 0)
    if root >= len(text) or text[root] != "{":
        raise ValueError("settings file must contain a JSONC object")
    return root


def _decode_value(raw: str) -> Any:
    output: list[str] = []
    index = 0
    in_string = False
    while index < len(raw):
        if in_string:
            output.append(raw[index])
            if raw[index] == "\\" and index + 1 < len(raw):
                index += 1
                output.append(raw[index])
            elif raw[index] == '"':
                in_string = False
            index += 1
        elif raw[index] == '"':
            in_string = True
            output.append(raw[index])
            index += 1
        elif raw.startswith("//", index):
            newline = raw.find("\n", index + 2)
            index = len(raw) if newline < 0 else newline
        elif raw.startswith("/*", index):
            end = raw.find("*/", index + 2)
            if end < 0:
                raise ValueError("unterminated JSONC block comment")
            index = end + 2
        else:
            output.append(raw[index])
            index += 1
    cleaned = "".join(output)
    cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
    return json.loads(cleaned)


def _locate(
    text: str, key_path: tuple[str, ...]
) -> tuple[_Member | None, tuple[tuple[str, ...], ...]]:
    object_start = _root_start(text)
    traversed: list[str] = []
    missing: list[tuple[str, ...]] = []
    for index, key in enumerate(key_path):
        _, members = _members(text, object_start)
        member = members.get(key)
        traversed.append(key)
        if member is None:
            missing.extend(
                tuple(key_path[:parent_end])
                for parent_end in range(index + 1, len(key_path))
            )
            return None, tuple(missing)
        if index == len(key_path) - 1:
            return member, tuple(missing)
        if text[member.value_start] != "{":
            raise ValueError(f"JSONC key {'.'.join(traversed)} is not an object")
        object_start = member.value_start
    raise ValueError("JSONC key path must not be empty")


def capture_jsonc_value(path: Path, key_path: tuple[str, ...]) -> JsoncResource:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    member, missing_parents = _locate(text, key_path)
    if member is None:
        return JsoncResource(
            path=path,
            key_path=key_path,
            existed=False,
            missing_parents=missing_parents,
        )
    raw = text[member.value_start : member.value_end]
    return JsoncResource(
        path=path,
        key_path=key_path,
        existed=True,
        value=_decode_value(raw),
        raw_value=raw,
    )


def _formatted(value: Any, continuation_indent: str) -> str:
    rendered = json.dumps(value, indent=2)
    return rendered.replace("\n", "\n" + continuation_indent)


def _insert_member(text: str, start: int, key: str, raw_value: str) -> str:
    close, existing = _members(text, start)
    if existing:
        last = max(existing.values(), key=lambda member: member.value_end)
        if last.comma_start is None:
            text = text[: last.value_end] + "," + text[last.value_end :]
            close += 1
    close_line_start = text.rfind("\n", 0, close) + 1
    close_indent = text[close_line_start:close]
    prefix = ""
    if close_indent.strip():
        close_line_start = close
        close_indent = ""
        prefix = "\n"
    child_indent = close_indent + "  "
    block = (
        prefix
        + child_indent
        + json.dumps(key)
        + ": "
        + raw_value.replace("\n", "\n" + child_indent)
        + "\n"
    )
    return text[:close_line_start] + block + text[close_line_start:]


def _set_path_raw(
    text: str, key_path: tuple[str, ...], raw_value: str, start: int | None = None
) -> str:
    object_start = _root_start(text) if start is None else start
    _, members = _members(text, object_start)
    key = key_path[0]
    member = members.get(key)
    if len(key_path) == 1:
        if member is None:
            return _insert_member(text, object_start, key, raw_value)
        return text[: member.value_start] + raw_value + text[member.value_end :]
    if member is None:
        rendered = raw_value
        for nested_key in reversed(key_path[1:]):
            indented = rendered.replace("\n", "\n  ")
            rendered = f"{{\n  {json.dumps(nested_key)}: {indented}\n}}"
        return _insert_member(text, object_start, key, rendered)
    if text[member.value_start] != "{":
        raise ValueError(f"JSONC key {key!r} is not an object")
    return _set_path_raw(text, key_path[1:], raw_value, member.value_start)


def _delete_path(text: str, key_path: tuple[str, ...], start: int | None = None) -> str:
    object_start = _root_start(text) if start is None else start
    _, members = _members(text, object_start)
    member = members.get(key_path[0])
    if member is None:
        return text
    if len(key_path) > 1:
        if text[member.value_start] != "{":
            return text
        return _delete_path(text, key_path[1:], member.value_start)
    if member.comma_end is not None:
        return text[: member.key_start] + text[member.comma_end :]
    previous = [
        candidate
        for candidate in members.values()
        if candidate.value_end < member.key_start
    ]
    start_remove = member.key_start
    if previous:
        prior = max(previous, key=lambda candidate: candidate.value_end)
        if prior.comma_start is not None:
            start_remove = prior.comma_start
    return text[:start_remove] + text[member.value_end :]


def _object_is_empty(text: str, key_path: tuple[str, ...]) -> bool:
    member, _ = _locate(text, key_path)
    if member is None or text[member.value_start] != "{":
        return False
    _, members = _members(text, member.value_start)
    return not members


def _write_jsonc(path: Path, text: str) -> None:
    captured = capture_file(path)
    if captured.state != "file":
        raise ValueError(f"JSONC resource must be a regular file: {path}")
    write_managed_file(
        path,
        text.encode("utf-8"),
        mode=captured.mode if captured.mode is not None else 0o644,
    )


def write_jsonc_value(record: JsoncResource, value: Any) -> JsoncResource:
    current = capture_jsonc_value(record.path, record.key_path)
    if current.fingerprint != record.fingerprint:
        raise RuntimeError(
            f"JSONC resource changed after capture: {record.path} "
            f"{'.'.join(record.key_path)}"
        )
    text = record.path.read_text(encoding="utf-8")
    member, _ = _locate(text, record.key_path)
    value_start = member.value_start if member is not None else _root_start(text)
    line_start = text.rfind("\n", 0, value_start) + 1
    line = text[line_start:value_start]
    indent = line[: len(line) - len(line.lstrip())]
    raw = _formatted(value, indent)
    _write_jsonc(record.path, _set_path_raw(text, record.key_path, raw))
    return capture_jsonc_value(record.path, record.key_path)


def restore_jsonc_value(
    record: JsoncResource, *, expected: JsoncResource
) -> AdapterResult:
    current = capture_jsonc_value(record.path, record.key_path)
    if current.fingerprint == record.fingerprint:
        return AdapterResult("unchanged")
    if current.fingerprint != expected.fingerprint:
        return AdapterResult(
            "conflicted",
            (f"{record.path}:{'.'.join(record.key_path)}",),
        )
    text = record.path.read_text(encoding="utf-8")
    if record.existed:
        if record.raw_value is None:
            raise ValueError("captured JSONC value has no source token")
        text = _set_path_raw(text, record.key_path, record.raw_value)
    else:
        text = _delete_path(text, record.key_path)
        for parent in reversed(record.missing_parents):
            if _object_is_empty(text, parent):
                text = _delete_path(text, parent)
    _write_jsonc(record.path, text)
    return AdapterResult("restored")


def _aggregate(action: str, results: Iterable[AdapterResult]) -> AdapterResult:
    result_list = list(results)
    conflicts = tuple(
        detail
        for result in result_list
        if result.status == "conflicted"
        for detail in result.details
    )
    if conflicts:
        return AdapterResult("conflicted", conflicts)
    if any(result.status == action for result in result_list):
        return AdapterResult(action)
    return AdapterResult("unchanged")


class LinkedThemeAdapter(Adapter):
    name = ""
    target_key = ""
    link_path = Path()
    include_path: Path | None = None
    include_line: bytes | None = None

    def _target(self, context: ThemeContext) -> str:
        value = context.values.get(
            self.target_key, context.values.get(f"{self.target_key}_target")
        )
        if value is None:
            raise ValueError(f"missing theme target: {self.target_key}")
        return str(value)

    def capture(self, context: ThemeContext) -> list[ResourceRecord]:
        link_path = context.home / self.link_path
        target = self._target(context)
        records = [
            ResourceRecord(
                adapter=self.name,
                resource=f"link:{link_path}",
                before=capture_file(link_path),
                applied=expected_managed_link(link_path, target),
            )
        ]
        if self.include_path is not None and self.include_line is not None:
            line = capture_line(context.home / self.include_path, self.include_line)
            records.append(
                ResourceRecord(
                    adapter=self.name,
                    resource=f"line:{line.path}",
                    before=line,
                    applied=expected_managed_line(line),
                )
            )
        return records

    def apply(
        self, context: ThemeContext, records: list[ResourceRecord]
    ) -> AdapterResult:
        del context
        conflicts: list[str] = []
        for record in records:
            if isinstance(record.before, FileResource):
                current = capture_file(record.before.path)
                if current.fingerprint not in {
                    record.before.fingerprint,
                    record.applied.fingerprint,
                }:
                    conflicts.append(str(record.before.path))
            elif isinstance(record.before, LineResource):
                current = capture_file(record.before.path)
                if current.fingerprint not in {
                    record.before.before.fingerprint,
                    record.applied.fingerprint,
                }:
                    conflicts.append(str(record.before.path))
        if conflicts:
            return AdapterResult("conflicted", tuple(conflicts))
        for record in records:
            if isinstance(record.before, FileResource):
                current = capture_file(record.before.path)
                if current.fingerprint != record.applied.fingerprint:
                    write_managed_link(record.before.path, record.applied.link_target)
            elif isinstance(record.before, LineResource):
                current = capture_file(record.before.path)
                if current.fingerprint != record.applied.fingerprint:
                    write_managed_line(record.before)
        return AdapterResult("applied")

    def verify(self, context: ThemeContext) -> AdapterStatus:
        expected = self.capture(context)
        drift = [
            record.resource
            for record in expected
            if (
                capture_file(
                    record.before.path
                    if isinstance(record.before, FileResource)
                    else record.before.path
                ).fingerprint
                != record.applied.fingerprint
            )
        ]
        return (
            AdapterStatus("drifted", tuple(drift))
            if drift
            else AdapterStatus("verified")
        )

    def restore(
        self, context: ThemeContext, records: list[ResourceRecord]
    ) -> AdapterResult:
        del context
        results: list[AdapterResult] = []
        for record in records:
            if isinstance(record.before, FileResource):
                results.append(restore_file(record.before, expected=record.applied))
            elif isinstance(record.before, LineResource):
                results.append(restore_line(record.before, expected=record.applied))
        return _aggregate("restored", results)


class KittyAdapter(LinkedThemeAdapter):
    name = "kitty"
    target_key = "kitty"
    link_path = Path(".config/kitty/dudley-theme.conf")
    include_path = Path(".config/kitty/kitty.conf")
    include_line = b"include dudley-theme.conf"


class GhosttyAdapter(LinkedThemeAdapter):
    name = "ghostty"
    target_key = "ghostty"
    link_path = Path(".config/ghostty/themes/dudley-theme")
    include_path = Path(".config/ghostty/config")
    include_line = b"theme = dudley-theme"


class NeovimAdapter(LinkedThemeAdapter):
    name = "neovim"
    target_key = "neovim"
    link_path = Path(".config/nvim/plugin/dudley-theme.lua")


class BtopAdapter(LinkedThemeAdapter):
    name = "btop"
    target_key = "btop"
    link_path = Path(".config/btop/themes/dudley-theme.theme")
    include_path = Path(".config/btop/btop.conf")
    include_line = b'color_theme = "dudley-theme"'


def _flatten_values(
    values: Mapping[str, Any], prefix: tuple[str, ...] = ()
) -> Iterable[tuple[tuple[str, ...], Any]]:
    for key, value in values.items():
        path = prefix + (key,)
        if isinstance(value, Mapping):
            yield from _flatten_values(value, path)
        else:
            yield path, value


class VSCodeAdapter(Adapter):
    name = "vscode"
    settings_paths = (
        Path(".config/Code/User/settings.json"),
        Path(".config/Code - Insiders/User/settings.json"),
    )

    def _values(self, context: ThemeContext) -> Mapping[str, Any]:
        values = context.values.get("vscode")
        if not isinstance(values, Mapping):
            raise ValueError("missing VS Code settings mapping")
        return values

    def capture(self, context: ThemeContext) -> list[ResourceRecord]:
        changes = tuple(_flatten_values(self._values(context)))
        records: list[ResourceRecord] = []
        for relative_path in self.settings_paths:
            path = context.home / relative_path
            if not path.is_file():
                continue
            for key_path, value in changes:
                before = capture_jsonc_value(path, key_path)
                applied = JsoncResource(
                    path=path,
                    key_path=key_path,
                    existed=True,
                    value=value,
                    raw_value=json.dumps(value),
                )
                records.append(
                    ResourceRecord(
                        adapter=self.name,
                        resource=f"jsonc:{path}:{'.'.join(key_path)}",
                        before=before,
                        applied=applied,
                    )
                )
        return records

    def apply(
        self, context: ThemeContext, records: list[ResourceRecord]
    ) -> AdapterResult:
        del context
        conflicts = [
            record.resource
            for record in records
            if capture_jsonc_value(
                record.before.path, record.before.key_path
            ).fingerprint
            not in {record.before.fingerprint, record.applied.fingerprint}
        ]
        if conflicts:
            return AdapterResult("conflicted", tuple(conflicts))
        for record in records:
            current = capture_jsonc_value(record.before.path, record.before.key_path)
            if current.fingerprint != record.applied.fingerprint:
                write_jsonc_value(record.before, record.applied.value)
        return AdapterResult("applied")

    def verify(self, context: ThemeContext) -> AdapterStatus:
        records = self.capture(context)
        drift = [
            record.resource
            for record in records
            if capture_jsonc_value(
                record.before.path, record.before.key_path
            ).fingerprint
            != record.applied.fingerprint
        ]
        return (
            AdapterStatus("drifted", tuple(drift))
            if drift
            else AdapterStatus("verified")
        )

    def restore(
        self, context: ThemeContext, records: list[ResourceRecord]
    ) -> AdapterResult:
        del context
        return _aggregate(
            "restored",
            (
                restore_jsonc_value(record.before, expected=record.applied)
                for record in records
            ),
        )


CURATED_APP_ADAPTERS = (
    KittyAdapter,
    GhosttyAdapter,
    NeovimAdapter,
    BtopAdapter,
    VSCodeAdapter,
)
