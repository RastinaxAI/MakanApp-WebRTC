"""Fresh isolated diagnostic rooms; no changes to existing API or media configuration."""
import asyncio
import datetime as dt
import getpass
import json
from pathlib import Path
import sys
import uuid
import importlib.util
import aiohttp
import yaml

spec = importlib.util.spec_from_file_location('media_check', Path(__file__).with_name('media-check.py'))
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)

async def browser_case(admin, session, key, secret, mode):
    name = 'diagnostic-20261023-' + mode + '-' + uuid.uuid4().hex[:8]
    ws = None
    try:
        ws, join = await checks.bootstrap_ice(session, key, secret, name)
        ice = []
        for server in join.ice_servers:
            urls = [u for u in server.urls if (
                (mode == 'turn_udp' and u.startswith('turn:') and 'transport=udp' in u)
                or (mode == 'turn_tls' and u.startswith('turns:')))]
            if urls:
                ice.append({'urls': urls, 'username': server.username, 'credential': server.credential})
        if mode != 'baseline' and not ice:
            raise RuntimeError('Requested relay transport was not advertised')
        payload = {'url': checks.URL, 'mode': mode, 'ice_servers': ice,
                   'tokens': [checks.token(key, secret, name, f'av-client-{i}') for i in range(2)]}
        proc = await asyncio.create_subprocess_exec('node', str(Path(__file__).with_name('browser-av-check.cjs')),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        output, errors = await asyncio.wait_for(proc.communicate(json.dumps(payload).encode()), 110)
        return json.loads(output)
    except Exception as exc:
        return {'mode':mode,'result':'FAIL','error':checks.safe_error(exc)}
    finally:
        if ws:
            await ws.close()
        await admin.room.delete_room(checks.api.DeleteRoomRequest(room=name))

async def run(key, secret):
    result=[]
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as session:
        admin=checks.api.LiveKitAPI(checks.URL,key,secret,session=session)
        for mode in ['baseline','turn_udp','turn_tls']:
            entry=await browser_case(admin,session,key,secret,mode)
            result.append(entry)
            print(json.dumps(entry),flush=True)
    return result

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    ssh=checks.ssh_connect(getpass.getpass('SSH password (not saved): '))
    try:
        with ssh.open_sftp() as ftp:
            with ftp.open('/opt/makan-media/keys.yaml') as source:
                keys=yaml.safe_load(source.read())
        key,secret=next(iter(keys.items()))
        results=asyncio.run(run(key,secret))
        report={'checked_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(), 'url':checks.URL,
                'scope':'Two isolated Chrome contexts on one external Windows host; generated audio and video, no microphone or camera.',
                'tests':results,'pass':all(x['result']=='PASS' for x in results)}
        dest=Path('output/webrtc-20261023')
        dest.mkdir(parents=True,exist_ok=True)
        (dest/'03-fresh-av-tests.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('FRESH_AV_TESTS_COMPLETE',report['pass'],flush=True)
    finally:
        ssh.close()

if __name__=='__main__':
    main()
