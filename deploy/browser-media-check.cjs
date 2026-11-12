// Test only: all JWTs and TURN credentials arrive on stdin and remain in memory.
const fs = require('fs');
const { chromium } = require('playwright');

async function main() {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const browser = await chromium.launch({
    channel: process.env.MAKAN_BROWSER_CHANNEL || 'chrome',
    headless: true,
    args: ['--autoplay-policy=no-user-gesture-required'],
  });
  const contexts = [];
  const results = [];
  try {
    for (let i = 0; i < 2; i++) {
      const context = await browser.newContext();
      contexts.push(context);
      const page = await context.newPage();
      await page.addInitScript(() => {
        const Original = window.RTCPeerConnection;
        window.testPeerConnections = [];
        window.RTCPeerConnection = class extends Original {
          constructor(...args) {
            super(...args);
            window.testPeerConnections.push(this);
          }
        };
      });
      await page.goto('https://195.177.255.98:8443/', {timeout: 20000});
      await page.addScriptTag({ path: require.resolve('livekit-client') });
      await page.locator('body').click();
      await page.evaluate(async ({url, token, iceServers, mode}) => {
        window.room = new LivekitClient.Room({ adaptiveStream: false, dynacast: false });
        window.remoteAudioAnalysers = [];
        window.remoteAudioSources = [];
        window.audioContext = new AudioContext();
        await window.audioContext.resume();
        window.room.on(LivekitClient.RoomEvent.TrackSubscribed, track => {
          if (track.kind !== LivekitClient.Track.Kind.Audio) return;
          const element = track.attach();
          document.body.appendChild(element);
          element.play().catch(() => {});
          const source = window.audioContext.createMediaStreamSource(new MediaStream([track.mediaStreamTrack]));
          const analyser = window.audioContext.createAnalyser();
          const silent = window.audioContext.createGain();
          silent.gain.value = 1;
          source.connect(analyser).connect(silent).connect(window.audioContext.destination);
          window.remoteAudioAnalysers.push(analyser);
          window.remoteAudioSources.push(source, silent);
        });
        const rtcConfig = mode === 'baseline' ? {} : {iceTransportPolicy: 'relay', iceServers};
        await window.room.connect(url, token, {rtcConfig, peerConnectionTimeout: 25000});
        await window.room.startAudio();
        const tone = window.audioContext.createOscillator();
        tone.frequency.value = 440;
        const gain = window.audioContext.createGain();
        gain.gain.value = .2;
        const dest = window.audioContext.createMediaStreamDestination();
        window.localAudioAnalyser = window.audioContext.createAnalyser();
        tone.connect(gain).connect(window.localAudioAnalyser).connect(dest);
        window.syntheticAudioNodes = [tone, gain, dest];
        tone.start();
        await window.room.localParticipant.publishTrack(dest.stream.getAudioTracks()[0], {
          name: 'synthetic-tone', source: LivekitClient.Track.Source.Microphone, dtx: false,
        });
      }, { url: input.url, token: input.tokens[i], iceServers: input.ice_servers, mode: input.mode });
    }
    await new Promise(resolve => setTimeout(resolve, 6000));
    for (const context of contexts) {
      const page = context.pages()[0];
      results.push(await page.evaluate(async () => {
        const selectedCandidates = [];
        let bytesReceived = 0, packetsReceived = 0, energy = 0;
        for (const pc of window.testPeerConnections) {
          const stats = await pc.getStats();
          stats.forEach(stat => {
            if (stat.type === 'transport' && stat.selectedCandidatePairId) {
              const pair = stats.get(stat.selectedCandidatePairId);
              const local = stats.get(pair.localCandidateId);
              selectedCandidates.push({candidate_type: local.candidateType,
                protocol: local.protocol, relay_protocol: local.relayProtocol || null});
            }
            if (stat.type === 'inbound-rtp' && stat.kind === 'audio') {
              bytesReceived += stat.bytesReceived || 0;
              packetsReceived += stat.packetsReceived || 0;
              energy += stat.totalAudioEnergy || 0;
            }
          });
        }
        const receivedTone = window.remoteAudioAnalysers.some(analyser => {
          const samples = new Float32Array(analyser.fftSize);
          analyser.getFloatTimeDomainData(samples);
          return samples.some(sample => Math.abs(sample) > .001);
        });
        const localSamples = new Float32Array(window.localAudioAnalyser.fftSize);
        window.localAudioAnalyser.getFloatTimeDomainData(localSamples);
        return {remote_participants: window.room.remoteParticipants.size,
          audio_context_state: window.audioContext.state,
          audio_context_time: window.audioContext.currentTime,
          remote_audio_tracks: window.remoteAudioAnalysers.length,
          generated_nonzero_audio: localSamples.some(sample => Math.abs(sample) > .001),
          bytes_received: bytesReceived, packets_received: packetsReceived,
          nonzero_audio: energy > 0 || receivedTone, selected_candidates: selectedCandidates};
      }));
    }
    const pass = results.every(r => r.remote_participants >= 1 && r.bytes_received > 1000 &&
      r.packets_received > 50 && r.nonzero_audio && (input.mode === 'baseline' ||
        (r.selected_candidates.length && r.selected_candidates.every(c => c.candidate_type === 'relay'))));
    process.stdout.write(JSON.stringify({client: 'Chrome', sdk: 'livekit-client@2.23.0',
      mode: input.mode, result: pass ? 'PASS' : 'FAIL', clients: results}));
  } catch (e) {
    process.stdout.write(JSON.stringify({client: 'Chrome', mode: input.mode,
      result: 'FAIL', error: String(e.message || e).replace(/eyJ[A-Za-z0-9_.-]+/g, '[REDACTED]').slice(0, 180)}));
  } finally {
    for (const context of contexts) {
      for (const page of context.pages()) {
        await page.evaluate(async () => {
          if (window.room) await window.room.disconnect();
          if (window.audioContext) await window.audioContext.close();
        }).catch(() => {});
      }
    }
    await browser.close();
  }
}
main().catch(() => { process.stdout.write(JSON.stringify({result:'FAIL', error:'Browser test runner failed'})); process.exitCode = 1; });
