import asyncio
import datetime as dt
import getpass
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import yaml

spec=importlib.util.spec_from_file_location('checks',Path(__file__).with_name('media-check.py'))
checks=importlib.util.module_from_spec(spec);spec.loader.exec_module(checks)
sys.stdout.reconfigure(encoding='utf-8')
client=checks.ssh_connect(getpass.getpass('SSH password (not saved): '))
key=secret=None
data=None
try:
    # Invitation credentials are passed to the browser only through stdin.
    data=json.loads(checks.command(client,'/usr/local/sbin/makan-webrtc-invite --json'))
    with client.open_sftp() as ftp:
        with ftp.open('/opt/makan-media/keys.yaml') as f:
            keys=yaml.safe_load(f.read())
    key,secret=next(iter(keys.items()))
    expired=checks.token(key,secret,data['room'],'expired-diagnostic',ttl=-120)
    token=data['links'][0].split('#token=')[1]
    parts=token.split('.')
    parts[2]=('A' if parts[2][0]!='A' else 'B')+parts[2][1:]
    payload={'links':data['links'],'invalid_token':'.'.join(parts),'expired_token':expired}
    proc=subprocess.run(['node',str(Path(__file__).with_name('page-acceptance.cjs'))],input=json.dumps(payload),text=True,encoding='utf-8',capture_output=True,timeout=170)
    result=json.loads(proc.stdout)
    result['checked_at_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
    result['scope']='Two isolated Chrome contexts on one external Windows computer, with generated media.'
    Path('output/webrtc-20261023/06-page-acceptance.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
finally:
    if data and key:
        async def cleanup():
            admin=checks.api.LiveKitAPI(checks.URL,key,secret)
            try: await admin.room.delete_room(checks.api.DeleteRoomRequest(room=data['room']))
            finally: await admin.aclose()
        asyncio.run(cleanup())
    client.close()
