set -e
sha256sum /opt/makan-media/maintenance-20261023/Makan_WebRTC_Implementation_Report_FA_20261023.pdf
nproc
python3 - <<'PY'
import base64,hashlib,hmac,json,time,urllib.request,yaml
from pathlib import Path
keys=yaml.safe_load(Path('/opt/makan-media/keys.yaml').read_text())
key,secret=next(iter(keys.items()))
b=lambda x:base64.urlsafe_b64encode(x).rstrip(b'=').decode()
now=int(time.time())
data={'iss':key,'sub':'maintenance-check','nbf':now-5,'exp':now+30,'video':{'roomList':True}}
s=b(b'{"alg":"HS256","typ":"JWT"}')+'.'+b(json.dumps(data).encode())
token=s+'.'+b(hmac.new(str(secret).encode(),s.encode(),hashlib.sha256).digest())
request=urllib.request.Request('http://127.0.0.1:7880/twirp/livekit.RoomService/ListRooms',
    data=b'{}',headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
with urllib.request.urlopen(request,timeout=10) as response:
    rooms=json.load(response).get('rooms',[])
print('DIAGNOSTIC_ROOMS_REMAINING',sum(x.get('name','').startswith('diagnostic-') for x in rooms))
PY
