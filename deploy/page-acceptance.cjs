const fs=require('fs');
const {chromium}=require('playwright');
const assert=require('assert');
async function main(){
  const input=JSON.parse(fs.readFileSync(0,'utf8'));
  const browser=await chromium.launch({channel:process.env.MAKAN_BROWSER_CHANNEL || 'chrome',headless:true,args:['--autoplay-policy=no-user-gesture-required']});
  const contexts=[],pages=[],result={tests:[],clients:[]};
  const record=(name,pass,detail)=>{result.tests.push({name,result:pass?'PASS':'FAIL',detail});if(!pass)throw Error(name);};
  try{
    const pageErrors=[],requestsWithTokens=[];
    for(let i=0;i<2;i++){
      const context=await browser.newContext();contexts.push(context);
      const page=await context.newPage();pages.push(page);
      page.on('pageerror',error=>pageErrors.push(error.name));
      page.on('request',request=>{if(/eyJ|access_token/.test(request.url()) && !request.url().includes('/rtc')) requestsWithTokens.push('unexpected token request');});
      const response=await page.goto(input.links[i]);
      await page.waitForFunction(()=>!!window.makanDiagnostic);
      record('page-and-fragment-'+i,response.status()===200 && new URL(page.url()).hash==='', 'HTTPS 200; invitation fragment removed');
      if(i===0){
        const h=response.headers();
        record('security-headers',h['referrer-policy']==='no-referrer' && h['cache-control']==='no-store' && !!h['content-security-policy'],'no-referrer, no-store and CSP present');
      }
      await page.locator('#join').click();
      await page.waitForFunction(()=>window.makanDiagnostic.snapshot().state==='connected',{},{timeout:35000});
    }
    await Promise.all(pages.map(p=>p.waitForFunction(()=>{const s=window.makanDiagnostic.snapshot();return s.audioBytes>1000 && s.videoFrames>20;},{},{timeout:20000})));
    for(const page of pages) result.clients.push(await page.evaluate(()=>window.makanDiagnostic.snapshot()));
    record('two-way-audio-video',result.clients.every(s=>s.state==='connected' && s.audioBytes>1000 && s.videoFrames>20 && s.remoteTracks===2),'both live pages received audio bytes and decoded video frames');
    await pages[0].locator('#mute').click();
    record('mute',await pages[0].evaluate(()=>window.makanDiagnostic.snapshot().muted),'local audio muted');
    await pages[0].locator('#mute').click();
    record('unmute',!(await pages[0].evaluate(()=>window.makanDiagnostic.snapshot().muted)),'local audio resumed');
    await pages[0].setViewportSize({width:1100,height:1300});
    await pages[0].screenshot({path:'output/webrtc-20261023/diagnostic-page-connected.png',fullPage:true});
    await pages[0].setViewportSize({width:390,height:844});
    record('mobile-layout',await pages[0].evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'390px viewport has no horizontal overflow');
    await pages[0].screenshot({path:'output/webrtc-20261023/diagnostic-page-mobile.png',fullPage:true});
    for(const page of pages){
      await page.locator('#leave').click();
      await page.waitForFunction(()=>{const s=window.makanDiagnostic.snapshot();return s.state==='disconnected'&&s.localTracks===0;});
    }
    record('disconnect-cleanup',true,'both clients disconnected and local tracks stopped');
    const context=await browser.newContext();contexts.push(context);
    const page=await context.newPage();
    await page.goto('https://195.177.255.98:8443/webrtc/');
    await page.locator('#join').click();
    record('missing-token-rejected',(await page.locator('#status').textContent()).includes('لازم'),'no connection without invitation');
    for(const [name,token] of [['invalid-signature',input.invalid_token],['expired-token',input.expired_token]]){
      await page.locator('#token').fill(token);
      await page.locator('#join').click();
      await page.waitForFunction(()=>document.getElementById('status').textContent==='اتصال برقرار نشد',{},{timeout:40000});
      record(name,(await page.evaluate(()=>window.makanDiagnostic.snapshot())).state==='disconnected','rejected; no media session remained');
    }
    record('javascript-errors',pageErrors.length===0,'no uncaught page errors in connected clients');
    record('token-http-leak',requestsWithTokens.length===0,'no token sent to static asset URLs; signaling uses its required token parameter');
    result.pass=result.tests.every(t=>t.result==='PASS');
  }catch(error){result.pass=false;result.error=String(error.message).replace(/eyJ[A-Za-z0-9_.-]+/g,'[REDACTED]').slice(0,200);
    result.debug=await Promise.all(pages.map(page=>page.evaluate(()=>({snapshot:window.makanDiagnostic?.snapshot(),status:document.getElementById('status')?.textContent,detail:document.getElementById('detail')?.textContent,stats:document.getElementById('stats')?.textContent})).catch(()=>({error:'page closed'}))));
  }
  finally{for(const c of contexts)await c.close();await browser.close();}
  process.stdout.write(JSON.stringify(result));
}
main().catch(()=>{process.stdout.write(JSON.stringify({pass:false,error:'acceptance runner failed'}));process.exitCode=1;});
