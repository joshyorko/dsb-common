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
- `etc/xdg/autostart/dudley-random-wallpaper.desktop`
- `usr/share/glib-2.0/schemas/zz0-dudley-background.gschema.override`
- `usr/share/ublue-os/just/60-dudley.just`

When migrating content from `dudleys-second-bedroom`, place reusable non-branded content in `shared/` and keep Dudley-specific defaults, branding, wallpaper behavior, and setup assets in `dudley/`.

## Consumer Pattern

`dudley-os` is the product repo and should consume this layer by copying the namespaced directories in order.

```dockerfile
FROM scratch AS ctx

COPY --from=ghcr.io/joshyorko/dsb-common:latest /system_files /ctx/oci/dsb-common/system_files
COPY --from=ghcr.io/projectbluefin/common:latest / /ctx/oci/bluefin-common

FROM ghcr.io/ublue-os/silverblue-main:latest

RUN cp -r /ctx/oci/dsb-common/system_files/shared/. / && \
    cp -r /ctx/oci/bluefin-common/. / && \
    cp -r /ctx/oci/dsb-common/system_files/dudley/. / && \
    cp -r /ctx/local-product-files/. /
```

Intended copy precedence:

1. `dsb-common/shared`
2. `projectbluefin/common`
3. `dsb-common/dudley`
4. local product files from the consumer repo

## Build and Publish

The repository ships only the minimal workflow needed to build and publish the OCI layer.

- Pull requests to `main` build the image for validation.
- Pushes to `main` publish `ghcr.io/joshyorko/dsb-common`.
- Published images are signed with cosign using the `SIGNING_SECRET` repository secret.

The public verification key is stored in `cosign.pub`.

```bash
cosign verify \
  --key cosign.pub \
  ghcr.io/joshyorko/dsb-common:latest
```

For forks:

1. Run `cosign generate-key-pair`.
2. Add `cosign.key` as the `SIGNING_SECRET` repository secret.
3. Replace `cosign.pub` with the matching public key.

## Scope Guardrails

- Keep this repo focused on the shared OCI layer.
- Do not add product-image identity, qcow2/ISO flows, or final assembly logic here.
- Do not move product-only logic out of `dudley-os` unless it is truly shared-layer content.
