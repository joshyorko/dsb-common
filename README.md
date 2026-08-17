# dsb-common

`dsb-common` publishes a narrow shared OCI layer for Dudley-related images. It is modeled after [projectbluefin/common](https://github.com/projectbluefin/common), uses [joshyorko/dudleys-second-bedroom](https://github.com/joshyorko/dudleys-second-bedroom) as migration source material, and is consumed by [joshyorko/dudley-os](https://github.com/joshyorko/dudley-os).

This repository is intentionally limited to shared layer content. It does not own final OS assembly, qcow2/ISO creation, product-image build orchestration, or final image verification.

## Published Layer Contract

The image published to `ghcr.io/joshyorko/dsb-common` exports four namespaced paths:

- `/system_files/shared`
- `/system_files/dudley`
- `/contract/dudley-payload.v1.json`
- `/scripts/install-payload.py`

Consumers should copy from those paths explicitly rather than assuming flattened `/usr` or `/etc` paths inside the OCI layer.

The machine-readable Dudley payload contract lives at `contract/dudley-payload.v1.json`. It lists every file under `system_files/`, its final target path, kind, and selectors for Bluefin, Dakota, and Ubuntu-family adapters. Use `scripts/install-payload.py --profile bluefin --dest <root>` for the Bluefin payload, `--profile dakota` for the portable Dakota/Ghostty payload, and `--profile ubuntu` for the portable Ubuntu feasibility payload. Ownership and applicability for the user-facing parity surface are reviewed in `contract/dudley-parity.v1.json`.

## Repository Layout

### `system_files/shared/`

Cross-image reusable content that is not Dudley-branded. Current examples:

- `usr/share/ublue-os/just/60-custom.just`

### `system_files/dudley/`

Dudley-opinionated content that should follow the Dudley flavor across consuming images. Current examples:

- `usr/bin/dudley-random-wallpaper`
- `etc/yum.repos.d/google-chrome.repo`
- `etc/xdg/autostart/dudley-random-wallpaper.desktop`
- `etc/dconf/db/distro.d/99-dudley-terminal-keybindings`
- `etc/flatpak/preinstall.d/dudley-*.preinstall`
- `usr/share/backgrounds/dudley/*`
- `usr/share/glib-2.0/schemas/zz0-dudley-background.gschema.override`
- `usr/bin/dudley-build-info`
- `usr/share/ublue-os/homebrew/dudley-*.Brewfile`
- `usr/share/dudley/homebrew-profiles.json`
- `usr/share/ublue-os/just/60-dudley.just`
- `usr/share/ublue-os/just/update.just`
- `usr/share/dudley/terminal-contract.json` and native terminal adapters
- `usr/share/ublue-os/user-setup.hooks.d/15-dudley-bazaar-launcher.sh`
- `usr/share/ublue-os/user-setup.hooks.d/20-dudley-vscode-extensions.sh`
- `usr/share/ublue-os/vscode-extensions.list`

The MOTD payload supplies uWelcome configuration, uMotd tags, and Bash/Zsh and
Fish login hooks. Bluefin uses the shared command surface; Dakota selects its
native configuration, which routes setup help through `ujust dudley list`
instead of the intentionally unavailable `ujust bluefin-cli`. The
terminal contract is emulator-neutral; Bluefin uses the Ptyxis adapter while
Dakota consumes the native Ghostty adapter. Final consumer images remain
responsible for installing/activating the appropriate emulator and MOTD
runtime.

The Dudley wallpaper photos from `joshyorko/dudleys-second-bedroom/custom_wallpapers` are bundled here so the wallpaper switcher works without consumer repos carrying duplicate image assets.

When migrating content from `dudleys-second-bedroom`, place reusable non-branded content in `shared/` and keep Dudley-specific defaults, branding, wallpaper behavior, wallpapers, Brewfiles, Flatpak manifests, RPM repository definitions such as Google Chrome, VS Code Insiders Homebrew opinion, VS Code extension opinion, and setup assets in `dudley/`.

`dudley-build-info` is shipped from this repo as a Dudley-facing diagnostic command. Consuming repos are responsible for generating `/etc/dudley/build-manifest.json` during final assembly so the command has image metadata to display.

## Portable DX Payload

Dudley's portable developer experience lives here instead of in a final product image. It tracks the user-space parts of Bluefin DX and Project Bluefin common that can travel cleanly across current Bluefin-based images and future Dakota-style assembly:

- curated workstation tooling in `dudley-default.Brewfile`
- compatibility profiles for `cli`, `dev`, `ide`, `fonts`, and `k8s`
- live metadata and Linux artifact validation for every shipped `tap`, `brew`, and `cask`
- DX Flatpaks in `dudley-dx.preinstall`
- VS Code defaults use JetBrains Mono 16, with a one-time migration for the previous generic monospace settings
- existing Bluefin user profiles re-enable the upstream top-panel menu for system monitoring, settings, applications, documentation, and Ask Bluefin
- `ujust dudley` as the user-space setup entrypoint, with compatibility commands
  such as `ujust dudley brew cli`, `ujust dudley brew dev`, `ujust dudley brew
  ide`, `ujust dudley brew fonts`, `ujust dudley brew k8s`, `ujust dudley brew
  all`, `ujust dudley extensions`, `ujust dudley tools`, `ujust dudley list`,
  and `ujust dudley info`
- opt-in AI tooling through `dudley-ai.Brewfile` and `ujust dudley ai`
- profile and build details through `ujust dudley info`

Fedora/DNF packages, systemd service enablement, Docker/libvirt/incus group creation, BuildStream elements, bootc metadata, and baked browser/package installs remain final-image concerns. Put those in `dudley-os`, Dakota/BuildStream product targets, or sysexts rather than this shared payload layer.

## Consumer Pattern

`dudley-os` is the product repo and should consume this layer by copying the namespaced directories in order.

```dockerfile
FROM scratch AS ctx

COPY --from=ghcr.io/joshyorko/dsb-common:latest /system_files/shared /ctx/oci/dsb-common/shared
COPY --from=ghcr.io/joshyorko/dsb-common:latest /system_files/dudley /ctx/oci/dsb-common/dudley

FROM ghcr.io/ublue-os/bluefin-dx:latest

RUN cp -r /ctx/oci/dsb-common/shared/. / && \
    cp -r /ctx/oci/dsb-common/dudley/. / && \
    cp -r /ctx/local-product-files/. /
```

Intended copy precedence:

1. `dsb-common/shared`
2. `dsb-common/dudley`
3. local product files from the consumer repo

## Build and Publish

The repository ships only the minimal workflow needed to build and publish the OCI layer.

- Pull requests validate shell payloads, Brewfile syntax, live Homebrew metadata and Linux artifacts, Flatpak preinstall files, just recipes, and the Chrome repo contract.
- Pull requests validate the v1 payload contract and profile installer so every shipped file is represented exactly once.
- Pull requests to `main` build the image for validation.
- Pushes to `main` publish `ghcr.io/joshyorko/dsb-common`.
- Published images are keylessly signed with cosign, get an attached SPDX SBOM, and publish GitHub provenance attestations.

### Local Dagger Helpers

The repo-local Dagger module is for local and ad hoc portable runs. GitHub
Actions keeps its separate workflow in `.github/workflows/build.yml`; CI does
not call Dagger.

```bash
dagger functions
dagger call metadata
dagger call release --publish=false
```

Shortcuts are available through `just`:

```bash
just dagger-metadata
just dagger-build
just dagger-release-dry-run
just dagger-publish-local
just dagger-release
```

Run the local release path against GHCR after authenticating with a token:

```bash
dagger call release \
  --registry ghcr.io/joshyorko \
  --registry-username "$GITHUB_ACTOR" \
  --registry-password env:GITHUB_TOKEN \
  --signing-key env:SIGNING_SECRET \
  --signing-password env:SIGNING_PASSWORD \
  --source-uri https://github.com/joshyorko/dsb-common
```

Try another registry without code changes:

```bash
dagger call release --registry registry.gitlab.com/group --publish=false
dagger call release --registry localhost:5000 --sign=false --attest=false
```

The Dagger module exposes `metadata`, `build`, `publish`, `sbom`,
`attest-sbom`, `attest-provenance`, `sign`, and `release`. It uses Buildah
from `quay.io/buildah/stable:v1.41`, builds this repo's scratch `Containerfile`
with OCI format, plans `latest`, `YYYYMMDD`, and short-SHA tags, generates a
Trivy SPDX JSON SBOM, and can use cosign for key-based signing and SBOM/SLSA
provenance attestations when `--signing-key` is provided. Loopback registries
(`localhost`, `127.0.0.1`, and `[::1]`) publish with `--tls-verify=false`; all
other registries use TLS verification.

## Dudley Bot Renovate

Dependency updates are handled by the central `joshyorko/renovate-config` runner. Repo-specific matching and grouping lives in `.github/renovate.json5`; do not add a repo-local Renovate workflow unless the runner model changes again. The central bot token must be able to read Dependabot/vulnerability alerts and write workflow files so Renovate can update `.github/workflows/**`.

Published CI images use keyless signing. Verify them with the GitHub Actions OIDC identity:

```bash
cosign verify \
  --certificate-identity-regexp "https://github.com/joshyorko/dsb-common/" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  ghcr.io/joshyorko/dsb-common:latest
```

The repo-local Dagger release path can still use key-based signing for ad hoc registries when `--signing-key` is provided.

## Scope Guardrails

- Keep this repo focused on the shared OCI layer.
- Do not add product-image identity, qcow2/ISO flows, or final assembly logic here.
- Do not move product-only logic out of `dudley-os` unless it is truly shared-layer content.
