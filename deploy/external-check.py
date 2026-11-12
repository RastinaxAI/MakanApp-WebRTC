import concurrent.futures
import datetime as dt
import hashlib
import json
from pathlib import Path
import socket
import ssl
import urllib.error
import urllib.request

host='195.177.255.98'
def probe(port):
    try:
        with socket.create_connection((host,port),timeout=4):
            return {'port':port,'reachable':True}
    except (TimeoutError,OSError):
        return {'port':port,'reachable':False}
def fetch(url):
    try:
        with urllib.request.urlopen(url,timeout=12) as r:
            return {'url':url,'status':r.status,'sha256':hashlib.sha256(r.read()).hexdigest()}
    except urllib.error.HTTPError as e: return {'url':url,'status':e.code}
    except Exception as e: return {'url':url,'error':type(e).__name__}
ports=[22,80,443,8443,7881,5349,7880,8001,11434]
urls=[f'https://{host}:8443/',f'https://{host}:8443/webrtc/',f'https://{host}:8443/rtc',f'https://{host}/openapi.json',f'https://{host}/api/v1/health',f'https://{host}/api/v1/ready']
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
    tcp=list(pool.map(probe,ports));http=list(pool.map(fetch,urls))
tls=[]
for port in [443,8443,5349]:
    with socket.create_connection((host,port),timeout=8) as connection:
        with ssl.create_default_context().wrap_socket(connection,server_hostname=host) as secured:
            cert=secured.getpeercert()
            tls.append({'port':port,'verified':True,'protocol':secured.version(),'expires':cert['notAfter'],'san':cert['subjectAltName']})
result={'checked_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'vantage':'Windows computer outside VPS','tcp':tcp,'http':http,'tls':tls}
Path('output/webrtc-20261023/09-external-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
