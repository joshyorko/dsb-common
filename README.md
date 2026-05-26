# dsb-common

`dsb-common` publishes a narrow shared OCI layer for Dudley-related images. It is modeled after [projectbluefin/common](https://github.com/projectbluefin/common), uses [joshyorko/dudleys-second-bedroom](https://github.com/joshyorko/dudleys-second-bedroom) as migration source material, and is consumed by [joshyorko/dudley-os](https://github.com/joshyorko/dudley-os).

This repository is intentionally limited to shared layer content. It does not own final OS assembly, qcow2/ISO creation, product-image build orchestration, or final image verification.

## Published Layer Contract

The image published to `ghcr.io/joshyorko/dsb-common` exports exactly two namespaced paths:

- `/system_files/shared`
- `/system_files/dudley`

Consumers should copy from those paths explicitly rather than assuming flattened `/usr` or `/etc` paths inside the OCI layer.

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
- `usr/share/ublue-os/just/60-dudley.just`
- `usr/share/ublue-os/just/update.just`
- `usr/share/ublue-os/user-setup.hooks.d/20-dudley-vscode-extensions.sh`
- `usr/share/ublue-os/vscode-extensions.list`

The Dudley wallpaper photos from `joshyorko/dudleys-second-bedroom/custom_wallpapers` are bundled here so the wallpaper switcher works without consumer repos carrying duplicate image assets.

When migrating content from `dudleys-second-bedroom`, place reusable non-branded content in `shared/` and keep Dudley-specific defaults, branding, wallpaper behavior, wallpapers, Brewfiles, Flatpak manifests, RPM repository definitions such as Google Chrome, VS Code Insiders Homebrew opinion, VS Code extension opinion, and setup assets in `dudley/`.

`dudley-build-info` is shipped from this repo as a Dudley-facing diagnostic command. Consuming repos are responsible for generating `/etc/dudley/build-manifest.json` during final assembly so the command has image metadata to display.

## Portable DX Payload

Dudley's portable developer experience lives here instead of in a final product image. It tracks the user-space parts of Bluefin DX and Project Bluefin common that can travel cleanly across current Bluefin-based images and future Dakota-style assembly:

- extra CLI/session tools such as `atuin`, `mise`, and `podman-tui`
- IDE/editor tooling in `dudley-ide.Brewfile`
- extra Nerd Fonts from Bluefin common
- DX Flatpaks in `dudley-dx.preinstall`
- VS Code default settings and extension setup
- `ujust dudley dx` as the user-space setup entrypoint
- opt-in AI and agent tooling through `dudley-ai.Brewfile`, `ujust dudley ai`, and `ujust dudley agents`

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

- Pull requests validate shell payloads, Brewfile syntax, Flatpak preinstall files, just recipes, and the Chrome repo contract.
- Pull requests to `main` build the image for validation.
- Pushes to `main` publish `ghcr.io/joshyorko/dsb-common`.
- If `SIGNING_SECRET` is configured, published images are also signed with cosign.

### Local Dagger Helpers

The repo-local Dagger module is for local and ad hoc portable runs. GitHub
Actions keeps its separate workflow in `.github/workflows/build.yml`; CI does
not call Dagger.

```bash
dagger functions
dagger call metadata
dagger call release --publish=false
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

Dependency updates are handled by the self-hosted GitHub Actions workflow in `.github/workflows/renovate.yml`. Set the repository secret `RENOVATE_TOKEN` to a Dudley-owned bot account or GitHub App installation token when you want Renovate pull requests to come from that identity. Without the secret, the workflow can fall back to `github.token` for repository-local runs. Bot tokens must be able to read Dependabot/vulnerability alerts so Renovate can process vulnerability fixes without warning.

The public verification key is stored in `cosign.pub`.

```bash
cosign verify \
  --key cosign.pub \
  ghcr.io/joshyorko/dsb-common:latest
```

For forks:

1. Run `cosign generate-key-pair`.
2. Add `cosign.key` as the `SIGNING_SECRET` repository secret.
3. Add the cosign key password as `SIGNING_PASSWORD` only when the key is encrypted; leave it unset for an unencrypted key.
4. Replace `cosign.pub` with the matching public key.

If you have not configured signing yet, the publish workflow still builds and publishes the layer and skips the signing step.

## Scope Guardrails

- Keep this repo focused on the shared OCI layer.
- Do not add product-image identity, qcow2/ISO flows, or final assembly logic here.
- Do not move product-only logic out of `dudley-os` unless it is truly shared-layer content.
