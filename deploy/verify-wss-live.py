"""Check the deployed secure WebSocket endpoint using an isolated short-lived room."""
import asyncio
import datetime as dt
import getpass
import importlib.util
import json
from pathlib import Path
import sys
import uuid
import aiohttp
import yaml

spec=importlib.util.spec_from_file_location('checks',Path(__file__).with_name('media-check.py'))
checks=importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)
sys.stdout.reconfigure(encoding='utf-8')

HEALTH_SCRIPT="""python3 - <<'PY'
import hashlib,json,urllib.request,subprocess
result={'services':{},'enabled':{},'http':{}}
for name in ['nginx','livekit-docker','makan-turn','docker']:
 r=subprocess.run(['systemctl','is-active',name],capture_output=True,text=True)
 result['services'][name]=r.stdout.strip()
for name in ['livekit-docker','makan-turn','snap.certbot.renew.timer']:
 r=subprocess.run(['systemctl','is-enabled',name],capture_output=True,text=True)
 result['enabled'][name]=r.stdout.strip()
for port in [8001,18002]:
 for path in ['/api/v1/health','/api/v1/ready','/openapi.json']:
  with urllib.request.urlopen('http://127.0.0.1:'+str(port)+path,timeout=10) as response:
   result['http'][str(port)+path]={'status':response.status,'sha256':hashlib.sha256(response.read()).hexdigest()}
names=['makanapp-ai-ai-1','makanapp-ai-avalai-staging','makan-media-livekit-1','makan-turn-coturn-1','makan-ollama']
containers=json.loads(subprocess.check_output(['docker','inspect',*names]))
result['containers']={c['Name']:{'id':c['Id'],'started':c['State']['StartedAt'],'restart_count':c['RestartCount'],'health':c['State'].get('Health',{}).get('Status')} for c in containers}
result['nginx_config_valid']=subprocess.run(['nginx','-t'],capture_output=True).returncode==0
print(json.dumps(result))
PY
"""

async def test(key,secret):
    room='diagnostic-wss-'+uuid.uuid4().hex[:12]
    result={}
    ws=None
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        admin=checks.api.LiveKitAPI(checks.URL,key,secret,session=session)
        try:
            async with session.get('https://195.177.255.98:8443/') as response:
                result['https_status']=response.status
                result['https_body']=(await response.text()).strip()
            ws=await session.ws_connect(checks.URL+'/rtc',params={
                'access_token':checks.token(key,secret,room,'wss-verification',ttl=90),
                'auto_subscribe':'0','sdk':'python','version':'1.1.21','protocol':'15'},heartbeat=10)
            result['websocket_upgrade_status']=ws._response.status
            message=await asyncio.wait_for(ws.receive(),15)
            signal=checks.signal.SignalResponse()
            if message.type==aiohttp.WSMsgType.BINARY:
                signal.ParseFromString(message.data)
            result['livekit_join_received']=signal.HasField('join')
            result['tls_validation']='Enabled, default system trust; IP hostname verified'
            await ws.close();ws=None
            try:
                invalid=await session.ws_connect(checks.URL+'/rtc',params={'access_token':'invalid','sdk':'python','protocol':'15'})
                await invalid.close()
                result['invalid_token_rejected']=False
            except aiohttp.WSServerHandshakeError as exc:
                result['invalid_token_status']=exc.status
                result['invalid_token_rejected']=exc.status in (401,403)
        finally:
            if ws:await ws.close()
            try:
                await admin.room.delete_room(checks.api.DeleteRoomRequest(room=room))
                result['temporary_room_deleted']=True
            except Exception as exc:
                result['temporary_room_deleted']=False
                result['cleanup_error']=checks.safe_error(exc)
    return result

def main():
    client=checks.ssh_connect(getpass.getpass('SSH password (not saved): '))
    result={'checked_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'url':checks.URL,
            'vantage':'External Windows computer; verified SSH inspection on VPS','configuration_changed':False}
    try:
        before=json.loads(checks.command(client,HEALTH_SCRIPT))
        print('SSH_OK; services:',json.dumps(before['services']),flush=True)
        print('ENABLED:',json.dumps(before['enabled']),flush=True)
        if not before['nginx_config_valid'] or any(x!='active' for x in before['services'].values()):
            raise RuntimeError('Existing services require review before continuing')
        with client.open_sftp() as ftp:
            with ftp.open('/opt/makan-media/keys.yaml') as source:
                keys=yaml.safe_load(source.read())
        key,secret=next(iter(keys.items()))
        result['wss']=asyncio.run(test(key,secret))
        after=json.loads(checks.command(client,HEALTH_SCRIPT))
        result['server_status']=after
        result['fastapi_responses_unchanged']=before['http']==after['http']
        result['containers_unchanged']=before['containers']==after['containers']
        result['pass']=(result['wss'].get('websocket_upgrade_status')==101 and
            result['wss'].get('livekit_join_received') and result['wss'].get('invalid_token_rejected') and
            result['wss'].get('temporary_room_deleted') and result['fastapi_responses_unchanged'] and result['containers_unchanged'])
        destination=Path('output/webrtc-20261023')/('wss-live-verification-'+dt.datetime.now(dt.timezone.utc).strftime('%H%M%S')+'.json')
        destination.write_text(json.dumps(result,indent=2),encoding='utf-8')
        with client.open_sftp() as ftp:
            remote='/opt/makan-media/maintenance-20261023/'+destination.name
            ftp.put(str(destination),remote);ftp.chmod(remote,0o600)
        print(json.dumps(result,indent=2),flush=True)
        print('EVIDENCE',str(destination.resolve()),flush=True)
        if not result['pass']:sys.exit(1)
    finally:
        client.close()

if __name__=='__main__':
    main()
