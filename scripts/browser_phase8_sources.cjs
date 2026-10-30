const { chromium } = require('../frontend/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

async function main() {
  const base = process.env.APP_URL || 'http://127.0.0.1:5173';
  const apiBase = process.env.API_URL || 'http://127.0.0.1:8000';
  const output = path.resolve(__dirname, '../logs/browser-qa-phase8-sources');
  fs.mkdirSync(output, {recursive: true});
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  const page = await browser.newPage({viewport: {width: 1500, height: 1000}});
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  try {
    const sourceResponse = await page.request.get(`${apiBase}/api/era5/sources`);
    assert.equal(sourceResponse.ok(), true);
    const sources = (await sourceResponse.json()).data;
    assert.equal(sources.state.default, 'auto');
    assert.equal(sources.items.length, 3);
    assert.equal(sources.state.sources.google_arco.status, 'available');
    assert.equal(sources.state.sources.aws_icechunk.status, 'available');
    assert.equal(sources.state.sources.ecmwf_arco.status, 'unauthorized');

    const auditResponse = await page.request.get(`${apiBase}/api/era5/samples/audit`);
    const audit = (await auditResponse.json()).data;
    assert.equal(audit.samples, 18);
    assert.deepEqual(audit.splits, {
      train: {samples: 6, events: 5},
      validation: {samples: 6, events: 6},
      test: {samples: 6, events: 6},
    });

    await page.goto(`${base}/wind-field`);
    await page.getByRole('heading', {name: 'ERA5 近海面风场'}).waitFor();
    await page.getByRole('tab', {name: '数据源诊断'}).click();
    await page.getByText('Google ARCO-ERA5', {exact: true}).waitFor();
    await page.getByText('AWS Earthmover Icechunk ERA5', {exact: true}).waitFor();
    await page.getByText('ECMWF ERA5 ARCO geoChunked', {exact: true}).waitFor();
    await page.getByText('未测得', {exact: true}).first().waitFor();
    await page.screenshot({path: path.join(output, 'source-diagnostics.png'), fullPage: true});
    assert.deepEqual(errors, []);
    const report = {
      checked_at: new Date().toISOString(),
      browser: 'Microsoft Edge (Playwright msedge channel)',
      sources: Object.fromEntries(Object.entries(sources.state.sources).map(([id, value]) => [id, value.status])),
      default: sources.state.default,
      samples: audit.samples,
      splits: audit.splits,
      console_errors: errors,
    };
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
