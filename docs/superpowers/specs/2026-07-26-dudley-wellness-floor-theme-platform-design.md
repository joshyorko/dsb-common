# Dudley Wellness Floor Theme Platform

Date: 2026-07-26

Status: awaiting written-spec review

Implementation scope after approval: Subproject 1 only. The later subprojects
are architectural boundaries and acceptance dependencies; each receives its
own design review before its implementation plan.

## Goal

Build a GNOME-native, Omarchy-style theme platform for Dudley OS that gives a
new Dudley user a cohesive Wellness Floor desktop and lets each user turn that
experience on or off without losing their previous configuration.

The platform must:

- theme the supported logged-in GNOME surfaces and curated applications;
- switch themes through one obvious command;
- restore the exact pre-Dudley user state when disabled;
- preserve user edits made while a theme is active;
- survive login, image upgrades, and bootc rollback;
- report unsupported, drifted, pending-restart, and conflicted surfaces
  honestly;
- keep machine-wide boot branding separate from per-user live switching; and
- ship only assets with documented provenance and redistribution rights.

The user-facing identity is **Dudley Wellness Floor**. It may take inspiration
from the palette and architecture of Omarchy's MIT-licensed Lumon theme, but it
must not ship unlicensed third-party Lumon or television-show artwork, logos,
launcher assets, or text.

## Product decisions

The following decisions are fixed for the first implementation:

1. Dudley remains a Bluefin/GNOME product.
2. The live theme is per-user and reversible.
3. GDM and Plymouth use matching static Dudley branding owned by the booted
   image. They do not change when a user runs `dudley-theme off`.
4. GNOME Shell and curated applications can claim exact theme parity.
5. GTK4/libadwaita applications claim supported GNOME dark, accent, contrast,
   and accessibility integration, not arbitrary global recoloring.
6. Native and Flatpak GTK3 applications cannot claim exact parity until the
   named theme and matching Flatpak theme extension pass the VM acceptance
   matrix.
7. Fresh, pristine Dudley users receive the product default. Existing
   customized users are not enrolled by an upgrade.
8. An explicit user opt-out always wins over the image default.
9. The current default-on first-login hook and destructive `reset` behavior
   must not cross the release boundary.

## Two-plane architecture

### Per-user live plane

`dsb-common` owns reusable theme behavior:

- the catalog and manifest schema;
- the semantic palette and deterministic templates;
- GNOME Shell, GTK, wallpaper, icon, cursor, and application adapters;
- the transaction engine and state schema;
- exact capture, verification, rollback, conflict, and recovery behavior;
- the CLI and shared `ujust` entry point;
- a non-enforcing session initializer;
- asset provenance records; and
- unit, fault-injection, concurrency, and adapter tests.

### Image branding plane

`dudley-os` owns final product assembly:

- installation and pinning of the GNOME User Themes extension;
- required host packages and Flatpak theme extensions;
- the product default policy;
- GDM branding;
- Plymouth branding and initramfs inclusion;
- the exact `dsb-common` OCI digest;
- compatibility checks against the selected Bluefin and GNOME versions;
- image metadata, signing, and publication; and
- booted QCOW2 or installed-VM acceptance.

The final image must bind the Bluefin base digest, `dudley-os` revision,
`dsb-common` digest, theme catalog digest, supported state schema range, GNOME
Shell version, extension version, and GDM/Plymouth asset hashes.

## User interface

The direct interface is:

```text
dudley-theme on
dudley-theme off
dudley-theme list
dudley-theme set <theme-id>
dudley-theme undo
dudley-theme status [--json]
dudley-theme repair [--adopt-current-baseline]
```

The matching convenience interface is:

```text
ujust dudley-theme on
ujust dudley-theme off
ujust dudley-theme list
ujust dudley-theme set <theme-id>
ujust dudley-theme undo
ujust dudley-theme status
ujust dudley-theme repair
```

Command semantics:

- `on` activates the last selected theme. If there is no prior selection, it
  activates the product default.
- `off` restores the original unmanaged baseline and persists an opt-out. If
  external user changes make exact restoration unsafe, it preserves those
  changes, returns a conflict, and does not claim to be disabled.
