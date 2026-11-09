/* Microsoft Edge end-to-end acceptance for Phase 9. */
const { chromium } = require('../frontend/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

async function main() {
  const root = path.resolve(__dirname, '..');
  const output = path.join(root, 'docs', 'screenshots', 'phase9');
  fs.mkdirSync(output, { recursive: true });
  const base = process.env.APP_URL || 'http://127.0.0.1:5173';
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 900 }, acceptDownloads: true });
  const page = await context.newPage();
  const checks = [], errors = [], failedResponses = [];
  page.on('pageerror', error => errors.push(String(error)));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('response', response => { if (response.status() >= 500) failedResponses.push(`${response.status()} ${response.url()}`); });
  const check = (name, condition) => { assert.ok(condition, name); checks.push(name); };
  const api = async route => {
    const response = await context.request.get(`${base}/api${route}`);
    assert.ok(response.ok(), `${route} returned ${response.status()}`);
    return (await response.json()).data;
  };
  const shot = async name => {
    await page.evaluate(() => document.body.classList.add('qa-capture'));
    await page.addStyleTag({ content: 'body.qa-capture .sidebar,body.qa-capture .topbar{position:relative!important;top:auto!important}' });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(120);
    const result = await page.screenshot({ path: path.join(output, name), fullPage: true });
    await page.evaluate(() => document.body.classList.remove('qa-capture'));
    return result;
  };
  const noOverflow = async label => {
    const layout = await page.evaluate(() => ({ width: window.innerWidth, scrollWidth: document.documentElement.scrollWidth, offenders: [...document.querySelectorAll('body *')].filter(el => el.getBoundingClientRect().right > window.innerWidth + 2).slice(0, 8).map(el => `${el.tagName}.${el.className}`) }));
    if (layout.scrollWidth > layout.width + 2) console.error('overflow', label, layout);
    check(`${label}无横向页面溢出`, layout.scrollWidth <= layout.width + 2);
  };

  try {
    const audit = await api('/era5/samples/audit');
    const common = await api('/ml/comparison/common-test');
    const models = await api('/ml/models');
    const experiments = await api('/ml/experiments');
    check('正式ERA5样本门禁通过', audit.formal_training_allowed && audit.samples === 90 && audit.events === 32);
    check('五模型共同测试集可用', common.status === 'formal' && common.items.length === 5);
    check('模型与实验记录完整', models.length >= 5 && experiments.length >= 10);

    await page.goto(base, { waitUntil: 'networkidle' });
    await page.getByRole('heading', { name: '系统运行概览' }).waitFor();
    const homeValues = await page.locator('.overview-grid .stat-value').allTextContents();
    check('首页展示双源和ERA5真实规模', homeValues[0] === '366' && homeValues[1] === '342' && homeValues[2] === '90');
    await noOverflow('首页'); await shot('01-home.png');

    await page.goto(`${base}/history`, { waitUntil: 'networkidle' });
    await page.getByPlaceholder('如 HAIYAN').fill('MERANTI');
    await page.getByRole('button', { name: '查询', exact: true }).click();
    await page.getByText('MERANTI', { exact: true }).first().waitFor();
    check('历史台风检索有效', await page.getByText('MERANTI', { exact: true }).count() > 0);
    await noOverflow('历史档案'); await shot('02-history-search.png');
    await page.getByRole('button', { name: '查看详情' }).first().click();
    await page.waitForURL(/\/history\/\d+/); await page.locator('canvas').first().waitFor();
    await page.locator('.track-map').waitFor();
    check('详情地图与曲线已渲染', await page.locator('canvas').count() >= 1 && await page.locator('.track-map .leaflet-overlay-pane svg').count() >= 1);
    await shot('03-typhoon-detail.png');

    await page.goto(`${base}/history`, { waitUntil: 'networkidle' });
    await page.getByRole('tab', { name: '数据接入与任务' }).click();
    await page.getByRole('heading', { name: 'IBTrACS 数据接入' }).waitFor();
    check('历史数据接入入口可用', await page.getByText(/导入|数据源/).count() > 0);
    await shot('04-data-ingestion.png');

    await page.goto(`${base}/wind-field`, { waitUntil: 'networkidle' });
    await page.getByRole('heading', { name: 'ERA5 近海面风场' }).waitFor();
    await page.locator('.el-radio-button__inner').filter({ hasText: /^U10$/ }).click();
    await page.locator('.el-radio-button__inner').filter({ hasText: /^单时次$/ }).click();
    await page.locator('.wind-toolbar .el-select').last().click();
    await page.getByRole('option', { name: 't-6h', exact: true }).click();
    await page.getByText(/质量检查 通过/).waitFor();
    check('真实风场样本已渲染', await page.locator('.wind-grid canvas').count() === 1);
    await noOverflow('风场分析'); await shot('05-era5-wind-field.png');
    await page.getByRole('tab', { name: '数据源诊断' }).click();
    await page.getByText('Google ARCO-ERA5', { exact: false }).first().waitFor();
    await shot('06-era5-sources.png');

    await page.goto(`${base}/training`, { waitUntil: 'networkidle' });
    await page.getByText('训练数据审计', { exact: true }).waitFor({ timeout: 60000 });
    await page.locator('.training-form .el-select').first().click();
    await page.getByRole('option', { name: 'SAF-Net', exact: true }).click();
    await page.getByText('正式实验就绪', { exact: true }).waitFor();
    check('训练页正式门禁就绪', await page.getByText('训练 50 / 20 个事件', { exact: true }).count() === 1);
    await shot('07-model-training.png');

    await page.goto(`${base}/experiments`, { waitUntil: 'networkidle' });
    await page.getByRole('heading', { name: '模型与实验记录' }).waitFor();
    check('已保存模型权重均可核验', await page.getByText('权重可用', { exact: true }).count() >= 5);
    await noOverflow('实验记录'); await shot('08-model-records.png');

    await page.goto(`${base}/prediction`, { waitUntil: 'networkidle' });
    await page.getByText('完整时空样本', { exact: true }).waitFor({ timeout: 60000 });
    const selects = page.locator('.prediction-form .el-select');
    await selects.nth(1).click();
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').first().click();
    await page.getByRole('button', { name: '执行真实模型推理' }).click();
    await page.getByText('SAF-Net 注意力', { exact: true }).waitFor({ timeout: 60000 });
    check('真实SAF-Net推理返回预测与注意力', await page.getByText('输入风速', { exact: true }).count() === 1 && await page.locator('.attention-card canvas').count() >= 2);
    await shot('09-real-prediction.png');
    await page.locator('.attention-card').scrollIntoViewIfNeeded();
    await page.locator('.attention-card').screenshot({ path: path.join(output, '10-attention.png') });

    await page.goto(`${base}/evaluation`, { waitUntil: 'networkidle' });
    await page.getByText('五模型共同测试集', { exact: true }).waitFor({ timeout: 60000 });
    check('评估页显示五模型公平对比', await page.locator('.el-table__body tr').count() >= 5 && await page.getByText(/事件级 Bootstrap/).count() > 0);
    await shot('11-evaluation.png');

    await page.goto(`${base}/reports`, { waitUntil: 'networkidle' });
    await page.getByRole('heading', { name: '科研分析报告中心' }).waitFor();
    await page.locator('.report-form .el-select').first().click();
    await page.getByRole('option', { name: '综合科研分析报告', exact: true }).click();
    await page.getByRole('button', { name: '生成报告' }).click();
    await page.getByText('已完成', { exact: true }).first().waitFor({ timeout: 60000 });
    check('报告生成和下载入口可用', await page.getByRole('link', { name: 'HTML' }).count() > 0 && await page.getByRole('link', { name: 'PDF' }).count() > 0);
    await shot('12-reports.png');

    await page.goto(`${base}/settings`, { waitUntil: 'networkidle' });
    await page.getByRole('heading', { name: '系统设置与维护' }).waitFor();
    const beforeBackups = await api('/system/backups');
    await page.getByRole('button', { name: '创建一致性备份' }).click();
    await page.getByText('备份已创建并校验', { exact: true }).waitFor();
    await page.locator('.el-loading-mask').waitFor({ state: 'hidden' }).catch(() => {});
    const afterBackups = await api('/system/backups');
    await page.getByText('已验证', { exact: true }).first().waitFor();
    check('备份已创建且提供下载', afterBackups.length > beforeBackups.length && await page.getByRole('link', { name: '下载' }).count() > 0);
    await shot('13-settings-backup.png');

    await page.goto(`${base}/about`, { waitUntil: 'networkidle' });
    await page.getByRole('heading', { name: '关于系统' }).waitFor();
    check('关于页版本已更新', await page.getByText('0.9.0', { exact: false }).count() > 0);
    await shot('14-about.png');

    await page.setViewportSize({ width: 1366, height: 768 });
    await page.goto(base, { waitUntil: 'networkidle' }); await noOverflow('1366宽度首页'); await shot('15-responsive-home.png');
    if (errors.length) console.error('browser-errors', errors);
    if (failedResponses.length) console.error('failed-responses', failedResponses);
    check('浏览器控制台无错误', errors.length === 0);
    check('接口无服务端错误', failedResponses.length === 0);
    const report = { checked_at: new Date().toISOString(), browser: 'Microsoft Edge', viewport: ['1600x900', '1366x768'], checks, page_errors: errors, failed_responses: failedResponses, screenshots: 15 };
    fs.writeFileSync(path.join(output, 'acceptance-report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ passed: checks.length, screenshots: 15 }, null, 2));
  } finally { await browser.close(); }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
