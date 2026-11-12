'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let invitationToken = new URLSearchParams(location.hash.slice(1)).get('token') || '';
  // Fragments never reach HTTP access logs. Remove before loading the SDK.
  if (location.hash) history.replaceState(null, '', location.pathname);
  $('token').value = invitationToken;
  let room = null, audioContext = null, animationTimer = null, statsTimer = null;
  let busy = false, muted = false, stream = null, localTracks = [], remoteTracks = new Set();
  let audioBytes = 0, videoFrames = 0;
  const sdkReady = new Promise((resolve,reject) => {
    const script = document.createElement('script');
    script.src = 'livekit-client.2.23.0.js';
    script.onload = resolve;
    script.onerror = () => reject(new Error('sdk'));
    document.head.appendChild(script);
  });
  sdkReady.catch(() => status('خطا در بارگذاری کتابخانه', 'صفحه را دوباره بارگذاری کنید.', 'error'));
  function status(title, detail, type='') {
    $('status').textContent = title; $('detail').textContent = detail;
    $('lamp').className = type;
  }
  function controls(connected=false) {
    $('join').disabled = busy || connected;
    $('leave').disabled = !connected;
    $('mute').disabled = !connected;
    $('source').disabled = busy || connected;
    $('token').disabled = busy || connected;
  }
  function placeholder(id, text) {
    $(id).replaceChildren(); const span=document.createElement('span');
    span.textContent=text; $(id).appendChild(span);
  }
  function attach(track, local) {
    const element=track.attach();
    element.autoplay=true; element.playsInline=true;
    if (track.kind === 'video') {
      if (local) element.muted=true;
      const box=$(local?'local':'remote');
      box.querySelectorAll('span').forEach(x=>x.remove());
      box.appendChild(element);
    } else if (!local) {
      element.hidden=true; document.body.appendChild(element);
      element.play().catch(()=>status('متصل؛ پخش صدا نیاز به لمس دارد', 'یک بار روی صفحه بزنید.', 'connected'));
    }
  }
  function detach(track) {
    track.detach().forEach(element=>element.remove());
  }
  async function updateStats() {
    let audio=0,frames=0;
    for (const track of remoteTracks) {
      const stats=await track.getRTCStatsReport();
      if (stats) stats.forEach(s=>{
        if(s.type==='inbound-rtp' && s.kind==='audio') audio+=s.bytesReceived||0;
        if(s.type==='inbound-rtp' && s.kind==='video') frames+=s.framesDecoded||0;
      });
    }
    audioBytes=audio; videoFrames=frames;
    $('stats').textContent=`Audio: ${audio.toLocaleString('en-US')} bytes · Video: ${frames.toLocaleString('en-US')} frames`;
    if(room && room.state==='connected') {
      const count=room.remoteParticipants.size;
      status('متصل به اتاق', count ? `تعداد شرکت‌کنندهٔ مقابل: ${count}؛ دریافت رسانه را در شمارنده بررسی کنید.` : 'اتصال برقرار است؛ لینک دوم را در دستگاه دیگر باز کنید.', 'connected');
    }
  }
  async function clean() {
    clearInterval(animationTimer); clearInterval(statsTimer);
    animationTimer=statsTimer=null;
    if(room) { const previous=room;room=null; await previous.disconnect().catch(()=>{}); }
    for(const track of localTracks) { detach(track); track.stop(); }
    localTracks=[];
    for(const track of remoteTracks) detach(track);
    remoteTracks.clear();
    if(stream) stream.getTracks().forEach(t=>t.stop());
    stream=null;
    if(audioContext) await audioContext.close().catch(()=>{});
    audioContext=null; muted=false; $('mute').textContent='قطع میکروفون';
    placeholder('local','اتصال پایان یافته است'); placeholder('remote','منتظر نفر دوم');
    controls(false);
  }
  async function syntheticTracks() {
    audioContext=new AudioContext(); await audioContext.resume();
    const tone=audioContext.createOscillator(), gain=audioContext.createGain();
    const dest=audioContext.createMediaStreamDestination();
    tone.frequency.value=440;gain.gain.value=.06;tone.connect(gain).connect(dest);tone.start();
    const canvas=document.createElement('canvas');canvas.width=640;canvas.height=360;
    const ctx=canvas.getContext('2d');let frame=0;
    function draw(){ctx.fillStyle=`hsl(${(frame++*.6)%360},55%,25%)`;ctx.fillRect(0,0,640,360);ctx.fillStyle='#fff';ctx.font='32px sans-serif';ctx.fillText('MAKAN WebRTC',30,160);ctx.font='22px sans-serif';ctx.fillText('Synthetic frame '+frame,30,205);}
    draw();animationTimer=setInterval(draw,100);
    stream=new MediaStream([...dest.stream.getAudioTracks(),...canvas.captureStream(10).getVideoTracks()]);
    return [new LivekitClient.LocalAudioTrack(stream.getAudioTracks()[0]),new LivekitClient.LocalVideoTrack(stream.getVideoTracks()[0])];
  }
  async function join() {
    if(busy || room) return;
    invitationToken=$('token').value.trim()||invitationToken;
    if(!/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(invitationToken)) {
      status('توکن دعوت لازم است','از مدیر سرور لینک دعوت معتبر بگیرید.','error'); return;
    }
    busy=true;controls(false);status('در حال اتصال','برقراری ارتباط امن با سرور رسانه…');
    try {
      await sdkReady;
      const source=$('source').value;
      // Ask for device permissions while handling the explicit Join action.
      localTracks=source==='synthetic' ? await syntheticTracks() : await LivekitClient.createLocalTracks({audio:true,video:source==='devices'});
      // Keep diagnostic video flowing while its preview is below the fold.
      room=new LivekitClient.Room({adaptiveStream:false,dynacast:false});
      room.on(LivekitClient.RoomEvent.TrackSubscribed,track=>{remoteTracks.add(track);attach(track,false);});
      room.on(LivekitClient.RoomEvent.TrackUnsubscribed,track=>{remoteTracks.delete(track);detach(track);});
      room.on(LivekitClient.RoomEvent.Disconnected,()=>{
        if(room){clean().then(()=>status('اتصال بسته شد','برای ورود مجدد، توکن باید هنوز معتبر باشد.'));}
      });
      room.on(LivekitClient.RoomEvent.Reconnecting,()=>status('در حال اتصال مجدد','شبکه در حال بازیابی است…'));
      await room.connect('wss://195.177.255.98:8443',invitationToken,{peerConnectionTimeout:25000});
      await room.startAudio();
      for(const track of localTracks){
        const audio=track.kind==='audio';
        await room.localParticipant.publishTrack(track,{source:audio?LivekitClient.Track.Source.Microphone:LivekitClient.Track.Source.Camera,dtx:false,videoCodec:'vp8',simulcast:false});
        if(!audio) attach(track,true);
      }
      $('token').value='';
      statsTimer=setInterval(()=>updateStats().catch(()=>{}),1000);
      status('متصل به اتاق','لینک دوم را روی دستگاه دیگر باز کنید.','connected');
    } catch(error) {
      const denied=error && ['NotAllowedError','NotFoundError','NotReadableError'].includes(error.name);
      await clean();
      status(denied?'دسترسی به میکروفون یا دوربین ممکن نشد':'اتصال برقرار نشد',denied?'مجوز مرورگر و اتصال دستگاه را بررسی کنید؛ یا حالت مصنوعی را انتخاب کنید.':'اعتبار لینک، ساعت دستگاه و شبکه را بررسی کنید. برای توکن منقضی، دعوت تازه بسازید.','error');
    } finally {busy=false;controls(!!room);}
  }
  $('join').addEventListener('click',join);
  $('leave').addEventListener('click',async()=>{busy=true;await clean();busy=false;controls();status('از اتاق خارج شدید','رسانهٔ محلی متوقف و ارتباط بسته شد.');});
  $('mute').addEventListener('click',async()=>{
    muted=!muted;
    for(const track of localTracks.filter(t=>t.kind==='audio')) await (muted?track.mute():track.unmute());
    $('mute').textContent=muted?'وصل میکروفون':'قطع میکروفون';
  });
  document.addEventListener('click',()=>{if(room)room.startAudio().catch(()=>{});});
  window.addEventListener('pagehide',()=>{if(stream)stream.getTracks().forEach(t=>t.stop());if(room)room.disconnect();});
  // Read-only diagnostics for repeatable acceptance tests; no invitation token exposed.
  window.makanDiagnostic={snapshot:()=>({state:room?.state||'disconnected',audioBytes,videoFrames,remoteTracks:remoteTracks.size,localTracks:localTracks.length,muted})};
})();
