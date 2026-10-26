const { chromium } = require('../frontend/node_modules/playwright')
const fs = require('fs')
const path = require('path')

;(async()=>{
  const out=path.join(__dirname,'..','logs','browser-qa');fs.mkdirSync(out,{recursive:true})
  const browser=await chromium.launch({channel:'msedge',headless:true})
  const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[],badResponses=[]
  page.on('console',m=>{if(m.type()==='error'&&!m.text().includes('Failed to load resource'))errors.push(m.text())});page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=400&&!r.url().endsWith('/favicon.ico'))badResponses.push(`${r.status()} ${r.url()}`)})
  await page.goto('http://127.0.0.1:5173/reports',{waitUntil:'networkidle'})
  await page.getByText('科研分析报告中心').waitFor();await page.getByText('succeeded').first().waitFor()
  const iconReady=await page.locator('img.brand-mark').evaluate(image=>image.complete&&image.naturalWidth>0);if(!iconReady)throw new Error('软件图标未加载')
  const visibleMicrocopy=await page.locator('.page-heading p,.section-heading p,p.muted-note,.phase-label,.research-badge,.pending-note').evaluateAll(nodes=>nodes.filter(node=>getComputedStyle(node).display!=='none').length);if(visibleMicrocopy)throw new Error(`仍有 ${visibleMicrocopy} 处装饰性小字可见`)
  const rows=await page.locator('.el-table__row').count();if(rows<3)throw new Error(`报告记录不足：${rows}`)
  await page.getByRole('button',{name:'预览'}).first().click();await page.locator('iframe.report-preview').waitFor()
  const frame=page.frameLocator('iframe.report-preview');await frame.locator('h1').waitFor();const previewTitle=await frame.locator('h1').innerText();await page.screenshot({path:path.join(out,'phase6-reports.png'),fullPage:true})
  await page.getByRole('button',{name:'Close'}).click().catch(()=>page.keyboard.press('Escape'))
  await page.goto('http://127.0.0.1:5173/evaluation',{waitUntil:'networkidle'});await page.getByText('SAF-Net').waitFor();await page.getByText('尚无正式结果').waitFor();if(await page.locator('.page-stack > .el-alert:visible,.page-heading p:visible').count())throw new Error('评估页仍有说明小字');await page.screenshot({path:path.join(out,'phase6-evaluation.png'),fullPage:true})
  await page.goto('http://127.0.0.1:5173/settings',{waitUntil:'networkidle'});await page.getByText('系统设置与维护').waitFor();await page.getByText('第六阶段验收备份').waitFor();if(await page.locator('.page-heading p:visible,.el-card .el-alert:visible,p.body-copy:visible').count())throw new Error('设置页仍有说明小字');await page.screenshot({path:path.join(out,'phase6-settings.png'),fullPage:true})
  for(const url of ['/api/exports/workbook','/api/exports/model-comparison.png']){const response=await page.request.get('http://127.0.0.1:8000'+url);if(!response.ok())throw new Error(`${url} ${response.status()}`)}
  if(errors.length||badResponses.length)throw new Error('浏览器错误：'+[...errors,...badResponses].join(' | '))
  console.log(JSON.stringify({reports:rows,previewTitle,iconReady,visibleMicrocopy,screenshots:3,errors:0}))
  await browser.close()
})().catch(error=>{console.error(error);process.exit(1)})
