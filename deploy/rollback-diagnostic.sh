#!/usr/bin/env bash
# Remove only the diagnostic route. Leave existing media and AI services running.
set -euo pipefail
backup=/opt/makan-media/maintenance-20261023
target=/etc/nginx/conf.d/makan-livekit-8443.conf
test -s "$backup/makan-livekit-8443.conf"
# Stop if somebody modified the deployed config since this maintenance operation.
sha256sum --check "$backup/deployed-nginx.sha256"
cp -a "$target" "$backup/before-rollback.conf"
cp -a "$backup/makan-livekit-8443.conf" "$target"
if ! nginx -t; then
 cp -a "$backup/before-rollback.conf" "$target"
 exit 1
fi
systemctl reload nginx
printf 'Diagnostic route removed. FastAPI, LiveKit, TURN and firewall unchanged.\n'
printf 'Static files and invitation helper retained for recovery; the page is no longer served.\n'
