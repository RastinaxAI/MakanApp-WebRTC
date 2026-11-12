set -euo pipefail
umask 077
backup=/opt/makan-media/maintenance-20261023
test -s "$backup/baseline.json"
test -s /opt/makan-media/diagnostic-stage/index.html
test ! -e /var/www/makan-webrtc
test ! -e /usr/local/sbin/makan-webrtc-invite
install -d -m 755 /var/www/makan-webrtc
install -m 644 /opt/makan-media/diagnostic-stage/index.html /opt/makan-media/diagnostic-stage/style.css /opt/makan-media/diagnostic-stage/app.js /opt/makan-media/diagnostic-stage/livekit-client.2.23.0.js /var/www/makan-webrtc/
install -m 644 /opt/makan-media/diagnostic-stage/SDK-LICENSE /var/www/makan-webrtc/SDK-LICENSE
install -m 700 /opt/makan-media/diagnostic-stage/makan-webrtc-invite.py /usr/local/sbin/makan-webrtc-invite
python3 - <<'PY'
from pathlib import Path
p=Path('/etc/nginx/conf.d/makan-livekit-8443.conf')
s=p.read_text()
assert s.count('    location / {')==1
location='''    # Standalone infrastructure diagnostic; existing API /rtc routes stay intact.
    location = /webrtc { return 308 /webrtc/; }
    location ^~ /webrtc/ {
        alias /var/www/makan-webrtc/;
        index index.html;
        autoindex off;
        add_header Cache-Control "no-store" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-Frame-Options "DENY" always;
        add_header Permissions-Policy "camera=(self), microphone=(self), geolocation=()" always;
        add_header Content-Security-Policy "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self' wss://195.177.255.98:8443; img-src 'self' data:; media-src 'self' blob:; worker-src 'self' blob:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'" always;
    }

'''
p.write_text(s.replace('    location / {',location+'    location / {'))
PY
if ! nginx -t; then
    cp -a "$backup/makan-livekit-8443.conf" /etc/nginx/conf.d/makan-livekit-8443.conf
    exit 1
fi
if ! systemctl reload nginx; then
    cp -a "$backup/makan-livekit-8443.conf" /etc/nginx/conf.d/makan-livekit-8443.conf
    nginx -t && systemctl reload nginx
    exit 1
fi
# A graceful reload can briefly serve a request from an old worker.
healthy=false
for attempt in 1 2 3 4 5; do
    if curl --fail --silent --show-error --max-time 10 https://195.177.255.98:8443/webrtc/ -o /dev/null; then
        healthy=true
        break
    fi
    sleep 1
done
if ! "$healthy"; then
    cp -a "$backup/makan-livekit-8443.conf" /etc/nginx/conf.d/makan-livekit-8443.conf
    nginx -t && systemctl reload nginx
    exit 1
fi
curl --fail --silent --show-error --max-time 10 https://195.177.255.98:8443/ -o /dev/null
printf 'DIAGNOSTIC_DEPLOYED\n'
