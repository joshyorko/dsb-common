# Dudley Wellness Floor Theme Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the experimental app-theme script with a reversible GNOME-native Wellness Floor platform, integrate its image-owned requirements into Dudley OS, and publish both feature branches with verified payload and product contracts.

**Architecture:** A Python transaction engine in `dsb-common` renders immutable theme generations, applies explicit adapters, records exact before/applied state, and restores only unchanged managed values. `dudley-os` installs the system requirements, supplies pristine-user policy and static boot/login branding, pins the published payload digest, and owns booted-image acceptance.

**Tech Stack:** Python 3 standard library, TOML/JSON, POSIX shell launchers, GNOME `gsettings`/`dconf`/`gnome-extensions`, GTK/GNOME Shell CSS, Just, unittest, shellcheck, bootc/Podman, Flatpak.

## Global Constraints

- Keep final OS assembly, packages, GDM, Plymouth, bootc metadata, and VM acceptance out of `dsb-common`.
- Keep reusable theme data, runtime commands, user hooks, adapters, and state under `system_files/dudley/`.
- Do not import assets from `OldJobobo/omarchy-lumon-theme`.
- Preserve MIT attribution for copied Omarchy material.
- Use the original Dudley Wellness Floor identity and existing Dudley-owned wallpapers only.
- `off` must preserve external user edits and return a conflict instead of overwriting them.
- A disabled user must remain disabled across hooks and image upgrades.
- Do not claim exact arbitrary libadwaita recoloring.
- Do not push directly to `dudley-os` `main`; work from a feature branch based on `origin/main`.
- Commit only task files with conventional commit messages.

---

### Task 1: Transaction model and durable store

**Files:**
- Create: `system_files/dudley/usr/lib/dudley_theme/__init__.py`
- Create: `system_files/dudley/usr/lib/dudley_theme/model.py`
- Create: `system_files/dudley/usr/lib/dudley_theme/state.py`
- Test: `tests/test_theme_state.py`

**Interfaces:**
- Produces: `ThemeState`, `ResourceRecord`, `TransactionRecord`, `StateStore`, and `StateConflict`.
- `StateStore(root: Path)` owns `preferences.json`, `baseline/`, `generations/`, `transactions/`, `current`, and `previous`.
- `StateStore.commit_generation(generation_id: str) -> None` atomically replaces current/previous references.
- `StateStore.recover_pointer() -> str | None` repairs only an unambiguous committed pointer.

- [ ] **Step 1: Write failing state-store tests**

```python
def test_commit_moves_current_to_previous(tmp_path):
    store = StateStore(tmp_path)
    store.create_generation("a", {"state": "ACTIVE"})
    store.commit_generation("a")
    store.create_generation("b", {"state": "ACTIVE"})
    store.commit_generation("b")
    assert store.current_id() == "b"
    assert store.previous_id() == "a"

def test_newer_schema_is_read_only(tmp_path):
    (tmp_path / "preferences.json").write_text('{"schema_version": 999}')
    assert StateStore(tmp_path).read_only is True
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `python3 -m unittest tests.test_theme_state -v`

Expected: import failure because `dudley_theme.state` does not exist.

- [ ] **Step 3: Implement typed records and atomic JSON/reference writes**

Use frozen dataclasses for immutable records, `os.replace` for files, `fsync`
before pointer replacement, and reject path traversal outside `generations/`.

- [ ] **Step 4: Prove pointer corruption and schema behavior**

Run: `python3 -m unittest tests.test_theme_state -v`

Expected: all state-store tests pass.

- [ ] **Step 5: Commit**

```bash
git add system_files/dudley/usr/lib/dudley_theme tests/test_theme_state.py
git commit -m "feat(theme): add transactional state store"
```

### Task 2: Catalog, palette, renderer, and provenance

**Files:**
- Create: `system_files/dudley/usr/lib/dudley_theme/catalog.py`
- Create: `system_files/dudley/usr/lib/dudley_theme/render.py`
- Rename: `system_files/dudley/usr/share/dudley/themes/wellness-floor/palette.toml` to `colors.toml`
- Create: `system_files/dudley/usr/share/dudley/themes/wellness-floor/provenance.json`
- Modify: `system_files/dudley/usr/share/dudley/themes/wellness-floor/manifest.json`
- Test: `tests/test_wellness_floor_theme.py`

**Interfaces:**
- `load_theme(path: Path) -> ThemeManifest`
- `discover_themes(path: Path) -> dict[str, ThemeManifest]`
- `render_theme(theme: ThemeManifest, destination: Path) -> RenderResult`
- `RenderResult.hashes: dict[str, str]` contains SHA-256 for every output.

- [ ] **Step 1: Update tests for the schema-v2 catalog**

```python
def test_catalog_requires_colors_and_provenance(self):
    self.assertEqual(2, self.manifest["schema_version"])
    self.assertEqual("colors.toml", self.manifest["colors"])
    self.assertTrue((THEME / "provenance.json").is_file())