- `list` reports the installed theme catalog.
- `set` transactionally switches to a selected managed theme.
- `undo` returns to the previous committed managed generation.
- `status` reports the transaction state and every selected surface
  independently.
- `repair` reconciles the active generation after verified drift. It does not
  overwrite a conflicting user edit. `--adopt-current-baseline` is limited to
  explicit recovery from the unrecoverable experimental state described below.

There is no generic `reset` command in the final interface. During the
experimental-branch transition, the old commands behave as compatibility
aliases for one development release:

| Experimental command | Transactional equivalent |
| --- | --- |
| `list` | catalog listing retained as `list` |
| `current` | `status` with the active theme emphasized |
| `apply <theme-id>` | `set <theme-id>` with a deprecation warning |
| `reset` | `off` with a deprecation warning |

The aliases execute through the same transaction authority. They must not
retain the old direct-mutation or schema-default behavior.

## Fidelity contract

| Surface | First-release contract |
| --- | --- |
| GNOME Shell | Exact Wellness Floor Shell theme using the User Themes extension |
| Desktop wallpaper | Exact, transactionally restored |
| Lock-screen wallpaper | Exact, transactionally restored |
| Icons | Licensed theme selection, transactionally restored |
| Cursors | Licensed theme selection, transactionally restored |
| GTK3 native | Exact after named-theme qualification |
| GTK3 Flatpak | Exact only with the matching qualified runtime extension |
| GTK4/libadwaita | GNOME-native dark, accent, contrast, and accessibility preferences |
| Kitty | Exact curated adapter |
| Ghostty | Exact curated adapter |
| Ptyxis/GNOME Console | Exact terminal palette where the installed version exposes a supported profile API |
| VS Code Stable/Insiders | Exact curated adapter for each explicitly qualified native or Flatpak installation |
| Neovim | Exact curated adapter without clearing unrelated user highlights globally |
| btop | Exact curated adapter |
| Browser chrome | System appearance in the first release; exact recoloring only after a per-profile adapter is qualified |
| GDM | Matching static image branding |
| Plymouth | Matching static image branding |

The GNOME Shell surface inventory includes the top bar, overview, app grid,
Quick Settings, notifications, dialogs, OSD, workspace indicators, and lock
shield. "Shell exact" is not satisfied by changing only the top bar.

High contrast, reduced motion, text scaling, and other accessibility settings
remain authoritative. The theme may adapt to them but may not disable them.
Fonts and sound themes are outside the first theme transaction so existing
accessibility and user choices remain unchanged.

## Theme catalog

Themes are installed under:

```text
/usr/share/dudley/themes/<theme-id>/
```

Each theme contains:

- `manifest.json`;
- `colors.toml`;
- deterministic templates;
- optional hand-authored surface overrides;
- wallpapers and other declared assets; and
- `provenance.json`.

`colors.toml` is the single semantic palette contract. The experimental
`palette.toml` file is renamed and normalized during implementation; the
catalog validator rejects a theme that contains both names. `provenance.json`
is a required new sidecar with its own schema, not an optional descriptive
file.

The manifest declares:

- schema version, theme ID, display name, and theme version;
- catalog and renderer compatibility;
- semantic palette and light/dark mode;
- supported desktop and GNOME version range;
- available fidelity profiles;
- required and optional adapters for each profile;
- source templates and generated outputs;
- application installation forms and version ranges;
- reload or restart behavior; and
- asset and provenance references.

Hand-authored per-surface output wins over a generated template. User-provided
theme overlays may be supported later, but the first release does not allow
untracked user templates to enter the product-default transaction.

## Engine components

The engine is a small Python 3 package installed under `/usr/lib/dudley/` with
a thin `/usr/bin/dudley-theme` launcher. Python is already part of the target
image and provides the structured file, TOML, JSON, hashing, atomic-file, and
test support needed for a transaction engine. The implementation must not grow
the experimental Bash command into a larger monolith.

The package is divided into:

- catalog and manifest validation;
- deterministic palette/template rendering;
- capability discovery and planning;
- transaction, journal, generation, and state storage;
- adapter protocol and individual adapter modules;
- conflict-aware restoration and crash recovery;
- receipt and status reporting; and
- CLI argument handling.

