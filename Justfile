export image_name := env("IMAGE_NAME", "dsb-common")
export default_tag := env("DEFAULT_TAG", "latest")
export dagger_registry := env("DAGGER_REGISTRY", "ghcr.io/joshyorko")
export dagger_local_registry := env("LOCAL_REGISTRY", "localhost:5000")
export dagger_registry_username := env("REGISTRY_USERNAME", "")
export dagger_registry_password_env := env("REGISTRY_PASSWORD_ENV", "REGISTRY_PASSWORD")
export dagger_signing_key_env := env("SIGNING_KEY_ENV", "SIGNING_SECRET")
export dagger_signing_password_env := env("SIGNING_PASSWORD_ENV", "SIGNING_PASSWORD")
export source_uri := env("SOURCE_URI", "https://github.com/joshyorko/dsb-common")
just := just_executable()

[private]
default:
    @just --list

# Build the OCI payload image
[group('Image')]
build $target_image=image_name $tag=default_tag:
    #!/usr/bin/env bash
    set -euo pipefail

    podman build \
        --format oci \
        --file ./Containerfile \
        --tag "${target_image}:${tag}" \
        .

# Build the OCI payload image for GitHub Actions in rootful container storage
[group('Image')]
build-ghcr $target_image=image_name $tag=default_tag:
    #!/usr/bin/env bash
    set -euo pipefail

    if [[ "${UID}" -gt "0" ]]; then
        echo "Must run with sudo or as root."
        exit 1
    fi

    "{{ just }}" build "${target_image}" "${tag}"

# Show repo-local Dagger functions
[group('Dagger')]
dagger-functions:
    dagger functions

# Show Dagger release metadata and tag plan
[group('Dagger')]
dagger-metadata registry=dagger_registry image=image_name source=source_uri:
    dagger call metadata --registry "{{ registry }}" --image-name "{{ image }}" --source-uri "{{ source }}"

# Run Dagger planner unit tests
[group('Dagger')]
dagger-test:
    docker run --rm -v "$PWD/.dagger:/src" -w /src golang:1.26 go test pipeline_plan.go pipeline_plan_test.go

# Build with Dagger without publishing
[group('Dagger')]
dagger-build registry=dagger_registry image=image_name:
    dagger call build --registry "{{ registry }}" --image-name "{{ image }}"

# Run the Dagger release planner without publishing
[group('Dagger')]
dagger-release-dry-run registry=dagger_registry image=image_name source=source_uri:
    dagger call release --registry "{{ registry }}" --image-name "{{ image }}" --source-uri "{{ source }}" --publish=false

# Publish to a local OCI registry without signing or attestations
[group('Dagger')]
dagger-publish-local registry=dagger_local_registry image=image_name source=source_uri:
    dagger call release --registry "{{ registry }}" --image-name "{{ image }}" --source-uri "{{ source }}" --sign=false --attest=false

# Run the full local Dagger release path. Set REGISTRY_PASSWORD for private registries.
[group('Dagger')]
dagger-release registry=dagger_registry image=image_name username=dagger_registry_username password_env=dagger_registry_password_env source=source_uri signing_key_env=dagger_signing_key_env signing_password_env=dagger_signing_password_env:
    #!/usr/bin/env bash
    set -euo pipefail

    args=(
        release
        --registry "{{ registry }}"
        --image-name "{{ image }}"
        --source-uri "{{ source }}"
    )

    if [[ -n "{{ username }}" ]]; then
        args+=(--registry-username "{{ username }}")
    fi

    password_var="{{ password_env }}"
    if [[ -n "${!password_var:-}" ]]; then
        args+=(--registry-password "env:${password_var}")
    fi

    signing_key_var="{{ signing_key_env }}"
    signing_password_var="{{ signing_password_env }}"
    if [[ -n "${!signing_key_var:-}" ]]; then
        args+=(--signing-key "env:${signing_key_var}")
        if [[ -n "${!signing_password_var:-}" ]]; then
            args+=(--signing-password "env:${signing_password_var}")
        fi
    else
        args+=(--sign=false --attest=false)
    fi

    dagger call "${args[@]}"