```

- [ ] **Step 2: Verify the old catalog fails**

Run: `python3 -m unittest tests.test_wellness_floor_theme -v`

Expected: failures for schema version, `colors.toml`, and provenance.

- [ ] **Step 3: Implement strict catalog validation and deterministic rendering**

Reject missing files, duplicate `palette.toml`/`colors.toml`, unknown required
adapter IDs, unresolved `{{ token }}` placeholders, and assets without a
provenance record.

- [ ] **Step 4: Normalize the Wellness Floor catalog**

Populate provenance with the three existing wallpaper hashes and embedded
generation metadata, mark locally authored configuration files as project
work, and record Omarchy MIT palette inspiration without importing its art.

- [ ] **Step 5: Run catalog and payload tests**

Run:

```bash
python3 -m unittest tests.test_wellness_floor_theme tests.test_payload_contract -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add system_files/dudley/usr/lib/dudley_theme system_files/dudley/usr/share/dudley/themes/wellness-floor tests
git commit -m "feat(theme): add validated Wellness Floor catalog"
```

### Task 3: Conflict-aware resource adapters

**Files:**
- Create: `system_files/dudley/usr/lib/dudley_theme/adapters/__init__.py`
- Create: `system_files/dudley/usr/lib/dudley_theme/adapters/base.py`
- Create: `system_files/dudley/usr/lib/dudley_theme/adapters/files.py`
- Create: `system_files/dudley/usr/lib/dudley_theme/adapters/gsettings.py`
- Create: `system_files/dudley/usr/lib/dudley_theme/adapters/apps.py`
- Test: `tests/test_theme_adapters.py`

**Interfaces:**
- `Adapter.capture(context: ThemeContext) -> list[ResourceRecord]`
- `Adapter.apply(context: ThemeContext, records: list[ResourceRecord]) -> AdapterResult`
- `Adapter.verify(context: ThemeContext) -> AdapterStatus`
- `Adapter.restore(context: ThemeContext, records: list[ResourceRecord]) -> AdapterResult`
- `FileResource` records absent/file/symlink state, bytes, mode, and link target.
- `SettingResource` records schema, key, typed value, and whether it was unset.

- [ ] **Step 1: Write failing exact-restore tests**

```python
def test_restore_preserves_user_edit(tmp_path):
    target = tmp_path / "settings"
    target.write_text("before")
    record = capture_file(target)
    write_managed_file(target, b"applied")
    target.write_text("user edit")
    result = restore_file(record, expected=b"applied")
    assert result.status == "conflicted"
    assert target.read_text() == "user edit"
