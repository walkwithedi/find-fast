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
  for (let i = 0; i < 450; i++) {
    touch(path.join(root, 'many', i % 3 ? 'b' : 'a', 'item-' + String(i).padStart(3, '0') + (i % 3 ? '.txt' : '.jpg')), '', 1500000000 + i);
  }
  fs.writeFileSync(path.join(tmp, 'config.json'), JSON.stringify({roots: [root]}));
  const bin = path.join(tmp, 'bin');
  fs.mkdirSync(bin);
  const log = path.join(tmp, 'opened.txt');
  fs.writeFileSync(path.join(bin, 'xdg-open'), '#!/bin/sh\necho "$1" >> "' + log + '"\n', {mode: 0o755});
  // a stand-in folder chooser that always answers the pics folder
  fs.writeFileSync(path.join(bin, 'zenity'), '#!/bin/sh\necho "' + path.join(root, 'pics') + '"\n', {mode: 0o755});
  // no desktop the tool can write shortcuts to: the real desktop settings are never touched
  const env = Object.assign({}, process.env, {LANG: lang, LC_ALL: '', LANGUAGE: '', PATH: bin + ':' + process.env.PATH,
                                              XDG_CURRENT_DESKTOP: '', DESKTOP_SESSION: ''});
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
  return page.$$eval('#rows .row .nm', xs => xs.map(x => x.textContent));
}
const countIs = (page, re) => page.waitForFunction(r => new RegExp(r).test(document.getElementById('count').textContent), re.source);
const statusIs = (page, re) => page.waitForFunction(r => new RegExp(r).test(document.getElementById('count').textContent + '|' +
  document.getElementById('toast').textContent), re.source);
async function linesOf(file, n) {
  for (let i = 0; i < 50 && (!fs.existsSync(file) || fs.readFileSync(file, 'utf8').trim().split('\n').length < n); i++) {
    await new Promise(r => setTimeout(r, 100));
  }
  return fs.existsSync(file) ? fs.readFileSync(file, 'utf8').trim().split('\n') : [];
}

