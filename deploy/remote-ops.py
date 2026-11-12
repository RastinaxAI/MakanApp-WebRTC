"""Run a reviewed remote shell script with host-key verification; never save SSH password."""
import getpass
import pathlib
import re
import sys
import paramiko

sys.stdout.reconfigure(encoding='utf-8')
client = paramiko.SSHClient()
client.load_host_keys(str(pathlib.Path.home() / '.ssh' / 'known_hosts'))
client.set_missing_host_key_policy(paramiko.RejectPolicy())
password = getpass.getpass('SSH password (not saved): ')
try:
    client.connect('195.177.255.98', username='root', password=password,
                   look_for_keys=False, allow_agent=False, timeout=25)
    password = None
    script = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8-sig')
    stdin, stdout, stderr = client.exec_command('bash -s', timeout=180)
    stdin.write(script.replace('\r\n', '\n'))
    stdin.channel.shutdown_write()
    for line in stdout:
        print(line, end='', flush=True)
    error = stderr.read().decode('utf-8', 'replace')
    if error:
        print(error, file=sys.stderr, flush=True)
    code = stdout.channel.recv_exit_status()
    print(f'REMOTE_EXIT={code}', flush=True)
    sys.exit(code)
finally:
    client.close()
