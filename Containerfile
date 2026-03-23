FROM scratch AS dsb-common

# Copy shared cross-image content (reusable by any Dudley-related image)
COPY /system_files/shared /system_files/shared/

# Copy Dudley-specific opinion content (branding, wallpapers, opinionated defaults)
COPY /system_files/dudley /system_files/dudley/
