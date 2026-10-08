const { chromium } = require('../../../../research/browser-registration/node_modules/playwright-core');
const path = require('path');

(async()=>{
  const source=process.argv[2]||'http://127.0.0.1:8787/';
  const target=/^https?:/i.test(source)?source:`file:///${path.resolve(source).replace(/\\/g,'/')}`;
  const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  const page=await browser.newPage({viewport:{width:1365,height:1050}});
  const requests=[];page.on('request',r=>requests.push(r.url()));
  try{
    await page.goto(target,{waitUntil:'networkidle'});
    const version=await page.evaluate(()=>ScopePay.version);
    const backend=await page.evaluate(()=>ScopePay.getBackend());
    await page.locator('#good-demo').click();await page.waitForFunction(()=>Boolean(window.__lastAnalysis));
    const good={score:await page.locator('#score').innerText(),disabled:await page.locator('#sandbox-button').isDisabled(),status:await page.locator('#status').innerText(),fingerprint:await page.locator('#fingerprint').innerText(),analysis:await page.evaluate(()=>window.__lastAnalysis)};
    await page.locator('#sandbox-button').click();await page.waitForFunction(()=>document.querySelector('#order-result')?.innerText.includes('CREATED'));
    const created={text:await page.locator('#order-result').innerText(),button:await page.locator('#sandbox-button').innerText(),status:await page.locator('#status').innerText()};
    await page.locator('#sandbox-button').click();await page.waitForFunction(()=>document.querySelector('#order-result')?.innerText.includes('COMPLETED'));
    const completed={text:await page.locator('#order-result').innerText(),disabled:await page.locator('#sandbox-button').isDisabled(),status:await page.locator('#status').innerText()};
    await page.screenshot({path:'Y:/Business/orders/ScopePayAI_v0.2.0_演示完成.png',fullPage:true});
    await page.locator('#risk-demo').click();await page.waitForFunction(()=>window.__lastAnalysis?.risk===true);
    const risky={score:await page.locator('#score').innerText(),disabled:await page.locator('#sandbox-button').isDisabled(),status:await page.locator('#status').innerText(),signals:await page.locator('#signals').innerText()};
    const externalRequests=requests.filter(u=>!u.startsWith(page.url().replace(/\/$/,''))&&!u.startsWith('file:'));
    const result={target:page.url(),title:await page.title(),version,backend,good,created,completed,risky,externalRequests};
    if(version!=='0.2.0'||backend.mode!=='demo'||good.disabled||!good.status.includes('passed')||good.fingerprint.length!==64||!created.text.includes('Demo order')||!completed.disabled||!completed.status.includes('No PayPal request')||!risky.disabled||!risky.signals.includes('Remove')||externalRequests.length)throw Error(JSON.stringify(result,null,2));
    await page.screenshot({path:'Y:/Business/orders/ScopePayAI_v0.2.0_风险示例.png',fullPage:true});
    console.log(JSON.stringify(result,null,2));
  }finally{await browser.close();}
})().catch(e=>{console.error(e.stack||e);process.exit(1)});
