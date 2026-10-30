/* Edge acceptance for the Phase-8 final real-data workflow. */
const { chromium } = require('../frontend/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

async function main() {
  const output = path.resolve(__dirname, '../logs/browser-qa-phase8-final');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const base = process.env.APP_URL || 'http://127.0.0.1:5173';
  const checks = [], errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  const check = (name, value) => { assert.ok(value, name); checks.push(name); };
  const api = async route => (await (await context.request.get(`${base}/api${route}`)).json()).data;
  try {
    const audit = await api('/era5/samples/audit');
    check('最终真实数据门禁通过', audit.formal_training_allowed && audit.samples === 90 && audit.events === 32);
    check('三分区达到样本和事件目标', audit.splits.train.samples === 50 && audit.splits.train.events === 20 && audit.splits.validation.samples === 20 && audit.splits.test.samples === 20);
    const common = await api('/ml/comparison/common-test');
    check('五模型使用冻结共同测试集', common.status === 'formal' && common.sample_count === 20 && common.event_count === 6 && common.items.length === 5);
    check('SAF-Net严格按验证集选模', common.safnet_selection.criterion === 'minimum_validation_mae' && common.safnet_selection.experiment_id === '5bdba532-3774-4d72-93f0-929798be6bea');
    check('事件级Bootstrap已计算', common.bootstrap_safnet_minus_persistence.reliable && common.bootstrap_safnet_minus_persistence.resampling_unit === 'typhoon_event');

    await page.goto(`${base}/wind-field`);
    await page.getByRole('heading', { name: 'ERA5 近海面风场' }).waitFor();
    await page.getByRole('tab', { name: '样本质量' }).click();
    await page.getByText('50 / 20（还差 0 / 0）', { exact: true }).waitFor();
    check('风场页显示正式门禁和零缺口', await page.getByText('通过', { exact: true }).count() > 0);
    await page.screenshot({ path: path.join(output, 'wind-field-quality.png'), fullPage: true });

    await page.goto(`${base}/training`);
    await page.getByText('训练数据审计', { exact: true }).waitFor({ timeout: 60000 });
    await page.locator('.training-form .el-select').first().click();
    await page.getByRole('option', { name: 'SAF-Net', exact: true }).click();
    await page.getByText('正式实验就绪', { exact: true }).waitFor();
    check('训练页展示50/20/20真实样本', await page.getByText('训练 50 / 20 个事件', { exact: true }).count() === 1);
    await page.screenshot({ path: path.join(output, 'training.png'), fullPage: true });

    await page.goto(`${base}/evaluation`);
    await page.getByText('五模型共同测试集', { exact: true }).waitFor({ timeout: 60000 });
    await page.getByText('SAF-Net 正式选择与不确定性', { exact: true }).waitFor();
    check('评估页呈现五模型与Bootstrap', await page.getByText(/事件级 Bootstrap/).count() === 1 && await page.locator('.el-table__body tr').count() >= 5);
    await page.screenshot({ path: path.join(output, 'evaluation.png'), fullPage: true });

    const samples = await api('/ml/safnet/samples?limit=100');
    const sample = samples.find(item => item.split === 'test');
    const predictionResponse = await context.request.post(`${base}/api/ml/safnet/predict`, { data: { model_id: common.safnet_selection.model_id, sample_id: sample.id, include_attention: true } });
    const prediction = (await predictionResponse.json()).data;
    check('最终权重真实推理并返回注意力', predictionResponse.ok() && prediction.attention.spatial.length === 4 && prediction.attention.temporal.length >= 1);
    await page.goto(`${base}/prediction`);
    await page.getByRole('heading', { name: '强度预测', level: 2 }).waitFor();
    await page.getByText('完整时空样本', { exact: true }).waitFor({ timeout: 60000 });
    check('预测页可选完整时空样本', !(await page.getByText('SAF-Net 尚未完成真实数据训练。').isVisible()));

    await page.goto(`${base}/reports`);
    await page.getByRole('heading', { name: '科研分析报告中心' }).waitFor();
    await page.getByText('第八阶段最终科研实验验收报告', { exact: true }).first().waitFor();
    check('最终HTML/PDF报告可下载', await page.getByRole('link', { name: 'HTML' }).count() > 0 && await page.getByRole('link', { name: 'PDF' }).count() > 0);
    await page.screenshot({ path: path.join(output, 'reports.png'), fullPage: true });

    check('页面无运行异常', errors.length === 0);
    const report = { checked_at: new Date().toISOString(), browser: 'Microsoft Edge', checks, page_errors: errors, audit: { samples: audit.samples, events: audit.events, splits: audit.splits }, common_test: common.items };
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ passed: checks.length, checks }, null, 2));
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
