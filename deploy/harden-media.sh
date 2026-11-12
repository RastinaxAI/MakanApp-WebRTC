#!/usr/bin/env bash
set -euo pipefail
umask 077
export SYSTEMD_PAGER=cat PAGER=cat
test -s /opt/makan-media/compose.yaml
test -s /opt/makan-media/turn/compose.yaml
test "$(docker inspect -f '{{.State.Running}}' makan-media-livekit-1)" = true
test "$(docker inspect -f '{{.State.Running}}' makan-turn-coturn-1)" = true
backup="/opt/makan-media/backup-infra-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 700 "$backup"
cp -a /etc/ufw "$backup/ufw"
iptables-save > "$backup/iptables.v4"
ip6tables-save > "$backup/iptables.v6"
for unit in makan-turn.service livekit-docker.service; do
    if test -f "/etc/systemd/system/$unit"; then
        cp -a "/etc/systemd/system/$unit" "$backup/$unit"
    fi
done
printf '%s\n' "$backup" > /opt/makan-media/last-infra-backup

# Keep the existing WireGuard gateway and all currently used media paths.
# No Docker/AI container, Nginx route, credential or certificate is replaced.
ufw allow 22/tcp comment 'SSH management'
ufw allow 80/tcp comment 'ACME certificate renewal'
ufw allow 443/tcp comment 'Existing AI HTTPS gateway'
ufw allow 8443/tcp comment 'LiveKit HTTPS WSS by IP'
ufw allow 7881/tcp comment 'LiveKit ICE TCP'
ufw allow 3478/udp comment 'LiveKit embedded TURN UDP STUN'
ufw allow 7882/udp comment 'LiveKit ICE UDP mux'
ufw allow 5349/tcp comment 'Coturn TURN TLS by IP'
ufw allow 41000:41100/udp comment 'Coturn relay range'
ufw allow 51820/udp comment 'Existing WireGuard tunnel'
ufw allow in on wg0 comment 'Preserve existing WireGuard gateway'

# Revert only the firewall enable if SSH is lost during this deployment.
systemd-run --unit=makan-ufw-rollback --on-active=5m /usr/sbin/ufw disable
ufw default deny incoming
ufw default allow outgoing
ufw --force enable

cat > /etc/systemd/system/makan-turn.service <<'UNIT'
[Unit]
Description=Makan media TURN TLS (existing Docker Compose deployment)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/makan-media/turn
ExecStart=/usr/bin/docker compose -f /opt/makan-media/turn/compose.yaml up -d
ExecStop=/usr/bin/docker compose -f /opt/makan-media/turn/compose.yaml stop
TimeoutStartSec=120
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/livekit-docker.service <<'UNIT'
[Unit]
Description=Makan LiveKit media spike (existing Docker Compose deployment)
Requires=docker.service
After=docker.service network-online.target makan-turn.service
Wants=network-online.target makan-turn.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/makan-media
ExecStart=/usr/bin/docker compose -f /opt/makan-media/compose.yaml up -d
ExecStop=/usr/bin/docker compose -f /opt/makan-media/compose.yaml stop
TimeoutStartSec=120
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
UNIT
chmod 644 /etc/systemd/system/makan-turn.service /etc/systemd/system/livekit-docker.service
systemctl daemon-reload
systemctl enable --now makan-turn.service livekit-docker.service
nginx -t
curl --fail --silent --show-error --max-time 10 https://195.177.255.98:8443/ > /dev/null
printf '\nHARDENING_OK\n'
