set -euo pipefail
umask 077
backup=/opt/makan-media/maintenance-20261023
test ! -e "$backup/baseline.json"
mkdir -p "$backup"
cp -a /etc/nginx/conf.d/makan-livekit-8443.conf "$backup/makan-livekit-8443.conf"
python3 - "$backup/baseline.json" <<'PY'
import glob,hashlib,json,pathlib,subprocess,sys,urllib.request,urllib.error
paths=glob.glob('/etc/nginx/sites-enabled/*')+glob.glob('/etc/nginx/conf.d/*.conf')+['/opt/makan-media/livekit.yaml','/opt/makan-media/compose.yaml','/opt/makan-media/turn/turnserver.conf','/opt/makan-media/turn/compose.yaml','/opt/makan-media/keys.yaml']
paths+=glob.glob('/opt/makanapp-ai/*.yml')+glob.glob('/opt/makanapp-ai/*.yaml')
data={'files':{p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in paths},
 'containers':json.loads(subprocess.check_output(['docker','inspect',*subprocess.check_output(['docker','ps','-q'],text=True).split()])), 'http':{}}
data['containers']={c['Name']:{'id':c['Id'],'started':c['State']['StartedAt'],'restart_count':c['RestartCount'],'health':c['State'].get('Health',{}).get('Status')} for c in data['containers']}
for base in ['http://127.0.0.1:8001','http://127.0.0.1:18002','https://195.177.255.98']:
 for path in ['/api/v1/health','/api/v1/ready','/openapi.json']:
  try:
   with urllib.request.urlopen(base+path,timeout=10) as r:
    body=r.read(); data['http'][base+path]={'status':r.status,'sha256':hashlib.sha256(body).hexdigest()}
  except urllib.error.HTTPError as e:
   data['http'][base+path]={'status':e.code}
data['ufw_sha256']=hashlib.sha256(subprocess.check_output(['ufw','status','numbered'])).hexdigest()
pathlib.Path(sys.argv[1]).write_text(json.dumps(data,indent=2))
print(json.dumps(data,indent=2))
PY
printf '\n=== PYTHON YAML ===\n'
python3 -c 'import yaml; print(yaml.__version__)'
printf '\n=== ROOT DIR ===\n'
ls -ld /root /opt/makan-media /var/www/html
