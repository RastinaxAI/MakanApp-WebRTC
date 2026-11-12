"""Authenticated, verified SSH session. Password is requested once and never persisted."""
import datetime
import getpass
import json
import pathlib
import re
import sys
import paramiko

sys.stdout.reconfigure(encoding='utf-8')
client = paramiko.SSHClient()
client.load_host_keys(str(pathlib.Path.home() / '.ssh' / 'known_hosts'))
client.set_missing_host_key_policy(paramiko.RejectPolicy())
password = getpass.getpass('SSH password (not saved): ')
client.connect('195.177.255.98', username='root', password=password,
               look_for_keys=False, allow_agent=False, timeout=25)
password = None
client.get_transport().set_keepalive(20)
logdir = pathlib.Path('output/webrtc-20261023')
logdir.mkdir(parents=True, exist_ok=True)
print('SESSION_READY', flush=True)
try:
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if request.get('action') == 'exit':
                break
            if request.get('action') == 'upload':
                with client.open_sftp() as ftp:
                    ftp.put(request['local'], request['remote'])
                    ftp.chmod(request['remote'], int(request.get('mode', '600'), 8))
                print('UPLOAD_OK', request['remote'], flush=True)
                continue
            if request.get('action') == 'download':
                with client.open_sftp() as ftp:
                    ftp.get(request['remote'], request['local'])
                print('DOWNLOAD_OK', request['local'], flush=True)
                continue
            script = (pathlib.Path(request['script']).read_text(encoding='utf-8-sig')
                      if 'script' in request else request['command'])
            stdin, stdout, stderr = client.exec_command('bash -s', timeout=request.get('timeout', 180))
            stdin.write(script.replace('\r\n', '\n'))
            stdin.channel.shutdown_write()
            output = stdout.read().decode('utf-8', 'replace')
            errors = stderr.read().decode('utf-8', 'replace')
            code = stdout.channel.recv_exit_status()
            output = re.sub(r'eyJ[A-Za-z0-9_.-]+', '[REDACTED_JWT]', output)
            result = dict(label=request.get('label', 'command'), at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                          exit_code=code, stdout=output, stderr=errors)
            if request.get('label'):
                (logdir / (request['label'] + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(output, end='', flush=True)
            if errors:
                print(errors, file=sys.stderr, flush=True)
            print('COMMAND_COMPLETE', result['label'], code, flush=True)
        except Exception as exc:
            print('SESSION_ERROR', type(exc).__name__, str(exc)[:300], flush=True)
finally:
    client.close()