Adapters may invoke platform tools such as `gsettings`, `dconf`, and
`gnome-extensions`, but subprocess calls are isolated behind testable command
interfaces. Runtime dependencies beyond the Python standard library must be
explicitly supplied and pinned by `dudley-os`.

## Runtime state

Durable state lives under:

```text
${XDG_STATE_HOME:-$HOME/.local/state}/dudley/theme/
```

The layout contains:

```text
preferences.json
baseline/
generations/<generation-id>/
transactions/<transaction-id>/
current
previous
```

`current` and `previous` are atomically replaced references to immutable
generation directories. A generation contains rendered outputs, adapter
plans, hashes, capability results, and the committed receipt.

The per-user lock lives under the safe per-user runtime directory:

```text
${XDG_RUNTIME_DIR:-/run/user/$UID}/dudley-theme.lock
```

The engine refuses a state-changing operation if that directory is absent,
not owned by the user, or not private enough for a trustworthy lock.

Only application integration files that consumers must load are placed under
`XDG_CONFIG_HOME`. Rendered source-of-truth files remain in the immutable
generation and are exposed through ownership-safe links or includes.

## State machine

The engine uses these durable states:

```text
UNMANAGED
PREPARING
COMMITTING
ACTIVE
RECOVERING
RESETTING
DISABLED
CONFLICTED
```

Normal activation is:

```text
UNMANAGED -> PREPARING -> COMMITTING -> ACTIVE
```

A managed switch is:

```text
ACTIVE(A) -> PREPARING(B) -> COMMITTING(B) -> ACTIVE(B)
```

Failure during commit is:

```text
COMMITTING -> RECOVERING -> previous ACTIVE or UNMANAGED
```

If exact automatic recovery would overwrite external user changes:

```text
RECOVERING -> CONFLICTED
```

Disabling is:

```text
ACTIVE -> RESETTING -> DISABLED
```

Unsafe external drift is:

```text
RESETTING -> CONFLICTED
```

An older engine that encounters a newer unsupported state schema enters
read-only status. `status --json` and catalog listing remain available.
`on`, `off`, `set`, `undo`, and `repair` exit without mutation and identify the
minimum compatible engine or image version.

If `current` or `previous` is missing, corrupt, or points outside the generation
store, recovery consults the synchronized transaction journal and verifies
candidate generation receipts and hashes. It repairs a pointer only when one
committed generation is unambiguous. Otherwise it enters `CONFLICTED`, preserves
all resources, and reports the corrupt references.

## Transaction protocol

Every state-changing command:

1. acquires the per-user lock;
2. resolves the requested theme and fidelity profile;
3. discovers capabilities and produces an explicit adapter plan;
4. renders an immutable candidate generation;
5. validates templates, assets, contrast, and adapter requirements;
6. captures exact before-state for every selected resource;
7. verifies that every completed action has a usable rollback action;
8. writes and synchronizes a durable transaction intent;
9. applies adapters in deterministic order;
10. verifies every required adapter;
11. atomically commits `current` and updates `previous`;
12. writes the final receipt; and
13. releases the lock.

If a required adapter fails, the engine rolls completed adapters back in
reverse order and verifies the restored state. A selected required adapter may
not use `|| true`. Unsupported surfaces are excluded during preflight and shown
in the plan; they are not silently converted into successful adapters.

"Atomic" means all required adapters verify or the previous committed
generation is recovered. GNOME and independently running applications do not
provide a single-frame cross-application display transaction, so temporary
visual skew during verified reloads is allowed and reported.

## Adapter contract

Every adapter declares:

- supported installation forms and versions;
- resources it reads and writes;
- preflight requirements;
- exact capture behavior;
- deterministic apply behavior;
- verification behavior;
- rollback behavior;
- conflict detection;
- reload, restart, logout, or reboot requirements; and
- whether it is required by a fidelity profile.

An adapter may not claim support merely because it copied a file into a
directory. The consuming application must be wired to the file and the applied
state must be verifiable.

Adapters must not overwrite a pre-existing regular file, directory, or symlink
without capturing its exact bytes, metadata, type, and target first. They must
record whether an identical include or setting existed before Dudley added it.

