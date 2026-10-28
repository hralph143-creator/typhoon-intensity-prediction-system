const { chromium } = require('../frontend/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

async function main() {
  const base=process.env.APP_URL||'http://127.0.0.1:5173';const apiBase=process.env.API_URL||'http://127.0.0.1:8000';
  const output=path.resolve(__dirname,'../logs/browser-qa-phase7');fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  const api=async url=>(await (await page.request.get(`${apiBase}/api${url}`)).json()).data;
  try {
    const era=await api('/era5/samples/statistics');assert.equal(era.spatiotemporal_samples,7);assert.deepEqual(era.splits,{test:2,train:3,validation:2});
    const matches=await api('/fusion/matches');assert.equal(matches.counts.confirmed,308);
    const fair=await api('/ml/comparison/common-test');assert.equal(fair.items.length,5);assert.equal(fair.formal_ranking_allowed,false);
    await page.goto(`${base}/wind-field`);await page.getByRole('heading',{name:'ERA5 近海面风场'}).waitFor();await page.waitForFunction(()=>document.querySelectorAll('.status-card .stat-value')[2]?.textContent?.trim()==='7');await page.getByRole('tab',{name:'批量准备'}).click();await page.getByText('6 / 6（失败 0）',{exact:true}).waitFor();await page.screenshot({path:path.join(output,'era5-batch.png'),fullPage:true});
    await page.goto(`${base}/training`);await page.getByText('训练数据审计',{exact:true}).waitFor({timeout:60000});await page.locator('.training-form .el-select').first().click();await page.getByRole('option',{name:'SAF-Net',exact:true}).click();await page.getByText('小样本试验',{exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'开始真实训练'}).isDisabled(),false);await page.screenshot({path:path.join(output,'safnet-training.png'),fullPage:true});
    await page.goto(`${base}/evaluation`);await page.getByText('五模型共同测试集',{exact:true}).waitFor();await page.getByText('共同样本 2 条 · 独立事件 2 个 · 预测时效 6 小时',{exact:true}).waitFor();await page.getByText('safnet',{exact:true}).first().waitFor();await page.screenshot({path:path.join(output,'common-comparison.png'),fullPage:true});
    await page.goto(`${base}/prediction`);await page.getByRole('heading',{name:'强度预测',level:2}).waitFor();await page.getByText('SAF-Net 尚未完成真实数据训练。',{exact:true}).waitFor({state:'detached'});
    assert.deepEqual(errors,[]);
    const report={checked_at:new Date().toISOString(),browser:'Microsoft Edge (Playwright msedge channel)',era5:era.splits,match_counts:matches.counts,common_test:{status:fair.status,samples:fair.sample_count,events:fair.event_count,models:fair.items.length},console_errors:errors};fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
  } finally {await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1});
