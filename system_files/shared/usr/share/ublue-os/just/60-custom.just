# vim: set ft=make :
########################
### Dudley Shared Commands
########################
## Cross-image reusable just recipes provided by dsb-common.
## These recipes are available in all images that consume this layer.

# Import Dudley-specific commands (provided by consuming images or dsb-common)
import? "60-dudley.just"

########################
### Standard Verbs
########################
# configure- = configure something pre-installed on the image
# install-   = install something; no uninstall or configuration provided
# setup-     = install something and also provide configuration and/or uninstallation
# toggle-    = turn something on/off, logic can be automatic or manual selection
# fix-       = apply fix/patch/workaround for something

# Install JetBrains Toolbox | https://www.jetbrains.com/toolbox-app/
[group('Apps')]
install-jetbrains-toolbox:
    #!/usr/bin/env bash
    pushd "$(mktemp -d)"
    echo "Get latest JetBrains Toolbox version"
    curl -sSfL -o releases.json "https://data.services.jetbrains.com/products/releases?code=TBA&latest=true&type=release"
    BUILD_VERSION=$(jq -r '.TBA[0].build' ./releases.json)
    DOWNLOAD_LINK=$(jq -r '.TBA[0].downloads.linux.link' ./releases.json)
    CHECKSUM_LINK=$(jq -r '.TBA[0].downloads.linux.checksumLink' ./releases.json)
    echo "Installing JetBrains Toolbox ${BUILD_VERSION}"
    curl -sSfL -O "${DOWNLOAD_LINK}"
    curl -sSfL "${CHECKSUM_LINK}" | sha256sum -c
    tar zxf jetbrains-toolbox-"${BUILD_VERSION}".tar.gz
    mkdir -p "$HOME/.local/share/JetBrains/ToolboxApp/"
    mv jetbrains-toolbox-"${BUILD_VERSION}"/* "$HOME/.local/share/JetBrains/ToolboxApp/"
    echo "Launching JetBrains Toolbox"
    "$HOME/.local/share/JetBrains/ToolboxApp/bin/jetbrains-toolbox"

# Install OpenTabletDriver, an open source, cross-platform, user-mode tablet driver
[group('Apps')]
install-opentabletdriver:
    #!/usr/bin/bash
    source /usr/lib/ujust/ujust.sh
    echo "Installer for OpenTabletDriver..."
    echo "${bold}Install or Remove OpenTabletDriver${normal}"
    OPTION=$(Choose "Install" "Uninstall" "Exit")
    if [[ "${OPTION,,}" =~ ^install ]]; then
        echo "Installing OpenTabletDriver..."
        git clone https://github.com/OpenTabletDriver/OpenTabletDriver.git /tmp/OpenTabletDriver
        cd /tmp/OpenTabletDriver || exit 1
        ./eng/linux/package.sh --package Generic
        cd /tmp/OpenTabletDriver/dist/Generic || exit 1
        sudo make install
        systemctl --user daemon-reload
        systemctl --user enable --now opentabletdriver.service
        rm -rf /tmp/OpenTabletDriver
        echo "OpenTabletDriver installed successfully"
    elif [[ "${OPTION,,}" =~ ^uninstall ]]; then
        echo "Uninstalling OpenTabletDriver..."
        systemctl --user stop opentabletdriver.service
        systemctl --user disable opentabletdriver.service
        sudo rm -rf /usr/lib/opentabletdriver
        sudo rm -f /usr/lib/systemd/user/opentabletdriver.service
        sudo rm -f /usr/share/applications/opentabletdriver.desktop
        systemctl --user daemon-reload
        echo "OpenTabletDriver uninstalled successfully"
    else
        echo "Exiting..."
        exit 0
    fi
