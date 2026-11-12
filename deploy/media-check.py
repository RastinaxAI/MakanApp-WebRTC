"""Audit/harden an existing media VPS and test synthetic audio. No secrets saved."""
import argparse
import asyncio
import datetime as dt
import getpass
import json
import logging
import math
from pathlib import Path
import re
import socket
import ssl
import struct
import sys
import time
import uuid

import aiohttp
import paramiko
import yaml
from google.protobuf.json_format import MessageToDict
from livekit import api, rtc
from livekit.protocol import rtc as signal

HOST = '195.177.255.98'
URL = f'wss://{HOST}:8443'
ROOT = Path(__file__).resolve().parent.parent
logging.basicConfig(level=logging.CRITICAL)


def safe_error(exc):
    text = re.sub(r'eyJ[A-Za-z0-9_.-]+', '[REDACTED]', str(exc))
    return f'{type(exc).__name__}: {text[:200]}'


def ssh_connect(password):
    client = paramiko.SSHClient()
    client.load_host_keys(str(Path.home() / '.ssh' / 'known_hosts'))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(HOST, username='root', password=password, timeout=20,
                   look_for_keys=False, allow_agent=False)
    return client


def command(client, cmd, timeout=120):
    _, out, err = client.exec_command(cmd, timeout=timeout)
    output = out.read().decode('utf-8', 'replace')
    errors = err.read().decode('utf-8', 'replace')
    code = out.channel.recv_exit_status()
    if code:
        raise RuntimeError(f'Command exit {code}: {errors[-500:]} {output[-500:]}')
    return output + errors


def token(key, secret, room, identity, ttl=120):
    return (api.AccessToken(key, secret).with_identity(identity)
            .with_ttl(dt.timedelta(seconds=ttl))
            .with_grants(api.VideoGrants(room_join=True, room=room,
                         can_publish=True, can_subscribe=True)).to_jwt())


async def bootstrap_ice(session, key, secret, room):
    ws = await session.ws_connect(f'{URL}/rtc', params={
        'access_token': token(key, secret, room, 'synthetic-ice-probe'),
        'auto_subscribe': '0', 'sdk': 'python', 'version': '1.1.21',
        'protocol': '15',
    }, heartbeat=10)
    msg = await asyncio.wait_for(ws.receive(), 15)
    if msg.type != aiohttp.WSMsgType.BINARY:
        await ws.close()
        raise RuntimeError('No binary LiveKit join response')
    response = signal.SignalResponse()
    response.ParseFromString(msg.data)
    if not response.HasField('join'):
        await ws.close()
        raise RuntimeError('LiveKit signaling did not return a join response')
    return ws, response.join


def summarized_stats(stats):
    result = []
    for group in [stats.publisher_stats, stats.subscriber_stats]:
        data = [MessageToDict(s, preserving_proto_field_name=True) for s in group]
        pairs = [s['candidate_pair'] for s in data if 'candidate_pair' in s]
        candidates = [s['local_candidate'] for s in data if 'local_candidate' in s]
        transports = [s['transport']['transport'] for s in data if 'transport' in s]
        chosen = {s.get('selected_candidate_pair_id') for s in transports}
        for wrapper in pairs:
            pair = wrapper['candidate_pair']
            pair_id = wrapper['rtc']['id']
            if pair_id not in chosen and not pair.get('nominated'):
                continue
            local_id = pair.get('local_candidate_id')
            for cwrapper in candidates:
                candidate = cwrapper['candidate']
                cid = cwrapper['rtc']['id']
                if cid == local_id:
                    result.append({k: candidate.get(k) for k in
                                  ['candidate_type', 'protocol', 'relay_protocol']})
    return result


