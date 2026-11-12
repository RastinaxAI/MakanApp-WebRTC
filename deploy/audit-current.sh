set -u
export SYSTEMD_PAGER=cat PAGER=cat
printf '\n=== HOST ===\n'
date -u
cat /etc/os-release | head -6
uptime
free -m
df -h /
printf '\n=== SERVICES ===\n'
systemctl is-active nginx docker livekit-docker makan-turn
systemctl list-units --type=service --state=running --no-pager | grep -Ei 'fast|uvicorn|gunicorn|makan|livekit|turn|ai|nginx|docker|wireguard'
docker ps --format '{{.Names}} | {{.Image}} | {{.Status}} | {{.Ports}}'
printf '\n=== LISTENERS ===\n'
ss -lntup
printf '\n=== FIREWALL ===\n'
ufw status numbered
printf '\n=== NGINX ROUTES ===\n'
nginx -T 2>/dev/null | grep -E 'configuration file|listen |server_name|location |proxy_pass|root |ssl_certificate|include '
printf '\n=== MEDIA FILES ===\n'
find /opt/makan-media -maxdepth 2 -type f -printf '%p\n' | head -70
printf '\n=== CONTAINER MOUNTS AND STATE ===\n'
docker inspect --format '{{.Name}} | PID={{.State.Pid}} | Started={{.State.StartedAt}} | Restart={{.RestartCount}} | Mounts={{range .Mounts}}{{.Source}}:{{.Destination}} {{end}}' $(docker ps -q)
printf '\n=== TLS ===\n'
openssl x509 -in /etc/letsencrypt/live/195.177.255.98/fullchain.pem -noout -dates -ext subjectAltName
systemctl list-timers --all --no-pager | grep -Ei 'cert|renew|makan'
printf '\n=== LOCAL HEALTH ===\n'
for url in http://127.0.0.1:7880/ http://127.0.0.1:8001/health http://127.0.0.1:8001/openapi.json https://195.177.255.98:8443/ https://195.177.255.98/health; do
  printf '%s ' "$url"
  curl -sS --max-time 8 -o /dev/null -w '%{http_code}\n' "$url" || true
done
