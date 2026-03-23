# dsb-common

Shared OCI common layer for Dudley-related images. This repository is the single source of truth for configuration files shared across all DSB (Dudley's Second Bedroom) images.

This repository is modeled after [projectbluefin/common](https://github.com/projectbluefin/common) and is consumed by [joshyorko/dudley-os](https://github.com/joshyorko/dudley-os).

> **Scope**: This repo provides only the common OCI layer. It is **not** responsible for final OS assembly, qcow2/ISO creation, or product image workflows — those live in consuming repos like `dudley-os`.

---

## Directory Structure

This repository organizes configuration files into two main directories:

### `system_files/shared/` — Cross-Image Content

Files that are image-agnostic and can be reused by any Dudley-related image:

- **Wallpaper randomizer** — `usr/bin/dudley-random-wallpaper` picks a random wallpaper from `/usr/share/backgrounds/dudley/` at login
- **Autostart entry** — `etc/xdg/autostart/dudley-random-wallpaper.desktop` triggers the randomizer on GNOME login
- **GSettings schema override** — `usr/share/glib-2.0/schemas/zz0-dudley-background.gschema.override` sets the default background
- **Just recipes** — `usr/share/ublue-os/just/60-custom.just` provides shared `ujust` commands (JetBrains Toolbox, OpenTabletDriver, etc.)
- **Background placeholder** — `usr/share/backgrounds/dudley/` is the target directory for wallpaper assets placed at build time

### `system_files/dudley/` — Dudley Opinion

Files specific to the Dudley image flavour. Consuming images that want the full Dudley experience copy from here:

- **Dudley just recipes** — `usr/share/ublue-os/just/60-dudley.just` contains Dudley-branded `ujust` commands (brew installs, VS Code extensions)
- **Wallpaper placeholder** — `usr/share/backgrounds/dudley/` staging directory for Dudley-specific wallpapers

**When adding new files:** Place in `dudley/` if Dudley-opinionated (branding, specific defaults), otherwise use `shared/`.

---

## Usage in a Containerfile

Reference this layer as a build stage and copy the directories you need.

### Copy everything (full Dudley experience)

```dockerfile
FROM ghcr.io/joshyorko/dsb-common:latest AS dsb-common

# Copy all system files (shared + dudley)
COPY --from=dsb-common /system_files/shared /
COPY --from=dsb-common /system_files/dudley /
```

### Copy only shared (image-agnostic, no Dudley opinion)

```dockerfile
FROM ghcr.io/joshyorko/dsb-common:latest AS dsb-common

# Copy only the cross-image shared layer
COPY --from=dsb-common /system_files/shared /
```

### Copy only Dudley opinion

```dockerfile
FROM ghcr.io/joshyorko/dsb-common:latest AS dsb-common

# Copy only Dudley-specific overrides
COPY --from=dsb-common /system_files/dudley /
```

### As part of a multi-stage ctx build (dudley-os pattern)

```dockerfile
FROM scratch AS ctx

# Pull in dsb-common alongside other OCI layers
COPY --from=ghcr.io/joshyorko/dsb-common:latest /system_files /oci/dsb-common

# ... other layers ...

FROM ghcr.io/ublue-os/silverblue-main:latest

RUN --mount=type=bind,from=ctx,source=/,target=/ctx \
    --mount=type=cache,dst=/var/cache \
    --mount=type=tmpfs,dst=/tmp \
    # Copy shared content into the image filesystem
    cp -r /ctx/oci/dsb-common/system_files/shared/. / && \
    cp -r /ctx/oci/dsb-common/system_files/dudley/. / && \
    /ctx/build/10-build.sh
```

---

## GitHub Actions

### Build and Publish (`build.yml`)

Triggers on:
- Push to `main`
- Pull requests targeting `main`
- Manual dispatch (`workflow_dispatch`)

Publishes the OCI layer to `ghcr.io/joshyorko/dsb-common` with the following tags:

| Tag | Description |
|-----|-------------|
| `latest` | Most recent push to `main` |
| `YYYYMMDD` | Date-stamped build |
| `<sha7>` | Short commit SHA |
| `pr-N` | Pull request builds (not pushed) |

Images are signed with [cosign](https://github.com/sigstore/cosign) using a repository secret (`SIGNING_SECRET`).

### Monthly Release (`release.yml`)

Runs on the 1st of every month and creates a versioned GitHub release tagged `vYYYY.MM`.

---

## Cosign / Image Verification

The public key used to verify signed images is stored at `cosign.pub` in this repository.

### Verify a published image

```bash
cosign verify \
  --key cosign.pub \
  ghcr.io/joshyorko/dsb-common:latest
```

### Setting up signing for your fork

1. Generate a cosign key pair:
   ```bash
   cosign generate-key-pair
   ```
2. Add the contents of `cosign.key` as a repository secret named `SIGNING_SECRET`.
3. Replace `cosign.pub` in the repository with your public key.

---

## Contributing

- Keep this repo intentionally narrow — shared layer content only
- Do **not** add OS assembly, ISO/qcow2, or product image logic here
- New shared files go in `system_files/shared/`
- New Dudley-opinionated files go in `system_files/dudley/`
- Follow existing file naming conventions

---

## Related Repositories

| Repository | Role |
|------------|------|
| [joshyorko/dudley-os](https://github.com/joshyorko/dudley-os) | Primary consumer of this layer |
| [joshyorko/dudleys-second-bedroom](https://github.com/joshyorko/dudleys-second-bedroom) | Reference source for Dudley content |
| [projectbluefin/common](https://github.com/projectbluefin/common) | Upstream architectural inspiration |