async def audio_case(session, admin, key, secret, mode):
    name = 'p3s-infra-' + mode + '-' + uuid.uuid4().hex[:8]
    rooms = [rtc.Room(), rtc.Room()]
    streams = []
    consume_tasks = []
    frame_count = [0, 0]
    peak = [0, 0]
    sources = []
    ws = None
    result = {'mode': mode, 'result': 'FAIL'}
    started = time.monotonic()

    async def consume(track, index):
        stream = rtc.AudioStream(track, capacity=50)
        streams.append(stream)
        async for event in stream:
            frame_count[index] += 1
            samples = event.frame.data
            peak[index] = max(peak[index], max((abs(s) for s in samples), default=0))

    for index, room in enumerate(rooms):
        @room.on('track_subscribed')
        def subscribed(track, publication, participant, index=index):
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                consume_tasks.append(asyncio.create_task(consume(track, index)))

    try:
        ws, join = await bootstrap_ice(session, key, secret, name)
        result['server_version'] = join.server_version or join.server_info.version
        result['advertised_ice_urls'] = [u for s in join.ice_servers for u in s.urls]
        config = None
        if mode != 'baseline':
            ice = []
            for server in join.ice_servers:
                urls = [u for u in server.urls if (
                    (mode == 'turn_udp' and u.startswith('turn:') and 'transport=udp' in u)
                    or (mode == 'turn_tls' and u.startswith('turns:')))]
                if urls:
                    ice.append(rtc.IceServer(urls=urls, username=server.username,
                                             password=server.credential))
            if not ice:
                raise RuntimeError('Requested relay transport was not advertised')
            config = rtc.RtcConfiguration(ice_transport_type=rtc.IceTransportType.TRANSPORT_RELAY,
                                           ice_servers=ice)
        options = rtc.RoomOptions(rtc_config=config, connect_timeout=25)
        for i, room in enumerate(rooms):
            await asyncio.wait_for(room.connect(URL, token(key, secret, name, f'synthetic-{i}'), options), 35)
        for room in rooms:
            source = rtc.AudioSource(48000, 1)
            sources.append(source)
            track = rtc.LocalAudioTrack.create_audio_track('synthetic-tone', source)
            await room.local_participant.publish_track(track, rtc.TrackPublishOptions(
                source=rtc.TrackSource.SOURCE_MICROPHONE, dtx=False))

        # Five seconds of a generated 440 Hz tone; no microphone or media file is used.
        for n in range(250):
            pcm = struct.pack('<960h', *[
                int(6000 * math.sin(2 * math.pi * 440 * (n * 960 + k) / 48000))
                for k in range(960)])
            await asyncio.gather(*[s.capture_frame(rtc.AudioFrame(pcm, 48000, 1, 960)) for s in sources])
            await asyncio.sleep(.02)
        await asyncio.gather(*[s.wait_for_playout() for s in sources])
        await asyncio.sleep(1)
        result['participants_visible'] = all(
            any(p.identity == f'synthetic-{1-i}' for p in room.remote_participants.values())
            for i, room in enumerate(rooms))
        result['received_audio_frames'] = frame_count.copy()
        result['received_nonzero_audio'] = [p > 100 for p in peak]
        result['selected_candidates'] = [summarized_stats(await room.get_rtc_stats()) for room in rooms]
        media_pass = result['participants_visible'] and all(c > 50 for c in frame_count) and all(p > 100 for p in peak)
        if mode != 'baseline':
            media_pass = media_pass and all(
                candidates and all(c.get('candidate_type') == 'RELAY' for c in candidates)
                for candidates in result['selected_candidates'])
        result['result'] = 'PASS' if media_pass else 'FAIL'
    except Exception as exc:
        result['error'] = safe_error(exc)
    finally:
        for task in consume_tasks:
            task.cancel()
        if consume_tasks:
            await asyncio.gather(*consume_tasks, return_exceptions=True)
        for stream in streams:
            await stream.aclose()
        for room in rooms:
            await room.disconnect()
        if ws:
            await ws.close()
        try:
            await admin.room.delete_room(api.DeleteRoomRequest(room=name))
        except Exception:
            pass
    result['elapsed_seconds'] = round(time.monotonic() - started, 2)
    print(json.dumps(result), flush=True)
    return result


async def tests(key, secret, modes):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as session:
        admin = api.LiveKitAPI(URL, key, secret, session=session)
        return [await audio_case(session, admin, key, secret, mode)
                for mode in modes]


