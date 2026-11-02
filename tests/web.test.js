// Browser tests of the find-fast page (find_fast.html served by find_fast_web.py).
// Needs Node and Playwright with Chromium:  node tests/web.test.js
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const {spawn} = require('child_process');
const {chromium} = require('playwright');

const ROOT = path.resolve(__dirname, '..');

function touch(p, data, mtime) {
  fs.mkdirSync(path.dirname(p), {recursive: true});
  fs.writeFileSync(p, data || '');
  if (mtime) fs.utimesSync(p, mtime, mtime);
}

function startServer(tmp, lang) {
  const root = path.join(tmp, 'root');
  touch(path.join(root, 'docs', 'Report 2024.pdf'), 'x'.repeat(300), 1700000300);
  touch(path.join(root, 'docs', 'report-draft.docx'), 'x'.repeat(20), 1700000200);
  touch(path.join(root, 'docs', 'old', 'report-2019.pdf'), 'x', 1600000000);
  touch(path.join(root, 'pics', '项目报告.pptx'), 'x', 1700000500);
  for (let i = 0; i < 450; i++) touch(path.join(root, 'many', 'item-' + String(i).padStart(3, '0') + '.txt'), '', 1500000000 + i);
  fs.writeFileSync(path.join(tmp, 'config.json'), JSON.stringify({roots: [root]}));
  const bin = path.join(tmp, 'bin');
  fs.mkdirSync(bin);
  const log = path.join(tmp, 'opened.txt');
  fs.writeFileSync(path.join(bin, 'xdg-open'), '#!/bin/sh\necho "$1" >> "' + log + '"\n', {mode: 0o755});
  const env = Object.assign({}, process.env, {LANG: lang, LC_ALL: '', LANGUAGE: '', PATH: bin + ':' + process.env.PATH});
  const proc = spawn('python3', [path.join(ROOT, 'find_fast.py'), '--web', '--no-browser',
    '--config', path.join(tmp, 'config.json'), '--cache', path.join(tmp, 'index.bin')], {env});
  return new Promise((resolve, reject) => {
    let out = '';
    proc.stdout.on('data', d => {
      out += d;
      const m = out.match(/(http:\/\/127\.0\.0\.1:\d+\/\?t=\S+)/);
      if (m) resolve({proc, url: m[1], root, log});
    });
    proc.on('exit', code => reject(new Error('server exited ' + code)));
    setTimeout(() => reject(new Error('no address printed')), 20000);
  });
}

function exited(proc, ms) {
  return new Promise(resolve => {
    if (proc.exitCode !== null) return resolve(true);
    const t = setTimeout(() => resolve(false), ms);
    proc.on('exit', () => { clearTimeout(t); resolve(true); });
  });
}

async function rowNames(page) {
  return page.$$eval('#rows tr td.name', tds => tds.map(td => td.textContent));
}