## Exact restoration and conflicts

For every resource the engine records:

1. the original value before Dudley management;
2. the exact value Dudley applied; and
3. the current value observed during undo, off, repair, or recovery.

If the current value still equals the value Dudley applied, the adapter may
restore the original value.

If the current value differs from both the original and Dudley-applied values,
the adapter preserves it and marks the resource `CONFLICTED`. It never silently
replaces that user edit. Any destructive force-restore operation is a separate,
explicit future feature and is not part of the first command contract.

Exact restoration includes:

- whether a typed dconf key was set or unset;
- the exact typed dconf value;
- file bytes, mode, ownership, and timestamps where relevant;
- symlink targets and absent paths;
- GNOME Shell extension enabled state and selected Shell theme;
- light, dark, screensaver, and lock-screen wallpaper values;
- application configuration values; and
- whether Dudley introduced or merely observed an existing include.

`gsettings reset` is not accepted as restoration unless the captured original
state was specifically unset and reset is the verified way to recreate it.

## Enrollment and lifecycle

The session initializer consults product policy but never enforces it blindly.

- A pristine user with no Dudley state and no customized managed resources may
  receive the product default.
- An existing customized user remains `UNMANAGED`.
- `DISABLED` always wins over the product default.
- Changing the hook version does not re-enroll a user.
- Updating theme assets or manifest versions reconciles an active user through
  a normal transaction.
- An image upgrade does not mutate a disabled or unmanaged user.
- A bootc rollback that exposes an older engine to newer state produces
  read-only status instead of destructive migration.

The current PR has not established a released state schema and must not ship
default-on before replacement. If the new engine encounters its experimental
theme-name or receipt files, it archives them for diagnosis, disables automatic
enrollment, and reports `CONFLICTED` because those files do not contain a
restorable baseline. It must not pretend it can reconstruct the pre-experiment
desktop. A development or canary user may explicitly accept the current
desktop as a new unmanaged baseline through a guided `repair`; that acceptance
is recorded in the receipt.

## Receipts and status

A committed receipt records:

- state schema version;
- transaction and generation IDs;
- theme ID and version;
- theme catalog digest;
- renderer and template versions;
- final Dudley image identity;
- exact `dsb-common` digest;
- selected adapter IDs and versions;
- rendered-output and asset hashes;
- before and after fingerprints;
- verification result for every adapter;
- restart or reload status;
- activation reason; and
- timestamp.

`status` reports each surface as one of:

```text
verified
unsupported
excluded
pending-restart
drifted
conflicted
```

A single theme-name file is not proof that the desktop is themed.

## Crash recovery

The transaction journal is written before externally visible mutation. After a
process kill, logout, reboot, or power loss, the next command or session
initializer detects the journal and:

1. completes a commit only when every required applied value can still be
   verified;
2. otherwise restores the previous committed generation in reverse adapter
   order; or
3. enters `CONFLICTED` and stops when external drift makes safe restoration
   impossible.

Recovery is idempotent. Re-running it cannot apply an adapter twice or discard
new user state.

## Provenance

Every shipped asset records:

- source;
- author or generator;
- license;
- original hash;
- shipped hash;
- modification status; and
- required attribution.

Omarchy code or data copied under MIT retains its notice. Repository-level MIT
licensing is not treated as evidence that unrelated third-party artwork,
brands, or television assets may be redistributed.

The existing Dudley wallpapers may remain only after their generation source,
redistribution rights, hashes, and intended public use are documented.
Embedded C2PA metadata is supporting provenance evidence, not a license grant.

## Verification

### `dsb-common` gates

The shared payload must pass:

- manifest and provenance schema validation;
- complete payload-contract inventory;
- deterministic render comparison;
- unresolved-template detection;
- relevant palette contrast checks;
- unit tests for every adapter;
- arbitrary pre-existing user-state fixtures;
- byte-exact file and typed-dconf restoration;
- JSONC comments, trailing commas, nested settings, and missing-file cases;
- pre-existing regular file and symlink cases;
- identical pre-existing include-line cases;
- native and Flatpak application path cases;
- active-theme user-edit conflict cases;
- changed assets without a version bump;
- corrupted state and receipt cases;
- concurrent apply/apply and apply/off cases;
- failure injection before and after every adapter; and
- process-kill recovery after every durable phase.

