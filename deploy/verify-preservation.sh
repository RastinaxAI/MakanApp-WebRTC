set -euo pipefail
python3 - <<'PY'
import hashlib,json,pathlib,subprocess,urllib.request,urllib.error
baseline=json.loads(pathlib.Path('/opt/makan-media/maintenance-20261023/baseline.json').read_text())
result={'unchanged_files':{},'containers':{},'http':{},'firewall_unchanged':False}
for p,h in baseline['files'].items():
 if p!='/etc/nginx/conf.d/makan-livekit-8443.conf':
  result['unchanged_files'][p]=hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()==h
current=json.loads(subprocess.check_output(['docker','inspect',*subprocess.check_output(['docker','ps','-q'],text=True).split()]))
for c in current:
 state={'id':c['Id'],'started':c['State']['StartedAt'],'restart_count':c['RestartCount'],'health':c['State'].get('Health',{}).get('Status')}
 result['containers'][c['Name']]={'unchanged':baseline['containers'].get(c['Name'])==state,**state}
for url,previous in baseline['http'].items():
 try:
  with urllib.request.urlopen(url,timeout=10) as r:
   current={'status':r.status,'sha256':hashlib.sha256(r.read()).hexdigest()}
 except urllib.error.HTTPError as e: current={'status':e.code}
 result['http'][url]={'unchanged':previous==current,**current}
result['firewall_unchanged']=hashlib.sha256(subprocess.check_output(['ufw','status','numbered'])).hexdigest()==baseline['ufw_sha256']
result['pass']=all(result['unchanged_files'].values()) and all(x['unchanged'] for x in result['containers'].values()) and all(x['unchanged'] for x in result['http'].values()) and result['firewall_unchanged']
print(json.dumps(result,indent=2))
pathlib.Path('/opt/makan-media/maintenance-20261023/preservation.json').write_text(json.dumps(result,indent=2))
assert result['pass'], 'Existing service regression detected'
PY
printf '\n=== ENDPOINTS ===\n'
for path in / /webrtc/ /webrtc/app.js /webrtc/style.css /webrtc/livekit-client.2.23.0.js /webrtc/token /webrtc/keys.yaml; do
 printf '%s ' "$path"
 curl -sS --max-time 10 -o /dev/null -w '%{http_code}\n' "https://195.177.255.98:8443$path"
done
printf '\n=== NON-ROOT CANNOT ISSUE INVITATIONS ===\n'
if runuser -u nobody -- /usr/local/sbin/makan-webrtc-invite --json >/dev/null 2>&1; then
 printf 'FAIL: unprivileged issuance\n'; exit 1
else
 printf 'PASS: unprivileged issuance denied\n'
fi
printf '\n=== SERVICES ===\n'
systemctl is-active nginx docker livekit-docker makan-turn makan-ai-wg-proxy
systemctl is-enabled livekit-docker makan-turn snap.certbot.renew.timer
printf '\n=== TLS ===\n'
openssl x509 -in /etc/letsencrypt/live/195.177.255.98/fullchain.pem -noout -dates
nginx -t
