set -u
printf '\n=== NGINX MEDIA ===\n'
cat /etc/nginx/conf.d/makan-livekit-8443.conf
printf '\n=== MEDIA CONFIG REDACTED ===\n'
sed -E '/secret|password|api_key|^keys:/I s/(:|=).*/\1 [REDACTED]/' /opt/makan-media/livekit.yaml
printf '\n=== HEALTH AND OPENAPI ===\n'
python3 - <<'PY'
import urllib.request, json, hashlib
for base in ['http://127.0.0.1:8001', 'http://127.0.0.1:18002', 'https://195.177.255.98']:
    for path in ['/api/v1/health','/api/v1/ready','/openapi.json']:
        try:
            with urllib.request.urlopen(base+path, timeout=10) as response:
                body=response.read()
                print(base+path, response.status, 'sha256='+hashlib.sha256(body).hexdigest())
                doc=json.loads(body)
                if path=='/openapi.json':
                    print('TITLE',doc.get('info',{}).get('title'), 'PATHS', sorted(doc.get('paths',{})))
                else:
                    print(json.dumps(doc, ensure_ascii=False)[:1800])
        except Exception as exc:
            print(base+path, type(exc).__name__, str(exc)[:160])
PY
printf '\n=== OTHER APPLICATION DIRECTORIES ===\n'
find /opt /var/www -maxdepth 2 -type d | head -65
printf '\n=== CERTIFICATE HOOKS ===\n'
find /etc/letsencrypt/renewal-hooks -maxdepth 2 -type f -printf '%p\n'
printf '\n=== CERTIFICATES SERVED ===\n'
for port in 443 8443 5349; do
  printf 'port=%s\n' "$port"
  timeout 10 openssl s_client -connect 195.177.255.98:$port -servername 195.177.255.98 </dev/null 2>/dev/null | openssl x509 -noout -dates -fingerprint -sha256
done