```

- [ ] **Step 2: Verify tests fail**

Run: `python3 -m unittest tests.test_theme_adapters -v`

- [ ] **Step 3: Implement generic file, link, line, and typed-setting resources**

Never replace a resource before capture. Restore only when its current
fingerprint equals the Dudley-applied fingerprint.

- [ ] **Step 4: Implement curated app adapters**

Cover Kitty, Ghostty, Neovim, btop, and VS Code Stable/Insiders native paths.
Use ownership-safe includes/links and a JSONC token-preserving editor. Record
every overwritten VS Code key and restore it independently.

- [ ] **Step 5: Prove JSONC, pre-existing include, symlink, and conflict cases**

Run: `python3 -m unittest tests.test_theme_adapters -v`

Expected: all adapter tests pass.

- [ ] **Step 6: Commit**

```bash
git add system_files/dudley/usr/lib/dudley_theme/adapters tests/test_theme_adapters.py
git commit -m "feat(theme): add reversible theme adapters"
```

### Task 4: Engine, locking, recovery, and CLI

**Files:**
- Create: `system_files/dudley/usr/lib/dudley_theme/engine.py`
- Create: `system_files/dudley/usr/lib/dudley_theme/cli.py`
- Create: `system_files/dudley/usr/lib/dudley_theme/compat.py`
- Replace: `system_files/dudley/usr/bin/dudley-theme`
- Test: `tests/test_theme_engine.py`
- Test: `tests/test_theme_migration.py`

**Interfaces:**
- `ThemeEngine.on() -> Result`
- `ThemeEngine.off() -> Result`
- `ThemeEngine.set(theme_id: str) -> Result`
- `ThemeEngine.undo() -> Result`
- `ThemeEngine.status() -> StatusReport`
- `ThemeEngine.repair(adopt_current_baseline: bool = False) -> Result`
- Exit `0` for verified success, `2` for usage, `3` for conflict/read-only, and
  `4` for rolled-back adapter failure.

- [ ] **Step 1: Write failing transaction tests**

Cover apply, switch, undo, off, disabled persistence, concurrent mutation,
failure after every adapter, crash-journal recovery, corrupted pointers, and
legacy experimental state.

- [ ] **Step 2: Verify tests fail**

Run:

```bash
python3 -m unittest tests.test_theme_engine tests.test_theme_migration -v
```

- [ ] **Step 3: Implement the serialized transaction lifecycle**

Acquire the safe per-user lock, render candidate, preflight, capture, journal,
apply, verify, commit, and reverse-restore on failure.

- [ ] **Step 4: Implement the command surface and compatibility aliases**

Support `on`, `off`, `list`, `set`, `undo`, `status [--json]`, and `repair
[--adopt-current-baseline]`. Route `apply` to `set`, `current` to `status`, and
`reset` to `off` with deprecation messages.

- [ ] **Step 5: Run engine and legacy tests**

Run:

```bash
python3 -m unittest tests.test_theme_engine tests.test_theme_migration -v
```

Expected: all tests pass and injected failures leave no false active receipt.

- [ ] **Step 6: Commit**

```bash
git add system_files/dudley/usr/bin/dudley-theme system_files/dudley/usr/lib/dudley_theme tests
git commit -m "feat(theme): add transactional theme engine"
```

### Task 5: GNOME Shell, GTK, wallpaper, icons, and cursor surfaces

**Files:**
- Create: `system_files/dudley/usr/share/dudley/themes/wellness-floor/templates/gnome-shell.css`
- Create: `system_files/dudley/usr/share/dudley/themes/wellness-floor/templates/gtk-3.0.css`
- Create: `system_files/dudley/usr/lib/dudley_theme/adapters/gnome.py`
- Modify: `system_files/dudley/usr/share/dudley/themes/wellness-floor/manifest.json`
- Modify: `system_files/dudley/usr/share/dudley/themes/wellness-floor/provenance.json`
- Test: `tests/test_theme_gnome.py`

**Interfaces:**
- `GnomeAdapter` manages color scheme, accent, GTK theme, icon theme,
  cursor theme, User Themes extension state, Shell theme, desktop wallpaper,
  dark wallpaper, and lock/screen-saver wallpaper.
- The first qualified icon/cursor selections are the image-provided
  `Yaru-blue` and `Adwaita`, avoiding unlicensed bundled art.

- [ ] **Step 1: Write GNOME render and typed-setting tests**

Verify Shell CSS covers panel, overview, quick settings, notifications,
dialogs, OSD, workspace indicators, and lock shield selectors.

- [ ] **Step 2: Verify tests fail**

Run: `python3 -m unittest tests.test_theme_gnome -v`

- [ ] **Step 3: Add original palette-generated Shell and GTK3 CSS**

Use only semantic tokens from `colors.toml`; do not copy Omarchy Hyprland/QML
or third-party Lumon CSS.

- [ ] **Step 4: Implement GNOME capture/apply/verify/restore**

Use `gsettings get/set/reset`, `gnome-extensions enable/disable`, and the
User Themes extension schema. Preserve explicit/unset typed state.

- [ ] **Step 5: Run GNOME tests**

Run: `python3 -m unittest tests.test_theme_gnome -v`

- [ ] **Step 6: Commit**

```bash
git add system_files/dudley/usr/share/dudley/themes/wellness-floor system_files/dudley/usr/lib/dudley_theme/adapters/gnome.py tests/test_theme_gnome.py
git commit -m "feat(theme): add GNOME Wellness Floor surfaces"
```

### Task 6: Session initializer, ujust interface, and payload contract

**Files:**
- Modify: `system_files/dudley/usr/share/ublue-os/user-setup.hooks.d/25-dudley-theme.sh`
- Modify: `system_files/dudley/usr/share/ublue-os/just/60-dudley.just`
- Modify: `contract/dudley-payload.v1.json`
- Modify: `tests/test_payload_contract.py`
- Replace: `tests/test_wellness_floor_theme.py`

**Interfaces:**
- The hook calls `dudley-theme status --json` first and applies only when the
  account is pristine, policy says enabled, and state is `UNMANAGED`.
- `ujust dudley-theme <action> [theme]` passes through to the CLI.

- [ ] **Step 1: Write failing hook and contract tests**

Test pristine default, disabled skip, existing-user skip, missing policy skip,
and catalog-version reconciliation for an active user.

- [ ] **Step 2: Implement the non-enforcing hook and ujust wrapper**

Remove hook-version forcing. Read `/etc/dudley/theme-default` and
`/etc/dudley/theme-enrollment`; never override `DISABLED` or `CONFLICTED`.

- [ ] **Step 3: Regenerate the explicit payload inventory**

Declare every new Python module, template, provenance file, and test-relevant
runtime path.

- [ ] **Step 4: Run the complete `dsb-common` validation**

Run:

```bash
python3 -m unittest discover -s tests -v
git diff --check
shellcheck -x system_files/dudley/usr/bin/dudley-theme system_files/dudley/usr/share/ublue-os/user-setup.hooks.d/25-dudley-theme.sh
just --unstable --fmt --check -f system_files/dudley/usr/share/ublue-os/just/60-dudley.just
```

- [ ] **Step 5: Commit**

```bash
git add contract system_files/dudley tests
git commit -m "feat(theme): wire reversible Dudley theme controls"
```

### Task 7: `dudley-os` feature worktree and system requirements

**Files:**
- Create worktree: `../.worktrees/dudley-os-wellness-floor`
- Modify: `Containerfile`
- Modify: `build/10-build.sh`
- Create: `build/16-wellness-floor.sh`
- Create: `custom/system_files/etc/dudley/theme-default`
- Create: `custom/system_files/etc/dudley/theme-enrollment`
- Create: `tests/test-theme-platform-contract.sh`
- Modify: `Justfile`
- Modify: `README.md`

**Interfaces:**
- Worktree branch: `agent/wellness-floor-theme-platform`, based on
  `origin/main`.
- `16-wellness-floor.sh` installs
  `gnome-shell-extension-user-theme`, validates GNOME compatibility, compiles
  dconf/schemas, and validates the selected theme manifest.
- Initial product policy is `default-off` until VM acceptance passes.

- [ ] **Step 1: Create the isolated up-to-date worktree**

```bash
git -C ../dudley-os fetch origin
git -C ../dudley-os worktree add -b agent/wellness-floor-theme-platform ../.worktrees/dudley-os-wellness-floor origin/main
```

- [ ] **Step 2: Write the failing product contract test**

Assert package installation, manifest validation, policy files, build-script
wiring, and pinned `dsb-common` placeholders.

- [ ] **Step 3: Add the system requirement build step**

Use `dnf5 install -y gnome-shell-extension-user-theme`; do not layer packages
at runtime or from `ujust`.

- [ ] **Step 4: Add policy and documentation**

Document the direct and `ujust` commands, exact live/static boundary, and the
default-off canary state.

- [ ] **Step 5: Run product validation**

Run:

```bash
bash tests/test-theme-platform-contract.sh
shellcheck build/10-build.sh build/16-wellness-floor.sh tests/test-theme-platform-contract.sh
just --list
git diff --check
```

- [ ] **Step 6: Commit**

```bash
git add Containerfile Justfile README.md build custom tests
git commit -m "feat(theme): integrate Wellness Floor platform