### `dudley-os` gates

The product image must pass:

- exact Bluefin, GNOME Shell, extension, GDM, and Flatpak compatibility checks;
- package and Flatpak runtime presence checks;
- GDM branding validation;
- Plymouth theme and effective-initramfs validation;
- final digest and provenance binding; and
- booted VM acceptance.

### Booted VM acceptance

A QCOW2 or installed VM must prove:

1. Plymouth appears and does not break supported boot, shutdown, update, or
   encrypted-disk prompt paths.
2. GDM branding appears without breaking authentication, accessibility, user
   selection, or session selection.
3. A fresh user receives the agreed product default.
4. A customized existing user can apply, switch, undo, and turn the theme off
   with exact baseline restoration.
5. Two users can select independent states.
6. GNOME Shell has no theme-related errors.
7. Native and Flatpak GTK/libadwaita behavior matches the fidelity report.
8. Curated applications apply and restore correctly.
9. Crash recovery is safe at every transaction phase.
10. Active, disabled, and unmanaged users behave correctly across bootc
    upgrade and rollback.
11. SELinux produces no unexplained theme-related denials.

Acceptance evidence includes machine-readable assertions, before/after
fingerprints, transaction logs, GNOME Shell logs, image and payload digests,
and screenshots or video for visual surfaces. Screenshots alone are not proof;
machine-readable assertions alone do not prove visual fidelity.

## Delivery decomposition

This architecture is intentionally larger than one safe implementation plan.
It is delivered through four bounded subprojects, each with its own reviewed
implementation plan and completion evidence:

### Subproject 1: Transaction foundation in `dsb-common`

- Replace the Bash monolith with the Python package and thin CLI.
- Add catalog, state, generation, journal, receipt, and adapter protocols.
- Implement file, dconf, wallpaper, and experimental-state detection
  primitives.
- Prove locks, exact rollback, conflicts, pointer recovery, and fault
  injection in temporary user homes.
- Keep product enrollment and GNOME Shell activation default-off.

### Subproject 2: GNOME and curated adapters in `dsb-common`

- Add the GNOME Shell theme and extension adapter.
- Add icons, cursors, GTK3, portal preferences, and lock-screen integration.
- Add and qualify each curated application adapter and installation form.
- Add deterministic templates, provenance, and fidelity reporting.
- Prove the real user-session integration matrix without changing GDM or
  Plymouth.

### Subproject 3: Product integration in `dudley-os`

- Pin the published `dsb-common` digest.
- Install and validate host and Flatpak requirements.
- Add pristine-user policy.
- Add static GDM and Plymouth branding.
- Bind image metadata and provenance.
- Keep the product default off until candidate acceptance passes.

### Subproject 4: VM acceptance and promotion

- Run fresh-user, customized-user, multi-user, crash, upgrade, rollback,
  Flatpak, GDM, Plymouth, Nvidia, and SELinux acceptance.
- Publish a default-off canary.
- Validate the canary on Josh's hardware.
- Enable the pristine-user default only in the subsequently promoted image.

Subproject 1 is the first implementation plan after this umbrella design is
approved. Later subprojects cannot claim completion based on earlier unit or
container-only evidence.

## Release order

1. Keep the current theme branch experimental and default-off.
2. Land this architecture and the implementation plan.
3. Replace the monolithic experimental script with the transactional engine,
   schemas, adapters, and tests in `dsb-common`.
4. Publish and verify the new `dsb-common` image.
5. Pin that immutable digest in `dudley-os`.
6. Add packages, default policy, GDM, Plymouth, and image validation in
   `dudley-os`.
7. Build a candidate image and run the destructive VM matrix.
8. Release a default-off canary to Josh's hardware.
9. Enable the pristine-user default only after canary evidence.
10. Promote the digest-bound image after all acceptance evidence passes.

Neither a green payload workflow nor a successful container build is proof
that the whole-desktop experience is released. The final claim requires the
booted-VM and image-lifecycle gates.