async def browser_tests(key, secret, modes):
    results = []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as session:
        admin = api.LiveKitAPI(URL, key, secret, session=session)
        for mode in modes:
            name = 'p3s-browser-' + mode + '-' + uuid.uuid4().hex[:8]
            ws = None
            try:
                ws, join = await bootstrap_ice(session, key, secret, name)
                ice = []
                for server in join.ice_servers:
                    urls = [u for u in server.urls if (
                        (mode == 'turn_udp' and u.startswith('turn:') and 'transport=udp' in u)
                        or (mode == 'turn_tls' and u.startswith('turns:')))]
                    if urls:
                        ice.append({'urls': urls, 'username': server.username, 'credential': server.credential})
                payload = {'url': URL, 'mode': mode, 'ice_servers': ice,
                           'tokens': [token(key, secret, name, f'browser-synthetic-{i}') for i in range(2)]}
                proc = await asyncio.create_subprocess_exec(
                    'node',
                    str(Path(__file__).with_name('browser-media-check.cjs')),
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                output, _ = await asyncio.wait_for(proc.communicate(json.dumps(payload).encode()), 110)
                result = json.loads(output)
            except Exception as exc:
                result = {'mode': mode, 'result': 'FAIL', 'error': safe_error(exc)}
            finally:
                if ws:
                    await ws.close()
                try:
                    await admin.room.delete_room(api.DeleteRoomRequest(room=name))
                except Exception:
                    pass
            print(json.dumps(result), flush=True)
            results.append(result)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--harden', action='store_true')
    parser.add_argument('--modes', nargs='+', default=['baseline', 'turn_udp', 'turn_tls'])
    parser.add_argument('--browser', action='store_true')
    parser.add_argument('--upload-reports', action='store_true')
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    password = getpass.getpass('SSH password (not saved): ')
    client = ssh_connect(password)
    report = {'checked_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'host': HOST, 'livekit_url': URL,
              'network_scope': 'Two synthetic clients on the same external Windows host; distinct networks still require manual validation.'}
    try:
        if args.upload_reports:
            with client.open_sftp() as sftp:
                for filename in ['DEPLOYMENT_FA.txt', 'browser-verification.json', 'media-verification.json']:
                    sftp.put(str(ROOT / 'output' / filename), '/opt/makan-media/' + filename)
                    sftp.chmod('/opt/makan-media/' + filename, 0o600)
            print('REPORTS_UPLOADED', flush=True)
            return
        if args.harden:
            with client.open_sftp() as sftp:
                sftp.put(str(Path(__file__).with_name('harden-media.sh')), '/root/makan-harden-media.sh')
                sftp.chmod('/root/makan-harden-media.sh', 0o700)
            print(command(client, 'bash /root/makan-harden-media.sh'), flush=True)
            # A fresh authenticated connection confirms the SSH firewall rule.
            check = ssh_connect(password)
            print(command(check, 'systemctl stop makan-ufw-rollback.timer; echo SSH_AFTER_UFW_OK'), flush=True)
            check.close()
        password = None
        with client.open_sftp() as sftp:
            with sftp.open('/opt/makan-media/keys.yaml') as f:
                keys = yaml.safe_load(f.read())
        key, secret = next(iter(keys.items()))
        report['transport_tests'] = asyncio.run(
            browser_tests(key, secret, args.modes) if args.browser else tests(key, secret, args.modes))
        key = secret = keys = None
        report['server_status'] = command(client,
            "systemctl is-active livekit-docker makan-turn nginx; "
            "systemctl is-enabled livekit-docker makan-turn snap.certbot.renew.timer; "
            "ufw status numbered; "
            "docker ps --format '{{.Names}} {{.Image}} {{.Status}}'; "
            "openssl x509 -in /etc/letsencrypt/live/195.177.255.98/fullchain.pem -noout -dates")
        report['status'] = (('INFRA_TESTED_SINGLE_EXTERNAL_NETWORK' if len(args.modes) == 3 else 'PARTIAL_TRANSPORT_CHECKS_PASSED') if
                            all(t['result'] == 'PASS' for t in report['transport_tests'])
                            else 'INFRA_NEEDS_ATTENTION')
        out = ROOT / 'output'
        out.mkdir(exist_ok=True)
        filename = 'browser-verification.json' if args.browser else 'media-verification.json'
        (out / filename).write_text(json.dumps(report, indent=2), encoding='utf-8')
        with client.open_sftp() as sftp:
            sftp.put(str(out / filename), '/opt/makan-media/' + filename)
            sftp.chmod('/opt/makan-media/' + filename, 0o600)
        print('REPORT', report['status'], flush=True)
    finally:
        client.close()


if __name__ == '__main__':
    main()
