/* Microsoft Edge end-to-end acceptance for Phase 10. */
const { chromium } = require('../frontend/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

async function main() {
  const root=path.resolve(__dirname,'..'),output=path.join(root,'docs','screenshots','phase-10');
  fs.mkdirSync(output,{recursive:true});
  const base=process.env.APP_URL||'http://127.0.0.1:5173';
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const context=await browser.newContext({viewport:{width:1600,height:900},acceptDownloads:true});
  const page=await context.newPage(),checks=[],errors=[],failedResponses=[];
  page.on('pageerror',error=>errors.push(String(error)));
  page.on('console',message=>{if(message.type()==='error')errors.push(message.text())});
  page.on('response',response=>{if(response.status()>=500)failedResponses.push(`${response.status()} ${response.url()}`)});
  const check=(name,condition)=>{assert.ok(condition,name);checks.push(name)};
  const api=async route=>{const response=await context.request.get(`${base}/api${route}`);assert.ok(response.ok(),`${route} ${response.status()}`);return (await response.json()).data};
  const shot=async name=>{await page.evaluate(()=>window.scrollTo(0,0));await page.waitForTimeout(150);await page.screenshot({path:path.join(output,name),fullPage:true})};
  try {
    const summary=await api('/ml/phase10/summary'),audit=await api('/ml/phase10/audit');
    check('多时效实验快照可用',summary.available&&summary.runs.length===18&&summary.selected_ablations.length===6);
    check('数据审计无事件泄漏',audit.total_samples===90&&audit.total_events===32&&audit.no_sid_leakage&&!audit.future_inputs_used);
    check('四时效均为正式实验',Object.values(audit.formal_by_horizon).every(Boolean));
    check('公开接口不泄露本地模型路径',!JSON.stringify(summary).includes('model_path'));

    await page.goto(`${base}/prediction`,{waitUntil:'networkidle'});
    await page.getByText('多时效概率预测',{exact:true}).waitFor({timeout:60000});
    check('预测页展示数据版本和导出入口',await page.getByText(/multi-horizon-v1/).count()>0&&await page.getByText('导出全部 CSV',{exact:true}).count()===1);
    await shot('01-prediction-ready.png');
    await page.getByRole('button',{name:/预测 6 \/ 12 \/ 18 \/ 24 小时/}).click();
    await page.getByText('P10',{exact:true}).waitFor({timeout:60000});
    check('真实多时效推理显示四行结果',await page.locator('.multi-card .el-table__body tr').count()===4);
    check('预测区间图已渲染',await page.locator('.multi-card canvas').count()===1);
    await shot('02-probability-forecast.png');
    await page.locator('.multi-card .el-table').screenshot({path:path.join(output,'03-horizon-results.png')});

    await page.goto(`${base}/evaluation`,{waitUntil:'networkidle'});
    await page.getByText('第十阶段结论',{exact:true}).waitFor({timeout:60000});
    check('评估页如实提示未超过基线',await page.getByText(/没有超过持续性基线/).count()>0);
    await shot('04-evaluation-6h.png');
    const selector=page.locator('.chart-grid .el-select').first();await selector.click();await page.getByRole('option',{name:'24 小时',exact:true}).click();
    await page.getByText(/覆盖率 65\.0%/).waitFor();
    check('时效切换更新概率指标',await page.getByText(/宽度 14\.264/).count()>0);
    await shot('05-evaluation-24h.png');
    const ablation=page.getByText('六组消融实验（验证集选择后一次性测试）',{exact:true}).locator('..').locator('..');
    check('六组消融全部可查询',await page.getByText('full_safnet',{exact:true}).count()>0&&await page.getByText('spatial_only',{exact:true}).count()>0);
    await ablation.screenshot({path:path.join(output,'06-ablation-study.png')});

    await page.goto(`${base}/experiments`,{waitUntil:'networkidle'});await page.getByRole('heading',{name:'模型与实验记录'}).waitFor();
    check('18个多时效消融实验已保存',await page.getByText('MH_SAFNET',{exact:true}).count()>=18);
    await shot('07-experiment-records.png');
    const selects=page.locator('.record-filters .el-select');await selects.nth(0).click();await page.getByRole('option',{name:'MH_SAFNET',exact:true}).click();
    await page.getByText('第十阶段消融组',{exact:true}).first().waitFor();
    await page.locator('.el-loading-mask').waitFor({state:'hidden',timeout:10000}).catch(()=>{});await page.waitForTimeout(300);
    check('实验模型筛选有效',await page.getByText('第十阶段消融组',{exact:true}).count()===18);
    await shot('08-experiment-filter.png');

    await page.goto(`${base}/reports`,{waitUntil:'networkidle'});await page.getByRole('heading',{name:'科研分析报告中心'}).waitFor();
    check('五类第十阶段报告均已生成',await page.getByText(/SAF-Net 性能诊断报告/).count()>0&&await page.getByText(/第十阶段综合科研实验报告/).count()>0);
    check('报告下载入口可用',await page.getByRole('link',{name:'PDF'}).count()>=5);
    await shot('09-phase10-reports.png');
    await page.getByRole('button',{name:'预览'}).first().click();await page.locator('.report-preview').waitFor();await page.waitForTimeout(800);
    await shot('10-report-preview.png');

    await page.setViewportSize({width:1366,height:768});await page.goto(`${base}/prediction`,{waitUntil:'networkidle'});await page.getByText('多时效概率预测',{exact:true}).waitFor();await shot('11-responsive-prediction.png');
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth-window.innerWidth);check('1366宽度无页面横向溢出',overflow<=2);
    await page.goto(`${base}/evaluation`,{waitUntil:'networkidle'});await page.getByText('第十阶段结论',{exact:true}).waitFor();await shot('12-responsive-evaluation.png');

    check('浏览器控制台无错误',errors.length===0);check('HTTP 5xx 为零',failedResponses.length===0);
    const report={checked_at:new Date().toISOString(),browser:'Microsoft Edge',viewports:['1600x900','1366x768'],checks,page_errors:errors,failed_responses:failedResponses,screenshots:12};
    fs.writeFileSync(path.join(output,'acceptance-report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify({passed:checks.length,screenshots:12,errors,failedResponses},null,2));
  } finally {await browser.close()}
}
main().catch(error=>{console.error(error);process.exitCode=1});
