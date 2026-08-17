FROM scratch AS dsb-common

# Copy shared cross-image content (reusable by any Dudley-related image)
COPY /system_files/shared /system_files/shared/

# Copy Dudley-specific opinion content (branding, wallpapers, opinionated defaults)
COPY /system_files/dudley /system_files/dudley/

# Publish the selector contract and installer so product images consume the
# reviewed profile instead of maintaining a second hand-picked file list.
COPY /contract/dudley-payload.v1.json /contract/dudley-payload.v1.json
COPY /scripts/install-payload.py /scripts/install-payload.py