Assisted-by: GPT-5 via Codex"
```

### Task 8: Static GDM and Plymouth branding

**Files:**
- Create: `custom/system_files/etc/dconf/profile/gdm`
- Create: `custom/system_files/etc/dconf/db/gdm.d/01-dudley-branding`
- Create: `custom/system_files/usr/share/plymouth/themes/dudley-wellness-floor/dudley-wellness-floor.plymouth`
- Create: `custom/system_files/usr/share/plymouth/themes/dudley-wellness-floor/dudley-wellness-floor.script`
- Copy original asset: `custom/system_files/usr/share/plymouth/themes/dudley-wellness-floor/background.png`
- Modify: `build/16-wellness-floor.sh`
- Modify: `tests/test-theme-platform-contract.sh`

**Interfaces:**
- GDM displays the supported banner text `Dudley OS · Wellness Floor`.
- Plymouth uses a Dudley-owned wallpaper with a centered progress indicator.
- These surfaces do not read or mutate per-user theme state.

- [ ] **Step 1: Extend the failing product contract**

Assert GDM dconf profile, banner, Plymouth descriptor/script/assets,
`plymouth-set-default-theme`, and initramfs validation wiring.

- [ ] **Step 2: Add supported GDM branding**

Enable the login-screen banner through the GDM dconf database; do not patch
GNOME Shell greeter CSS.

- [ ] **Step 3: Add and select the Plymouth script theme**

Install the descriptor, script, and original Dudley asset, run
`plymouth-set-default-theme dudley-wellness-floor`, and verify the effective
initramfs contains the theme.

- [ ] **Step 4: Run product tests and shellcheck**

Run the commands from Task 7 and assert no product file reaches
`dsb-common`.

- [ ] **Step 5: Commit**

```bash
git add build custom tests
git commit -m "feat(theme): add Dudley boot and login branding

