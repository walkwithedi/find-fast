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
  touch(path.join(root, 'v', '示例方案.docx'), 'x', 1700000600);
  touch(path.join(root, 'v', 'a', '示例方案_v2.docx'), 'x', 1700000800);
  touch(path.join(root, 'v', 'b', '示例方案-终稿.docx'), 'x', 1700000700);
  for (let i = 0; i < 450; i++) touch(path.join(root, 'many', 'item-' + String(i).padStart(3, '0') + '.txt'), '', 1500000000 + i);
  fs.writeFileSync(path.join(tmp, 'config.json'), JSON.stringify({roots: [root]}));
  const bin = path.join(tmp, 'bin');
  fs.mkdirSync(bin);
  const log = path.join(tmp, 'opened.txt');
  fs.writeFileSync(path.join(bin, 'xdg-open'), '#!/bin/sh\necho "$1" >> "' + log + '"\n', {mode: 0o755});
  // a stand-in folder chooser that always answers the pics folder
  fs.writeFileSync(path.join(bin, 'zenity'), '#!/bin/sh\necho "' + path.join(root, 'pics') + '"\n', {mode: 0o755});
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
  // CHROMIUM_PATH: a Chromium other than the one Playwright downloads (optional)
  const browser = await chromium.launch(process.env.CHROMIUM_PATH ? {executablePath: process.env.CHROMIUM_PATH} : {});
  let srv;
  try {
    srv = await startServer(tmp, 'zh_CN.UTF-8');
    // bypassCSP: the page forbids eval, which Playwright's waitForFunction needs; the page itself is unchanged
    const ctx = await browser.newContext({viewport: {width: 1100, height: 800}, bypassCSP: true});
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
    // hovering a row shows its full path
    assert.deepStrictEqual(await page.$$eval('#rows tr', trs => trs.map(tr => tr.title)),
      [path.join(srv.root, 'docs', 'Report 2024.pdf'), path.join(srv.root, 'docs', 'report-draft.docx'),
       path.join(srv.root, 'docs', 'old', 'report-2019.pdf')]);

    // keyboard: down, enter opens, ctrl+enter opens the folder, ctrl+c copies
    await page.press('#q', 'ArrowDown');
    await page.keyboard.press('ArrowDown');
    assert.strictEqual(await page.$eval('tr[aria-selected="true"] td.name', td => td.textContent), 'report-draft.docx');
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => true);
    for (let i = 0; i < 50 && !fs.existsSync(srv.log); i++) await page.waitForTimeout(100);
    assert.strictEqual(fs.readFileSync(srv.log, 'utf8').trim(), path.join(srv.root, 'docs', 'report-draft.docx'));
    // the locate button at the end of a row; without a file manager service the folder is opened
    assert.strictEqual(await page.textContent('#folder'), '定位');
    assert.strictEqual(await page.getAttribute('#rows tr:nth-child(1) button.locate', 'aria-label'), '定位 Report 2024.pdf');
    await page.click('#rows tr:nth-child(1) button.locate');
    for (let i = 0; i < 50 && fs.readFileSync(srv.log, 'utf8').trim().split('\n').length < 2; i++) await page.waitForTimeout(100);
    assert.strictEqual(fs.readFileSync(srv.log, 'utf8').trim().split('\n')[1], path.join(srv.root, 'docs'));
    await page.waitForFunction(() => /已打开所在文件夹/.test(document.getElementById('status').textContent));
    assert.strictEqual(await page.$eval('tr[aria-selected="true"] td.name', td => td.textContent), 'Report 2024.pdf');
    await page.focus('#rows tr:nth-child(1) button.locate');
    await page.keyboard.press('Tab');
    assert.strictEqual(await page.evaluate(() => document.activeElement.closest('tr').querySelector('td.name').textContent), 'report-draft.docx');
    assert.ok(await page.evaluate(() => document.activeElement.matches(':focus-visible')
      && getComputedStyle(document.activeElement).outlineStyle !== 'none'));
    await page.keyboard.press('Enter');
    for (let i = 0; i < 50 && fs.readFileSync(srv.log, 'utf8').trim().split('\n').length < 3; i++) await page.waitForTimeout(100);
    assert.strictEqual(fs.readFileSync(srv.log, 'utf8').trim().split('\n').length, 3);
    await page.click('#rows tr:nth-child(2) td.name');
    await page.keyboard.press('Control+c');
    await page.waitForFunction(() => /已复制路径/.test(document.getElementById('status').textContent));
    assert.strictEqual(await page.evaluate(() => navigator.clipboard.readText()), path.join(srv.root, 'docs', 'report-draft.docx'));
    assert.strictEqual(await page.getAttribute('#status', 'class'), 'ok');

    // sort by name through the header, then the select
    await page.click('#hName');
    // wait for the re-sorted rows themselves: the first row is the same in both orders
    await page.waitForFunction(() => Array.from(document.querySelectorAll('#rows td.name'), td => td.textContent).join('|')
      === 'Report 2024.pdf|report-2019.pdf|report-draft.docx'
      && document.querySelector('th[data-sort="name"]').getAttribute('aria-sort') === 'ascending');
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

    // similar versions: tags, the hover line and "go to the newest version"
    await page.selectOption('#sort', 'mtime:1');
    await page.fill('#q', '示例方案');
    await page.waitForFunction(() => /^3 个结果/.test(document.getElementById('status').textContent));
    assert.deepStrictEqual(await page.$$eval('#rows tr', trs => trs.map(tr => (tr.querySelector('.tag') || {}).textContent)),
      ['最新', '有更新版', '有更新版']);
    assert.match(await page.getAttribute('#rows tr:nth-child(3)', 'title'), /\n同组共 3 个类似版本，最新：.*示例方案_v2\.docx$/);
    await page.click('#rows tr:nth-child(3)', {button: 'right'});
    assert.ok(await page.isVisible('#mJump'));
    await page.click('#mJump');
    await page.waitForFunction(() => document.querySelector('tr[aria-selected="true"] td.name').textContent.endsWith('示例方案_v2.docx'));
    await page.click('#rows tr:nth-child(1)', {button: 'right'});
    assert.ok(await page.isHidden('#mJump'));
    await page.keyboard.press('Escape');

    // right-click a row: exclude its folder after confirming
    await page.fill('#q', 'report-2019');
    await page.waitForFunction(() => /^1 个结果/.test(document.getElementById('status').textContent));
    await page.click('#rows tr', {button: 'right'});
    assert.ok(await page.isVisible('#ctx'));
    assert.strictEqual(await page.textContent('#mExclude'), '排除所在文件夹');
    assert.deepStrictEqual(await page.$$eval('#ctx button:not([hidden])', bs => bs.map(b => b.textContent)),
      ['定位', '打开', '复制路径', '排除所在文件夹', '重新扫描']);
    assert.strictEqual(await page.evaluate(() => document.activeElement.id), 'mFolder');
    let asked = '';
    page.once('dialog', d => { asked = d.message(); d.accept(); });
    await page.click('#mExclude');
    await page.waitForFunction(() => /已按新设置更新索引/.test(document.getElementById('status').textContent));
    assert.ok(asked.includes(path.join(srv.root, 'docs', 'old')), asked);
    assert.ok(await page.isHidden('#ctx'));
    await page.fill('#q', 'report-2019');
    await page.waitForFunction(() => /^0 个结果/.test(document.getElementById('status').textContent));
    // a folder row offers "exclude this folder"; Escape closes the menu
    await page.fill('#q', 'pics');
    await page.waitForFunction(() => document.querySelector('#rows td.name') && /pics/.test(document.querySelector('#rows td.name').textContent));
    await page.click('#rows tr', {button: 'right'});
    assert.strictEqual(await page.textContent('#mExclude'), '排除此文件夹');
    assert.ok(await page.isHidden('#mJump'));
    await page.keyboard.press('Escape');
    assert.ok(await page.isHidden('#ctx'));

    // settings: pick a folder, add a name rule, save
    await page.click('#gear');
    await page.waitForFunction(() => document.getElementById('settings').open && document.querySelectorAll('#setRoots li').length === 1);
    assert.strictEqual(await page.textContent('#setRoots li span'), srv.root);
    await page.click('#addExcludeFolder');
    await page.waitForFunction(() => Array.from(document.querySelectorAll('#setExclude li span'), x => x.textContent).some(t => /pics$/.test(t)));
    await page.fill('#ruleIn', '*.docx');
    await page.press('#ruleIn', 'Enter');
    assert.ok((await page.$$eval('#setExclude li span', xs => xs.map(x => x.textContent))).includes('*.docx'));
    // a path that does not exist is listed first; Save anyway is offered
    await page.fill('#ruleIn', path.join(srv.root, 'no-such-folder'));
    await page.click('#addRule');
    await page.click('#setSave');
    await page.waitForFunction(() => document.getElementById('setMsg').className === 'warn');
    assert.ok(await page.isVisible('#setAnyway'));
    assert.match(await page.textContent('#setMsg'), /no-such-folder/);
    await page.setViewportSize({width: 360, height: 700});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= 360), 'horizontal scroll with settings open');
    await page.setViewportSize({width: 1100, height: 800});
    await page.click('#setAnyway');
    await page.waitForFunction(() => !document.getElementById('settings').open);
    await page.waitForFunction(() => /已按新设置更新索引/.test(document.getElementById('status').textContent));
    await page.fill('#q', 'report');
    await page.waitForFunction(() => /^1 个结果/.test(document.getElementById('status').textContent));
    assert.deepStrictEqual(await rowNames(page), ['Report 2024.pdf']);
    const saved = JSON.parse(fs.readFileSync(path.join(path.dirname(srv.root), 'config.json'), 'utf8'));
    assert.ok(saved.exclude.includes('*.docx') && saved.exclude.includes(path.join(srv.root, 'pics')));
    // empty folder list cannot be saved
    await page.click('#gear');
    await page.waitForFunction(() => document.getElementById('settings').open);
    await page.click('#setRoots li button');
    await page.click('#setSave');
    await page.waitForFunction(() => document.getElementById('setMsg').className === 'bad');
    assert.ok(await page.isHidden('#setAnyway'));
    await page.click('#setCancel');

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
    const p2 = await (await browser.newContext({bypassCSP: true})).newPage();
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