(async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ff-web-'));
  // CHROMIUM_PATH: a Chromium other than the one Playwright downloads (optional)
  const browser = await chromium.launch(process.env.CHROMIUM_PATH ? {executablePath: process.env.CHROMIUM_PATH} : {});
  let srv;
  try {
    srv = await startServer(tmp, 'zh_CN.UTF-8');
    // bypassCSP: the page forbids eval, which Playwright's waitForFunction needs; the page itself is unchanged
    const ctx = await browser.newContext({viewport: {width: 1280, height: 800}, bypassCSP: true, colorScheme: 'light'});
    await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], {origin: new URL(srv.url).origin});
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    await page.goto(srv.url);
    assert.strictEqual(await page.title(), '秒搜文件');
    assert.strictEqual(await page.textContent('h1'), '秒搜文件');
    assert.strictEqual(await page.textContent('#quit'), '退出');
    await page.waitForFunction(() => /共 \d+ 项/.test(document.getElementById('indexState').textContent));
    // the default global shortcut could not be written (no desktop): said once the page is up
    await countIs(page, /^设置默认唤起快捷键失败：/);
    assert.strictEqual(await page.getAttribute('#count', 'class'), 'warn');
    assert.ok(JSON.parse(fs.readFileSync(path.join(tmp, 'config.json'), 'utf8')).toggle_default_done);
    assert.match(await page.textContent('#version'), /^v\d+\.\d+\.\d+$/);
    assert.match(await page.textContent('#ver'), /^v\d+\.\d+\.\d+$/);
    assert.match(await page.textContent('#rule'), /关闭本页/);
    // nothing typed: the starting state with examples, the index card in the details
    assert.ok(await page.isVisible('#empty'));
    assert.match(await page.textContent('#empty h2'), /找一个文件/);
    assert.ok(await page.isHidden('#filterbar'));
    assert.ok(await page.isVisible('#pvIndex'));

    // search, newest first; matches are marked; the first row is selected and shown in the details
    await page.fill('#q', 'report');
    await countIs(page, /^3 个结果/);
    assert.deepStrictEqual(await rowNames(page), ['Report 2024.pdf', 'report-draft.docx', 'report-2019.pdf']);
    assert.deepStrictEqual(await page.$$eval('#rows .row .nm mark', ms => ms.map(m => m.textContent)), ['Report', 'report', 'report']);
    assert.strictEqual(await page.getAttribute('#count', 'aria-live'), 'polite');
    assert.strictEqual(await page.getAttribute('#q', 'aria-activedescendant'), 'opt-0');
    assert.strictEqual(await page.textContent('#pvName'), 'Report 2024.pdf');
    assert.strictEqual(await page.textContent('#pvPath'), path.join(srv.root, 'docs', 'Report 2024.pdf'));
    assert.strictEqual(await page.textContent('#pvHit'), '名称');
    assert.match(await page.textContent('#listEnd'), /已显示全部 3 个结果/);
    // only the status bar counts results
    assert.strictEqual(await page.evaluate(() => (document.body.innerText.match(/个结果/g) || []).length), 2);  // count + end note
    // rows are 48 px high; hovering one shows its full path
    assert.ok(await page.$$eval('#rows .row', rs => rs.every(r => Math.abs(r.getBoundingClientRect().height - 48) <= 1)));
    assert.deepStrictEqual(await page.$$eval('#rows .row', rs => rs.map(r => r.title.split('\n')[0])),
      [path.join(srv.root, 'docs', 'Report 2024.pdf'), path.join(srv.root, 'docs', 'report-draft.docx'),
       path.join(srv.root, 'docs', 'old', 'report-2019.pdf')]);
    // type filters with counts over the whole result
    assert.deepStrictEqual(await page.$$eval('#chips .chip', cs => cs.map(c => c.dataset.type + ':' + c.querySelector('.n').textContent)),
      ['all:3', 'folder:0', 'doc:3', 'image:0', 'archive:0', 'code:0', 'audio:0']);
    assert.strictEqual(await page.getAttribute('#chips [data-type=folder]', 'aria-disabled'), 'true');

    // words also match folder names (marked in the folder); settings can turn that off (no rescan needed)
    await page.fill('#q', 'old 2019');
    await countIs(page, /^1 个结果/);
    assert.deepStrictEqual(await rowNames(page), ['report-2019.pdf']);
    assert.strictEqual(await page.$eval('#rows .row .pth mark', m => m.textContent), 'old');
    assert.strictEqual(await page.textContent('#pvHit'), '名称与路径');
    await page.fill('#q', 'docs report');
    await countIs(page, /^3 个结果/);
    await page.click('#gear');
    await page.waitForFunction(() => document.getElementById('settings').open);
    assert.ok(await page.isVisible('#setMatchPath'));
    assert.ok(await page.isChecked('#setMatchPath'));
    await page.uncheck('#setMatchPath');
    await page.click('#setSave');
    await page.waitForFunction(() => !document.getElementById('settings').open);
    await page.waitForFunction(() => !document.getElementById('empty').hidden && /docs report/.test(document.getElementById('empty').textContent));
    assert.strictEqual(JSON.parse(fs.readFileSync(path.join(tmp, 'config.json'), 'utf8')).match_path, false);
    await page.click('#gear');
    await page.waitForFunction(() => document.getElementById('settings').open);
    assert.ok(!(await page.isChecked('#setMatchPath')));
    await page.click('#setDefaults');
    assert.ok(await page.isChecked('#setMatchPath'));
    await page.click('#setCancel');
    await page.click('#gear');
    await page.waitForFunction(() => document.getElementById('settings').open);
    assert.ok(!(await page.isChecked('#setMatchPath')));
    await page.check('#setMatchPath');
    await page.click('#setSave');
    await countIs(page, /^3 个结果/);

    // keyboard: down, enter opens, ctrl+enter locates, ctrl+shift+c copies the path; the focus stays in the box
    await page.fill('#q', 'report');
    await countIs(page, /^3 个结果/);
    await page.focus('#q');
    await page.keyboard.press('ArrowDown');
    await page.waitForFunction(() => document.querySelector('.row[aria-selected="true"] .nm').textContent === 'report-draft.docx');
    assert.strictEqual(await page.evaluate(() => document.activeElement.id), 'q');
    assert.strictEqual(await page.$$eval('.row[aria-selected="true"]', xs => xs.length), 1);
    await page.keyboard.press('Enter');
    assert.strictEqual((await linesOf(srv.log, 1))[0], path.join(srv.root, 'docs', 'report-draft.docx'));
    await statusIs(page, /已打开：report-draft\.docx/);
    // locate: without a file manager service the folder is opened
    await page.keyboard.press('Control+Enter');
    assert.strictEqual((await linesOf(srv.log, 2))[1], path.join(srv.root, 'docs'));
    await statusIs(page, /已打开所在文件夹/);
    // the buttons of the details panel; no locate button in the rows
    assert.strictEqual(await page.textContent('#folderText'), '定位');
    assert.strictEqual(await page.$$eval('#rows button', bs => bs.length), 0);
    await page.click('#open');
    assert.strictEqual((await linesOf(srv.log, 3)).length, 3);
    await page.click('#rows .row:nth-child(1)');
    assert.strictEqual(await page.textContent('#pvName'), 'Report 2024.pdf');
    await page.focus('#q');
    await page.keyboard.press('Control+Shift+C');
    await statusIs(page, /已复制路径/);
    assert.strictEqual(await page.evaluate(() => navigator.clipboard.readText()), path.join(srv.root, 'docs', 'Report 2024.pdf'));
    // the list itself: Tab reaches it; letters go back to the box
    await page.focus('#q');
    const order = [];
    for (let i = 0; i < 12 && order[order.length - 1] !== 'rows'; i++) {
      await page.keyboard.press('Tab');
      order.push(await page.evaluate(() => document.activeElement.id || document.activeElement.dataset.type));
    }
    assert.deepStrictEqual(order, ['clear', 'gear', 'all', 'sortBtn', 'rows']);
    assert.ok(await page.evaluate(() => document.activeElement.matches(':focus-visible')
      && getComputedStyle(document.activeElement).outlineStyle !== 'none'));
    await page.keyboard.press('ArrowDown');
    assert.strictEqual(await page.$eval('.row[aria-selected="true"] .nm', x => x.textContent), 'report-draft.docx');
    await page.keyboard.press('x');
    assert.strictEqual(await page.evaluate(() => document.activeElement.id), 'q');
    assert.strictEqual(await page.inputValue('#q'), 'reportx');
    await page.fill('#q', 'report');
    await countIs(page, /^3 个结果/);

    // sort menu
    await page.click('#sortBtn');
    assert.ok(await page.isVisible('#sortMenu'));
    assert.strictEqual(await page.getAttribute('#sortMenu [aria-checked="true"]', 'data-i'), '0');
    await page.click('#sortMenu [data-i="2"]');
    await page.waitForFunction(() => Array.from(document.querySelectorAll('#rows .nm'), x => x.textContent).join('|')
      === 'Report 2024.pdf|report-2019.pdf|report-draft.docx');
    assert.strictEqual(await page.textContent('#sortText'), '名称 A→Z');
    await page.click('#sortBtn');
    await page.click('#sortMenu [data-i="4"]');
    await page.waitForFunction(() => document.querySelector('#rows .nm').textContent === 'Report 2024.pdf'
      && document.getElementById('sortText').textContent === '最大在前');

    // bad regular expression: explained under the box, the list stays
    await page.fill('#q', 'regex:(');
    await page.waitForFunction(() => !document.getElementById('qError').hidden);
    assert.match(await page.textContent('#qError'), /^正则表达式有误：/);
    assert.strictEqual(await page.getAttribute('#qError', 'role'), 'alert');
    assert.strictEqual((await rowNames(page)).length, 3);

    // more rows than one request: scrolling loads more; filters narrow over the whole result
    await page.click('#sortBtn');
    await page.click('#sortMenu [data-i="0"]');
    await page.fill('#q', 'item-');
    await countIs(page, /^450 个结果/);
    assert.ok(await page.isHidden('#qError'));
    assert.strictEqual((await rowNames(page)).length, 200);
    assert.ok(await page.isHidden('#listEnd'));
    await page.$eval('#listwrap', b => { b.scrollTop = b.scrollHeight; });
    await page.waitForFunction(() => document.querySelectorAll('#rows .row').length === 400);
    await page.$eval('#listwrap', b => { b.scrollTop = b.scrollHeight; });
    await page.waitForFunction(() => document.querySelectorAll('#rows .row').length === 450);
    assert.match(await page.textContent('#listEnd'), /已显示全部 450 个结果/);
    await page.click('#rows .row:nth-child(300)');
    assert.strictEqual(await page.getAttribute('#q', 'aria-activedescendant'), 'opt-299');
    assert.deepStrictEqual(await page.$$eval('#chips .chip', cs => cs.map(c => (c.dataset.type || 'scope') + ':' + c.querySelector('.n').textContent)),
      ['all:450', 'folder:0', 'doc:300', 'image:150', 'archive:0', 'code:0', 'audio:0', 'scope:300', 'scope:150']);
    await page.click('#chips [data-type=doc]');
    await countIs(page, /^300 个结果/);
    assert.ok(await page.$$eval('#rows .nm', xs => xs.every(x => x.textContent.endsWith('.txt'))));
    assert.strictEqual(await page.getAttribute('#chips [data-type=doc]', 'aria-pressed'), 'true');
    await page.click('#chips [data-type=doc]');
    await countIs(page, /^450 个结果/);
    assert.strictEqual(await page.getAttribute('#chips [data-scope]', 'title'), path.join(srv.root, 'many', 'b'));
    await page.click('#chips [data-scope]');
    await countIs(page, /^300 个结果/);
    assert.strictEqual(await page.$$eval('#chips [data-scope]', cs => cs.length), 1);
    assert.strictEqual(await page.getAttribute('#chips [data-scope]', 'aria-pressed'), 'true');
    await page.click('#chips [data-scope]');
    await countIs(page, /^450 个结果/);

    // no match: the words are repeated and there are ways out
    await page.fill('#q', 'zzzz');
    await page.waitForFunction(() => !document.getElementById('empty').hidden && /没有匹配「zzzz」的结果/.test(document.getElementById('empty').textContent));
    assert.ok(await page.isHidden('#filterbar'));
    await page.click('#empty [data-action=clear]');
    await page.waitForFunction(() => /找一个文件/.test(document.getElementById('empty').textContent));
    assert.strictEqual(await page.inputValue('#q'), '');
    // the shortcuts panel: ? in the empty box; a syntax example searches it
    await page.focus('#q');
    await page.keyboard.press('?');
    await page.waitForFunction(() => document.getElementById('keysDlg').open);
    assert.strictEqual(await page.inputValue('#q'), '');
    await page.click('#synList [data-q="ext:pdf;docx"]');
    await page.waitForFunction(() => !document.getElementById('keysDlg').open);
    assert.strictEqual(await page.inputValue('#q'), 'ext:pdf;docx');
    await countIs(page, /^\d+ 个结果/);
    assert.ok(await page.$$eval('#rows .nm mark', ms => ms.length > 0 && ms.every(m => /^\.(pdf|docx)$/.test(m.textContent))));

    // similar versions: tags, the hover line and "go to the newest version"
    await page.fill('#q', '示例方案');
    await countIs(page, /^3 个结果/);
    assert.deepStrictEqual(await page.$$eval('#rows .row', rs => rs.map(r => (r.querySelector('.tag') || {}).textContent)),
      ['最新', '有更新版', '有更新版']);
    assert.match(await page.getAttribute('#rows .row:nth-child(3)', 'title'), /\n同组共 3 个类似版本，最新：.*示例方案_v2\.docx/);
    await page.click('#rows .row:nth-child(3)', {button: 'right'});
    assert.ok(await page.isVisible('#mJump'));
    await page.click('#mJump');
    await page.waitForFunction(() => document.querySelector('.row[aria-selected="true"] .nm').textContent.endsWith('示例方案_v2.docx'));
    await page.click('#rows .row:nth-child(1)', {button: 'right'});
    assert.ok(await page.isHidden('#mJump'));
    await page.keyboard.press('Escape');
    // the tags stay while the type filter changes (the same result is reused)
    await page.click('#chips [data-type=doc]');
    await page.waitForFunction(() => document.querySelector('#chips [data-type=doc]').getAttribute('aria-pressed') === 'true');
    assert.deepStrictEqual(await page.$$eval('#rows .row', rs => rs.map(r => (r.querySelector('.tag') || {}).textContent)),
      ['最新', '有更新版', '有更新版']);

    // right-click a row: exclude its folder after confirming
    await page.fill('#q', 'report-2019');
    await countIs(page, /^1 个结果/);
    await page.click('#rows .row', {button: 'right'});
    assert.ok(await page.isVisible('#ctx'));
    assert.strictEqual(await page.textContent('#mExclude .ml'), '排除所在文件夹');
    assert.deepStrictEqual(await page.$$eval('#ctx button:not([hidden]) .ml', bs => bs.map(b => b.textContent)),
      ['打开', '定位', '复制路径', '排除所在文件夹', '重新扫描']);
    assert.strictEqual(await page.$$eval('#ctx hr', hs => hs.length), 2);
    assert.strictEqual(await page.evaluate(() => document.activeElement.id), 'mOpen');
    let asked = '';
    page.once('dialog', d => { asked = d.message(); d.accept(); });
    await page.click('#mExclude');
    await countIs(page, /已按新设置更新索引/);
    assert.ok(asked.includes(path.join(srv.root, 'docs', 'old')), asked);
    assert.ok(await page.isHidden('#ctx'));
    await page.fill('#q', 'report-2019');
    await page.waitForFunction(() => /没有匹配/.test(document.getElementById('empty').textContent) && !document.getElementById('empty').hidden);
    // a folder row offers "exclude this folder"; Escape closes the menu
    await page.fill('#q', 'pics');
    await page.waitForFunction(() => document.querySelector('#rows .nm') && /pics/.test(document.querySelector('#rows .nm').textContent));
    await page.click('#rows .row', {button: 'right'});
    assert.strictEqual(await page.textContent('#mExclude .ml'), '排除此文件夹');
    assert.ok(await page.isHidden('#mJump'));
    await page.keyboard.press('Escape');
    assert.ok(await page.isHidden('#ctx'));

    // settings: four parts; pick a folder, add a name rule, save
    await page.keyboard.press('Control+,');
    await page.waitForFunction(() => document.getElementById('settings').open && document.querySelectorAll('#setRoots li').length === 1);
    assert.deepStrictEqual(await page.$$eval('#setNav [role=tab]', ts => ts.map(t => t.textContent)), ['索引的文件夹', '排除规则', '搜索', '升级']);
    assert.strictEqual(await page.textContent('#setRoots li span'), srv.root);
    await page.focus('#tabRoots');
    await page.keyboard.press('ArrowDown');
    assert.ok(await page.isVisible('#paneExclude'));
    assert.strictEqual(await page.getAttribute('#tabExclude', 'aria-selected'), 'true');
    await page.click('#addExcludeFolder');
    await page.waitForFunction(() => Array.from(document.querySelectorAll('#setExclude li span'), x => x.textContent).some(t => /pics$/.test(t)));
    await page.fill('#ruleIn', '*.docx');
    await page.press('#ruleIn', 'Enter');
    assert.ok(await page.evaluate(() => document.getElementById('settings').open));
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
    await page.setViewportSize({width: 1280, height: 800});
    await page.click('#setAnyway');
    await page.waitForFunction(() => !document.getElementById('settings').open);
    await countIs(page, /已按新设置更新索引/);
    await page.fill('#q', 'report');
    await countIs(page, /^1 个结果/);
    assert.deepStrictEqual(await rowNames(page), ['Report 2024.pdf']);
    const saved = JSON.parse(fs.readFileSync(path.join(path.dirname(srv.root), 'config.json'), 'utf8'));
    assert.ok(saved.exclude.includes('*.docx') && saved.exclude.includes(path.join(srv.root, 'pics')));
    // empty folder list cannot be saved; the focus comes back to the gear
    await page.click('#gear');
    await page.waitForFunction(() => document.getElementById('settings').open);
    await page.click('#setRoots li button');
    await page.click('#setSave');
    await page.waitForFunction(() => document.getElementById('setMsg').className === 'bad');
    assert.ok(await page.isHidden('#setAnyway'));
    await page.click('#setCancel');
    assert.strictEqual(await page.evaluate(() => document.activeElement.id), 'gear');

    // narrow windows: no horizontal page scroll; the details hide below 1080 px
    for (const w of [1080, 860, 760, 480, 360]) {
      await page.setViewportSize({width: w, height: 700});
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'horizontal scroll at ' + w);
    }
    assert.ok(await page.isHidden('#preview'));
    // the theme: the system's at first, switched by hand and kept
    assert.strictEqual(await page.getAttribute('html', 'data-theme'), 'light');
    await page.setViewportSize({width: 1280, height: 800});
    await page.click('#themeBtn');
    assert.strictEqual(await page.getAttribute('html', 'data-theme'), 'dark');
    assert.strictEqual(await page.evaluate(() => getComputedStyle(document.querySelector('.shell')).backgroundColor), 'rgb(20, 24, 29)');
    // folding to the search box alone
    await page.click('#moreBtn');
    await page.click('#mFold');
    assert.ok(await page.evaluate(() => Math.abs(document.getElementById('shell').getBoundingClientRect().height - 90) <= 1));
    await page.fill('#q', 'report');
    await page.waitForFunction(() => !document.getElementById('shell').classList.contains('folded'));
    assert.deepStrictEqual(errors, []);

    // a reload keeps the service and the theme; closing the last page stops it
    await page.reload();
    await page.waitForFunction(() => /共 \d+ 项/.test(document.getElementById('indexState').textContent));
    assert.strictEqual(await page.getAttribute('html', 'data-theme'), 'dark');
    assert.strictEqual(srv.proc.exitCode, null);
    await page.close({runBeforeUnload: true});
    assert.ok(await exited(srv.proc, 15000), 'service did not exit after the page closed');

    // English, and the quit button
    srv = await startServer(fs.mkdtempSync(path.join(os.tmpdir(), 'ff-web-')), 'en_US.UTF-8');
    const p2 = await (await browser.newContext({bypassCSP: true})).newPage();
    await p2.goto(srv.url);
    await p2.waitForFunction(() => document.getElementById('title').textContent === 'find-fast');
    assert.strictEqual(await p2.textContent('#quit'), 'Quit');
    await p2.fill('#q', 'report');
    await p2.waitForFunction(() => /^3 results$/.test(document.getElementById('count').textContent));
    assert.strictEqual(await p2.textContent('#chips [data-type=doc]'), 'Documents3');
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
