#!/usr/bin/env python3
"""Root-only diagnostic invitations. Does not grant application user authorization."""
import argparse
import base64
import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time
import yaml

def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode()

def main():
    parser=argparse.ArgumentParser(description='Create two short-lived invitations to a private WebRTC diagnostic room.')
    parser.add_argument('--minutes',type=int,default=10,choices=range(1,31),metavar='1..30')
    parser.add_argument('--json',action='store_true',help='Machine-readable output; contains private invitation tokens.')
    args=parser.parse_args()
    if os.geteuid()!=0:
        parser.exit(1,'Run as root: invitations require the server API key.\n')
    keys=yaml.safe_load(Path('/opt/makan-media/keys.yaml').read_text())
    key,secret=next(iter(keys.items()))
    now=int(time.time())
    room='diagnostic-'+secrets.token_hex(12)
    links=[]
    for i in range(2):
        payload={'iss':key,'sub':f'diagnostic-{i+1}-'+secrets.token_hex(4),'name':f'Test {i+1}',
                 'nbf':now-5,'exp':now+args.minutes*60,
                 'video':{'roomJoin':True,'room':room,'canPublish':True,'canSubscribe':True,
                          'canPublishData':False,'canPublishSources':['camera','microphone']}}
        signing=b64(b'{"alg":"HS256","typ":"JWT"}')+'.'+b64(json.dumps(payload,separators=(',',':')).encode())
        jwt=signing+'.'+b64(hmac.new(str(secret).encode(),signing.encode(),hashlib.sha256).digest())
        links.append('https://195.177.255.98:8443/webrtc/#token='+jwt)
    result={'room':room,'expires_at_utc':datetime.datetime.fromtimestamp(now+args.minutes*60,datetime.timezone.utc).isoformat(),
            'links':links,'purpose':'private infrastructure diagnostic only'}
    if args.json:
        print(json.dumps(result))
    else:
        print('Private diagnostic room:',room)
        print('Initial join expires:',result['expires_at_utc'])
        print('Open one link per participant. Keep the links private.\n')
        for i,link in enumerate(links,1):
            print(f'Participant {i}:\n{link}\n')
        print('Token expiry limits initial join; disconnect closes your test session.')

if __name__=='__main__':
    main()
