/* Real browser checks against the running app and real business database. */
const { chromium } = require('../frontend/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

async function main() {
  const output = path.resolve(__dirname, '../logs/browser-qa');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL || 'msedge', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } });
  const page = await context.newPage();
  const errors = [];
  const checks = [];
  page.on('pageerror', error => errors.push(String(error)));
  const check = (name, result) => { assert.ok(result, name); checks.push(name); };
  const base = process.env.APP_URL || 'http://127.0.0.1:5173';
  try {
    const stats = (await (await context.request.get(`${base}/api/typhoons/statistics`)).json()).data;
    check('真实数据库已导入且年份覆盖2014—2025', stats.observation_count > 0 && stats.years.includes(2014) && stats.years.includes(2025));
    await page.goto(base);
    await page.getByRole('heading', { name: '系统运行概览' }).waitFor();
    await page.locator('.stat-value').first().filter({ hasText: String(stats.typhoon_count) }).waitFor();
    check('首页年度统计图实际渲染', await page.locator('.data-chart canvas').count() > 0);
    await page.screenshot({ path: path.join(output, 'home.png'), fullPage: true });

    await page.getByRole('menuitem', { name: '历史台风数据' }).click();
    await page.getByPlaceholder('如 HAIYAN').fill('MERANTI');
    const queryResponse = page.waitForResponse(r => r.url().includes('/api/typhoons?') && r.url().includes('name=MERANTI'));
    await page.getByRole('button', { name: '查询', exact: true }).click();
    const queryData = (await (await queryResponse).json()).data;
    check('名称筛选请求真实API并返回匹配事件', queryData.total > 0 && queryData.items.every(item => item.name.includes('MERANTI')));
    await page.locator('.el-table__body-wrapper').getByText('MERANTI', { exact: true }).first().waitFor();
    await page.screenshot({ path: path.join(output, 'history.png'), fullPage: true });
    await page.getByRole('button', { name: '查看详情' }).first().click();
    await page.getByLabel('真实台风历史路径地图').waitFor();
    await page.locator('.leaflet-overlay-pane path').first().waitFor();
    check('Leaflet绘制真实路径与起终点', await page.locator('.leaflet-overlay-pane path').count() > 5 && await page.getByText('起点', { exact: true }).count() > 0);
    check('风速气压曲线实际渲染', await page.locator('.data-chart canvas').count() > 0);
    const before = await page.locator('.selected-observation strong').innerText();
    await page.getByRole('button', { name: '下一时次' }).click();
    const after = await page.locator('.selected-observation strong').innerText();
    check('时次按钮联动选中记录与表格', before !== after && (await page.locator('tr.current-row').count()) === 1);
    await page.getByRole('slider').focus();
    await page.keyboard.press('End');
    check('滑块移动到终点', await page.getByRole('button', { name: '下一时次' }).isDisabled());
    // Click a marker using its actual SVG bounding box; the tooltip and time selection must respond.
    const endTime = await page.locator('.selected-observation strong').innerText();
    const marker = page.locator('.leaflet-overlay-pane path.leaflet-interactive').nth(3);
    await marker.dispatchEvent('mouseover');
    await page.waitForFunction(previous => document.querySelector('.selected-observation strong')?.textContent !== previous, endTime);
    check('地图观测点可联动时次', (await page.locator('.selected-observation strong').innerText()) !== endTime);
    await page.screenshot({ path: path.join(output, 'detail.png'), fullPage: true });

    await page.getByRole('button', { name: '← 返回历史档案' }).click();
    await page.getByPlaceholder('如 HAIYAN').fill('NO_SUCH_TYPHOON_XXXX');
    const emptyResponse = page.waitForResponse(r => r.url().includes('name=NO_SUCH_TYPHOON_XXXX'));
    await page.getByRole('button', { name: '查询', exact: true }).click();
    await emptyResponse;
    await page.getByText('暂无符合条件的历史台风', { exact: true }).waitFor();
    check('真实空查询显示明确无数据状态', true);
    const resetResponse = page.waitForResponse(r => r.url().includes('/api/typhoons?') && !r.url().includes('name='));
    await page.getByRole('button', { name: '重置', exact: true }).click();
    await resetResponse;
    await page.locator('.table-count').filter({ hasText: String(stats.typhoon_count) }).waitFor();
    const [, variantsResponse] = await Promise.all([
      page.getByText('包含临时轨迹和支轨事件', { exact: true }).click(),
      page.waitForResponse(r => r.url().includes('/api/typhoons?') && r.url().includes('include_spurs=true')),
    ]);
    const allData = (await variantsResponse.json()).data;
    check('临时和支轨事件可查询且不混淆MAIN统计', allData.total === stats.all_event_count);

    await page.getByRole('button', { name: '数据接入与任务', exact: true }).click();
    await page.getByRole('button', { name: '上传本地 CSV' }).waitFor();
    await page.getByText('已完成', { exact: true }).first().waitFor();
    check('任务状态跨页面恢复', true);
    if (process.env.TEST_REAL_UPLOAD === '1') {
      const status = (await (await context.request.get(`${base}/api/ibtracs/status`)).json()).data;
      const file = status.imported_files.find(file => file.status === 'imported');
      assert.ok(file?.local_path, '已登记真实原始文件');
      const uploadResponse = page.waitForResponse(r => r.url().endsWith('/api/ibtracs/import') && r.request().method() === 'POST', { timeout: 120000 });
      await page.getByLabel('选择 IBTrACS CSV 文件').setInputFiles(file.local_path);
      const response = await uploadResponse;
      assert.equal(response.status(), 202);
      const job = (await response.json()).data;
      let completed;
      for (let attempt = 0; attempt < 150; attempt++) {
        completed = (await (await context.request.get(`${base}/api/ibtracs/jobs/${job.id}`)).json()).data;
        if (!['queued', 'downloading', 'importing'].includes(completed.status)) break;
        await new Promise(resolve => setTimeout(resolve, 200));
      }
      check('浏览器上传真实CSV成功并验证内容哈希幂等', completed.status === 'succeeded' && completed.statistics.idempotent === true);
      const afterUpload = (await (await context.request.get(`${base}/api/typhoons/statistics`)).json()).data;
      check('重复上传后真实业务记录未增长', afterUpload.observation_count === stats.observation_count && afterUpload.all_event_count === stats.all_event_count);
    }
    await page.getByRole('menuitem', { name: '系统设置' }).click();
    await page.getByText('Python 版本', { exact: true }).waitFor();
    check('系统设置和数据管理继续可用', await page.getByRole('button', { name: '下载官方数据并导入' }).count() === 1);
    await page.getByRole('menuitem', { name: '气象风场分析', exact: true }).click();
    await page.getByText('该模块尚未接入', { exact: true }).waitFor();
    check('ERA5风场仍保持未接入边界', true);
    const auditResponse = page.waitForResponse(r => r.url().endsWith('/api/ml/audit'));
    await page.getByRole('menuitem', { name: '模型训练', exact: true }).click();
    await page.getByText('训练数据审计', { exact: true }).waitFor({ timeout: 60000 });
    const audit = (await (await auditResponse).json()).data;
    check('训练页展示真实严格样本审计', audit.strict_sample_count === 8048 && audit.special_cma_17_count === 0);
    await page.getByRole('menuitem', { name: '预测性能评估', exact: true }).click();
    await page.getByText('LSTM 严格质量主实验', { exact: true }).waitFor();
    check('评估页从真实实验读取四模型指标', await page.locator('.el-table__body tr').count() >= 4);
    await page.getByRole('menuitem', { name: '强度预测', exact: true }).click();
    await page.getByRole('button', { name: '执行真实模型推理', exact: true }).waitFor();
    check('历史回测预测页已接入真实模型', await page.getByText('历史回测预测', { exact: true }).count() > 0);
    const models = (await (await context.request.get(`${base}/api/ml/models`)).json()).data;
    const sampleEvent = (await (await context.request.get(`${base}/api/typhoons?season=2024&page=1&page_size=1&source=ibtracs`)).json()).data.items[0];
    const sampleTrack = (await (await context.request.get(`${base}/api/typhoons/${sampleEvent.id}/track?track_type=MAIN`)).json()).data.items;
    const timeMap = new Map(sampleTrack.map(point => [Date.parse(point.observation_time), point]));
    const forecast = sampleTrack.find(point => [0, 6, 12, 18, -6].every(hours => { const row = timeMap.get(Date.parse(point.observation_time) - hours * 3600000); return row && row.cma_wind_ms != null && ['O','V'].includes(row.cma_iflag); }));
    const inference = await context.request.post(`${base}/api/ml/predict`, { data: { model_id: models.find(model => model.model_type === 'lstm').id, typhoon_id: sampleEvent.id, forecast_time: forecast.observation_time } });
    check('已保存LSTM实际推理并返回历史真值', inference.ok() && (await inference.json()).data.actual_wind != null);
    await page.getByRole('menuitem', { name: '实验记录', exact: true }).click();
    await page.getByRole('button', { name: '导出 CSV', exact: true }).waitFor();
    check('实验记录和CSV/Excel导出入口可用', await page.getByRole('button', { name: '导出 Excel', exact: true }).count() === 1);
    await page.getByRole('menuitem', { name: '关于系统' }).click();
    await page.getByRole('heading', { name: '关于云浪智析' }).waitFor();
    await page.setViewportSize({ width: 1280, height: 800 });
    check('1280桌面视口无整页横向溢出', await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    if (errors.length) console.error('PAGE_ERRORS', JSON.stringify(errors, null, 2));
    check('无浏览器运行异常', errors.length === 0);
    const report = { checked_at: new Date().toISOString(), checks, page_errors: errors, statistics: stats, screenshots: ['home.png', 'history.png', 'detail.png'] };
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ passed: checks.length, checks, page_errors: errors }, null, 2));
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
