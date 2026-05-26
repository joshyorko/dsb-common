# Agent Instructions for dsb-common

## Scope

`dsb-common` is a narrow OCI payload layer for Dudley-related images. It owns reusable files that should be shared into consuming product images through the published contract paths:

- `/system_files/shared`
- `/system_files/dudley`

Do not add final OS assembly here. Product image build logic, image identity, bootc linting, baked package installs, ISO/qcow2 flows, and final runtime metadata belong in `dudley-os`.

Treat `dudleys-second-bedroom` as read-only legacy source material. Do not edit, push, reopen, or merge that repository when working on this split. If legacy behavior is still needed, move the reusable payload here or the final assembly glue to `dudley-os`.

Dakota/BuildStream work is out of scope unless the user explicitly requests it. Do not introduce Dakota image names, tags, workflows, package manifests, or docs while syncing Dudley.

## Ownership Rules

Use `system_files/shared/` for product-agnostic DSB organisation files.

Use `system_files/dudley/` for Dudley-specific reusable payload, including:

- wallpapers and GNOME background defaults
- Dudley dconf defaults
- Flatpak preinstall manifests
- Homebrew Brewfiles
- shared Dudley `ujust` recipes
- VS Code extension lists and first-login hooks
- RPM repository definitions such as Google Chrome
- reusable runtime commands such as `dudley-random-wallpaper`

Keep the Google Chrome RPM repository definition here, but keep the package install and post-install repo disabling in `dudley-os`.

## Validation

Before committing changes, run the closest local checks available:

```bash
git diff --check
shellcheck -x system_files/dudley/usr/bin/dudley-random-wallpaper system_files/dudley/usr/share/ublue-os/user-setup.hooks.d/20-dudley-vscode-extensions.sh
HOMEBREW_NO_AUTO_UPDATE=1 brew bundle list --file=system_files/dudley/usr/share/ublue-os/homebrew/dudley-cli.Brewfile
HOMEBREW_NO_AUTO_UPDATE=1 brew bundle list --file=system_files/dudley/usr/share/ublue-os/homebrew/dudley-dev.Brewfile
HOMEBREW_NO_AUTO_UPDATE=1 brew bundle list --file=system_files/dudley/usr/share/ublue-os/homebrew/dudley-fonts.Brewfile
HOMEBREW_NO_AUTO_UPDATE=1 brew bundle list --file=system_files/dudley/usr/share/ublue-os/homebrew/dudley-k8s.Brewfile
just --unstable --fmt --check -f system_files/shared/usr/share/ublue-os/just/60-custom.just
just --unstable --fmt --check -f system_files/dudley/usr/share/ublue-os/just/60-dudley.just
just --unstable --fmt --check -f system_files/dudley/usr/share/ublue-os/just/update.just
```

If a tool is unavailable locally, note that in your handoff and rely on the GitHub workflow to cover it.

## Dudley Bot Renovate

This repo runs self-hosted Renovate from `.github/workflows/renovate.yml`.

Use the repository secret `RENOVATE_TOKEN` for a Dudley-owned bot account or GitHub App installation. If the secret is absent, the workflow falls back to `github.token`, which is useful for smoke tests but will not make pull requests appear as a Dudley-branded bot. Bot tokens must be able to read Dependabot/vulnerability alerts or Renovate will warn that vulnerability alerts are inaccessible.

## Merge Order

Changes here must publish before `dudley-os` can consume them from `ghcr.io/joshyorko/dsb-common:latest`.

Expected order:

1. Merge and verify `dsb-common`.
2. Confirm the `main` publish workflow updated `ghcr.io/joshyorko/dsb-common:latest`.
3. Rebuild or rerun `dudley-os` so it consumes the new layer.
4. Merge `dudley-os` only after that build path is green.