Assisted-by: GPT-5 via Codex"
```

### Task 9: Cross-repository verification and publication

**Files:**
- Modify only generated test artifacts if explicitly tracked by the repos.

**Interfaces:**
- `dsb-common` publishes first.
- `dudley-os` consumes the immutable published digest, never an invented one.

- [ ] **Step 1: Run all local `dsb-common` checks**

Run the repository's AGENTS.md validation commands plus:

```bash
python3 -m unittest discover -s tests -v
git diff --check
```

- [ ] **Step 2: Push the `dsb-common` feature branch**

```bash
git push origin agent/wellness-floor-theme-pack
```

- [ ] **Step 3: Wait for PR checks and inspect the published PR image**

Use `ghx pr checks 82` and inspect the workflow result. Do not claim the
`:latest` main digest changed before merge.

- [ ] **Step 4: Update `dudley-os` with the real published or PR-test digest**

Replace both `dsb-common` `COPY --from` digests with the exact digest produced
by the verified workflow.

- [ ] **Step 5: Run all `dudley-os` local checks**

Run `just test-unit`, shellcheck on touched scripts, `just --list`, and
`git diff --check`.

- [ ] **Step 6: Push the `dudley-os` feature branch**

```bash
git push -u origin agent/wellness-floor-theme-platform
```

### Task 10: Image and VM acceptance

**Files:**
- Create: `tests/test-theme-vm.sh` if the existing VM harness lacks the
  required assertions.
- Modify: `.github/workflows/upgrade-test.yml` only if the existing workflow
  cannot run the acceptance script.

**Interfaces:**
- Candidate image is identified by immutable digest.
- Default enrollment remains off until all mandatory VM assertions pass.

- [ ] **Step 1: Build the candidate bootc image**

Run in the Dudley OS worktree:

```bash
just build
just build-qcow2
```

- [ ] **Step 2: Boot and test fresh/customized/multi-user paths**

Prove Plymouth, GDM, pristine initialization, `on`, `set`, `undo`, `off`,
conflict preservation, and second-user isolation.

- [ ] **Step 3: Run upgrade and rollback acceptance**

Prove active, disabled, and unmanaged states across candidate upgrade and
bootc rollback, including newer-schema read-only behavior.

- [ ] **Step 4: Capture release evidence**

Record image/payload digests, command output, before/after state hashes,
GNOME Shell errors, SELinux denials, and screenshots for Shell/GDM/Plymouth.

- [ ] **Step 5: Enable pristine-user default only after green acceptance**

Change `theme-enrollment` from `default-off` to `pristine-only`, rerun product
tests, commit with a conventional message and required `Assisted-by` footer,
and push the updated feature branch.