(async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ff-web-'));
  const browser = await chromium.launch();
  let srv;
  try {
    srv = await startServer(tmp, 'zh_CN.UTF-8');
    const ctx = await browser.newContext({viewport: {width: 1100, height: 800}});
    await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], {origin: new URL(srv.url).origin});
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(srv.url);
    assert.strictEqual(await page.title(), '秒搜文件');
    assert.strictEqual(await page.textContent('h1'), '秒搜文件');
    assert.strictEqual(await page.textContent('#quit'), '退出');
    await page.waitForFunction(() => /条目/.test(document.getElementById('index').textContent));
    assert.match(await page.textContent('#version'), /^v\d+\.\d+\.\d+$/);
    assert.match(await page.textContent('#rule'), /关闭本页/);

    // search, newest first
    await page.fill('#q', 'report');
    await page.waitForFunction(() => /^3 个结果/.test(document.getElementById('status').textContent));
    assert.deepStrictEqual(await rowNames(page), ['Report 2024.pdf', 'report-draft.docx', 'report-2019.pdf']);
    assert.strictEqual(await page.getAttribute('#status', 'aria-live'), 'polite');

    // keyboard: down, enter opens, ctrl+enter opens the folder, ctrl+c copies
    await page.press('#q', 'ArrowDown');
    await page.keyboard.press('ArrowDown');
    assert.strictEqual(await page.$eval('tr[aria-selected="true"] td.name', td => td.textContent), 'report-draft.docx');
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => true);
    for (let i = 0; i < 50 && !fs.existsSync(srv.log); i++) await page.waitForTimeout(100);
    assert.strictEqual(fs.readFileSync(srv.log, 'utf8').trim(), path.join(srv.root, 'docs', 'report-draft.docx'));
    await page.keyboard.press('Control+c');
    await page.waitForFunction(() => /已复制路径/.test(document.getElementById('status').textContent));
    assert.strictEqual(await page.evaluate(() => navigator.clipboard.readText()), path.join(srv.root, 'docs', 'report-draft.docx'));
    assert.strictEqual(await page.getAttribute('#status', 'class'), 'ok');

    // sort by name through the header, then the select
    await page.click('#hName');
    await page.waitForFunction(() => document.querySelector('#rows td.name').textContent === 'Report 2024.pdf'
      && document.querySelector('th[data-sort="name"]').getAttribute('aria-sort') === 'ascending');
    assert.deepStrictEqual(await rowNames(page), ['Report 2024.pdf', 'report-2019.pdf', 'report-draft.docx']);
    await page.selectOption('#sort', 'size:1');
    await page.waitForFunction(() => document.querySelector('th[data-sort="size"]').getAttribute('aria-sort') === 'descending');

    // bad regular expression
    await page.fill('#q', 'regex:(');
    await page.waitForFunction(() => document.getElementById('status').className === 'warn');
    assert.match(await page.textContent('#status'), /^搜索失败：/);
    assert.strictEqual((await rowNames(page)).length, 0);

    // more rows than one request: "show more" and End
    await page.fill('#q', 'item-');
    await page.waitForFunction(() => /^450 个结果/.test(document.getElementById('status').textContent));
    assert.strictEqual((await rowNames(page)).length, 200);
    await page.click('#more');
    await page.waitForFunction(() => document.querySelectorAll('#rows tr').length === 400);

    // narrow screen: no horizontal page scroll; dark mode colours
    await page.setViewportSize({width: 360, height: 700});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= 360), 'horizontal scroll at 360px');
    await page.emulateMedia({colorScheme: 'dark'});
    assert.strictEqual(await page.evaluate(() => getComputedStyle(document.body).backgroundColor), 'rgb(13, 17, 23)');
    assert.deepStrictEqual(errors, []);

    // a reload keeps the service; closing the last page stops it
    await page.reload();
    await page.waitForFunction(() => /条目/.test(document.getElementById('index').textContent));
    assert.strictEqual(srv.proc.exitCode, null);
    await page.close({runBeforeUnload: true});
    assert.ok(await exited(srv.proc, 15000), 'service did not exit after the page closed');

    // English, and the quit button
    srv = await startServer(fs.mkdtempSync(path.join(os.tmpdir(), 'ff-web-')), 'en_US.UTF-8');
    const p2 = await (await browser.newContext()).newPage();
    await p2.goto(srv.url);
    await p2.waitForFunction(() => document.getElementById('title').textContent === 'find-fast');
    assert.strictEqual(await p2.textContent('#quit'), 'Quit');
    await p2.click('#quit');
    await p2.waitForFunction(() => getComputedStyle(document.getElementById('closed')).display === 'block');
    assert.ok(await p2.isDisabled('#q'));
    assert.ok(await exited(srv.proc, 10000), 'service did not exit on quit');
    console.log('web tests passed');
  } finally {
    await browser.close();
    if (srv && srv.proc.exitCode === null) srv.proc.kill();
    fs.rmSync(tmp, {recursive: true, force: true});
  }
})().catch(e => { console.error(e); process.exit(1); });
