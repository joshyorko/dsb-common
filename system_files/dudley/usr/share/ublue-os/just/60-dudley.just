# Dudley runtime setup
#
#   ujust dudley
#   ujust dudley brew cli
#   ujust dudley extensions force
#   ujust dudley info

[group('Dudley')]
dudley action="" target="" mode="":
    #!/usr/bin/env bash
    set -euo pipefail

    ACTION="{{ action }}"
    TARGET="{{ target }}"
    MODE="{{ mode }}"
    BREW_DIR="${DUDLEY_BREW_DIR:-/usr/share/ublue-os/homebrew}"
    PROFILE_INFO="${DUDLEY_PROFILE_INFO:-/usr/share/dudley/homebrew-profiles.json}"
    EXTENSIONS_HOOK="${DUDLEY_EXTENSIONS_HOOK:-/usr/share/ublue-os/user-setup.hooks.d/20-dudley-vscode-extensions.sh}"
    NO_ASK_HELPER="${DUDLEY_NO_ASK_HELPER:-/usr/libexec/dudley/configure-homebrew-no-ask}"
    BREW_HELPER="${DUDLEY_BREW_HELPER:-/usr/libexec/dudley/ensure-homebrew}"
    INFO_COMMAND="${DUDLEY_INFO_COMMAND:-/usr/bin/dudley-build-info}"

    ensure_brew() {
        [[ -f "$BREW_HELPER" ]] || {
            echo "ERROR: BREW_HELPER not found: $BREW_HELPER" >&2
            exit 1
        }
        # shellcheck disable=SC1090
        source "$BREW_HELPER"
        ensure_dudley_brew
    }

    install_linux_casks() {
        local brewfile="$1"
        local cask

        [[ "$(uname -s)" == "Linux" ]] || return 0
        while IFS= read -r cask; do
            [[ -n "$cask" ]] || continue
            brew list --cask "$cask" >/dev/null 2>&1 || brew install --cask "$cask"
        done < <(sed -nE 's/^[[:space:]]*cask[[:space:]]+"([^"]+)".*/\1/p' "$brewfile")
    }

    run_bundle() {
        local bundle="$1"
        local brewfile="$BREW_DIR/$bundle"

        [[ -f "$brewfile" ]] || { echo "ERROR: $brewfile not found"; exit 1; }
        ensure_brew
        "$NO_ASK_HELPER"
        brew bundle --file="$brewfile"
        install_linux_casks "$brewfile"
    }

    run_extensions() {
        local force="${1:-}"

        [[ -x "$EXTENSIONS_HOOK" ]] || {
            echo "ERROR: $EXTENSIONS_HOOK not found or not executable"
            exit 1
        }
        if [[ "$force" == "force" ]]; then
            VSCODE_EXTENSIONS_FORCE=1 bash "$EXTENSIONS_HOOK"
        else
            bash "$EXTENSIONS_HOOK"
        fi
    }

    run_all_brewfiles() {
        run_bundle "dudley-default.Brewfile"
        run_bundle "dudley-cli.Brewfile"
        run_bundle "dudley-dev.Brewfile"
        run_bundle "dudley-ide.Brewfile"
        run_bundle "dudley-fonts.Brewfile"
        run_bundle "dudley-k8s.Brewfile"
    }

    show_list() {
        echo "Available Dudley Brewfiles:"
        if [[ -d "$BREW_DIR" ]]; then
            for brewfile in "$BREW_DIR"/dudley-*.Brewfile; do
                [[ -f "$brewfile" ]] || continue
                printf '  %s\n' "$(basename "$brewfile")"
            done
        else
            echo "  Homebrew directory not found"
        fi
        printf '%s\n' \
            "" \
            "Commands:" \
            "  ujust dudley                 Install the complete Dudley profile" \
            "  ujust dudley brew <profile>  Install cli, dev, ide, fonts, k8s, or all" \
            "  ujust dudley ai              Install the opt-in AI profile" \
            "  ujust dudley extensions      Install or update VS Code extensions" \
            "  ujust dudley tools           Install the curated Joshyorko tools" \
            "  ujust dudley info            Show build and profile information"
    }

    show_info() {
        "$INFO_COMMAND"
        echo
        if [[ -f "$PROFILE_INFO" ]]; then
            cat "$PROFILE_INFO"
        else
            echo "Dudley Homebrew profile metadata is unavailable."
        fi
    }

    setup_target() {
        case "$1" in
            all|"")
                run_all_brewfiles
                run_extensions
                ;;
            cli)
                run_bundle "dudley-cli.Brewfile"
                ;;
            dev)
                run_bundle "dudley-dev.Brewfile"
                run_extensions
                ;;
            ide)
                run_bundle "dudley-ide.Brewfile"
                ;;
            fonts)
                run_bundle "dudley-fonts.Brewfile"
                ;;
            k8s)
                run_bundle "dudley-k8s.Brewfile"
                ;;
            ai)
                run_bundle "dudley-ai.Brewfile"
                ;;
            *)
                echo "ERROR: expected profile: cli|dev|ide|fonts|k8s|all|ai"
                exit 1
                ;;
        esac
    }

    case "$ACTION" in
        ""|setup)
            setup_target "${TARGET:-all}"
            ;;
        brew)
            setup_target "$TARGET"
            ;;
        ai)
            setup_target ai
            ;;
        dx)
            setup_target all
            ;;
        tools)
            run_bundle "dudley-default.Brewfile"
            run_bundle "dudley-ai.Brewfile"
            ;;
        extensions)
            run_extensions "${TARGET:-$MODE}"
            ;;
        info)
            show_info
            ;;
        list|help|--help|-h)
            show_list
            ;;
        *)
            echo "ERROR: unknown Dudley command '$ACTION'"
            show_list
            exit 1
            ;;
    esac

toggle-user-motd:
    @uwelcome toggle

# Dudley already inherits from a developer image, so Bluefin's generic devmode
# rebase recipe should not synthesize a sibling image name.
devmode:
    @ujust toggle-devmode

toggle-devmode:
    #!/usr/bin/env bash
    set -euo pipefail

    IMAGE_INFO_FILE="${IMAGE_INFO_FILE:-/usr/share/ublue-os/image-info.json}"
    if [[ ! -f "$IMAGE_INFO_FILE" ]]; then
        echo "ERROR: $IMAGE_INFO_FILE not found"
        exit 1
    fi

    image_flavor="$(jq -r '."image-flavor" // ""' "$IMAGE_INFO_FILE")"
    base_image_name="$(jq -r '."base-image-name" // ""' "$IMAGE_INFO_FILE")"

    if [[ "$image_flavor" =~ dx || "$base_image_name" =~ dx ]]; then
        echo "Dudley is already built from a developer image."
        ujust dudley
        if gum confirm "Install the default development Flatpaks?"; then
            ADD_DEVMODE=1 ujust install-system-flatpaks 0 1
        fi
        echo "Use ujust dx-group when the image provides Docker or virtualization groups."
        exit 0
    fi

    echo "Dudley is not built from a developer base image."
    echo "Install Dudley's portable user-space tools with: ujust dudley"
    exit 1
