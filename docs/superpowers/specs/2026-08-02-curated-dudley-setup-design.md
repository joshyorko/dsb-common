# Curated Dudley Setup Design

## Goal

Replace the sprawling Dudley `ujust` surface with one predictable dispatcher
that installs explicit default and AI profiles. Keep the package manifests in
`dsb-common`, where reusable Brewfiles and recipes belong.

## Command surface

Expose one recipe with three user-facing forms:

```text
ujust dudley
ujust dudley ai
ujust dudley info
```

The default form installs the everyday developer profile and VS Code
extensions. The `ai` form installs the opt-in AI profile. The `info` form shows
the Dudley build manifest and the two profile manifests. Remove the historical
`dudley-brews-*`, `dudley-vscode-*`, `dudley-dx`, `dudley-ai`,
`dudley-agents`, and `dudley-build-info` wrappers.

Consumers remain responsible for product-specific handoffs. In particular,
`dudley-os` may tell Dakota users to run upstream `ujust dx-group`; group policy
does not move into this shared payload.

## Default profile

Create one explicit `dudley-default.Brewfile`. It contains the useful packages
currently split across CLI, development, IDE, fonts, and Kubernetes manifests.
It must include:

- `brunoborges/tap/ghx`, with Homebrew `gh` removed;
- `rtk`, `awscli`, `dagger`, `k9s`, and the `kubernetes-cli` formula that
  provides `kubectl`;
- the existing shell, development, IDE, font, Kubernetes, security, and
  packaging tools that do not belong to the AI profile;
- these end-user packages from `joshyorko/tools`:
  - casks: `action-server`, `devpod-linux`, `devsy-desktop`, `rcc`, and
    `vscode-insiders-linux`;
  - formulae: `camp`, `codex-release`,
    `devpod-appindicator-runtime-tools`, `devsy`, and `fizzy-cli-master`.

Do not install duplicate aliases such as both `kubectl` and
`kubernetes-cli`. Do not install Homebrew Podman or packages that depend on it;
Dakota and Fedora Bluefin own the system Podman lifecycle.

## AI profile

Keep `dudley-ai.Brewfile` opt-in. Retain its current AI tools and add these
`joshyorko/tools` packages:

- casks: `buzz-linux` and `t3-code-linux`;
- formulae: `antigravity-cli`, `fizzy-popper-self-hosted`,
  `fizzy-symphony`, and `t3code-cli-main`.

Exclude packages Josh manages manually:

- `codex-desktop`;
- `codex-desktop-linux-builder`;
- `eitype`;
- `voxtype`.

Every current `joshyorko/tools` package must appear in exactly one of the
default, AI, or excluded sets. Contract tests enforce that partition so new tap
packages require an intentional classification.

## Homebrew behavior

Homebrew 6 enables install confirmation by default. Before any managed install,
the Dudley recipe writes the supported user configuration file:

```text
~/.homebrew/brew.env
HOMEBREW_NO_ASK=1
```

Preserve unrelated settings already present in that file. This makes direct
and scripted Homebrew installs non-interactive without scattering `-y` flags.
The recipe initializes `ujust bluefin-cli` only when `brew` is unavailable.

## Update behavior

The shared `ujust update` recipe must only inspect
`/etc/rpm-ostreed.conf` when the file exists. Fedora systems with an explicit
unlocked layering configuration continue to use `rpm-ostree upgrade`; Dakota
and other bootc systems use `sudo bootc upgrade` without emitting a missing-file
error.

## Validation

Tests must prove:

- only the single Dudley dispatcher remains visible;
- default and AI profile routing invokes the intended Brewfile;
- `ghx` is present and `gh` is absent;
- required default tools are present without duplicate Kubectl declarations;
- the full `joshyorko/tools` inventory is partitioned between default, AI, and
  excluded sets;
- Homebrew's no-ask file is written idempotently while preserving other values;
- the update recipe selects bootc when `rpm-ostreed.conf` is missing and retains
  the Fedora unlocked-layering path.

Run repository payload tests, Brew bundle listing checks, Justfile formatting,
ShellCheck where applicable, and `git diff --check` before publication.
