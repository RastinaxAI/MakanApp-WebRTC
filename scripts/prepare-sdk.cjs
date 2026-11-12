'use strict';
const fs = require('node:fs');
const path = require('node:path');

// فقط SDK و مجوز همان نسخهٔ نصب‌شده آماده می‌شوند؛ تغییری روی سرور نمی‌دهد.
const entry = require.resolve('livekit-client');
const packageRoot = path.dirname(path.dirname(entry));
const metadata = JSON.parse(fs.readFileSync(path.join(packageRoot, 'package.json'), 'utf8'));
if (metadata.version !== '2.23.0') throw new Error('Expected livekit-client 2.23.0. Run npm ci.');
const target = path.resolve(__dirname, '../deploy/webrtc-page');
const license = ['LICENSE', 'LICENSE.txt', 'LICENSE.md'].map(name => path.join(packageRoot, name)).find(file => fs.existsSync(file));
if (!license) throw new Error('SDK license file is missing.');
fs.copyFileSync(entry, path.join(target, 'livekit-client.2.23.0.js'));
fs.copyFileSync(license, path.join(target, 'SDK-LICENSE'));
console.log('Prepared SDK 2.23.0 and its license; generated files are ignored by Git.');
