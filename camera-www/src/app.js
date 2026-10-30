/* Gear 360 control page. Talks to cgi-bin/run (one command at a time) and cgi-bin/files. */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const stamp = () => new Date().toTimeString().slice(0, 8);

  // ---------- serial command queue (st can crash the camera if called in parallel) ----------
  let chain = Promise.resolve();
  let pending = 0;
  function setBusy() {
    const b = $('busy');
    b.textContent = pending ? `busy (${pending})` : 'idle';
    b.className = 'badge ' + (pending ? 'text-bg-warning' : 'text-bg-secondary');
  }

  function parseRun(text, res) {
    const out = { reply: '', a7: null, dlog: null };
    let cur = null;
    for (const line of text.split('\n')) {
      if (line === '@@REPLY') { cur = 'reply'; out.reply = ''; continue; }
      if (line === '@@A7') { cur = 'a7'; out.a7 = ''; continue; }
      if (line === '@@DLOG') { cur = 'dlog'; out.dlog = ''; continue; }
      if (cur) out[cur] += line + '\n';
    }
    out.exit = res.headers.get('X-Exit-Code');
    out.ms = res.headers.get('X-Duration-Ms');
    return out;
  }

  /** Run a command on the camera. opts: {a7, dlog, quiet, timeoutMs} */
  function run(cmd, opts = {}) {
    pending++; setBusy();
    const entry = opts.quiet ? null : logStart(cmd);
    const task = chain.then(async () => {
      const q = new URLSearchParams({ cmd, a7: opts.a7 ? '1' : '0', dlog: opts.dlog ? '1' : '0' });
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), opts.timeoutMs || 120000);
      try {
        const res = await fetch('cgi-bin/run?' + q.toString(), { signal: ctl.signal, cache: 'no-store' });
        const r = parseRun(await res.text(), res);
        if (entry) logFinish(entry, r);
        return r;
      } catch (e) {
        const r = { reply: '', a7: null, dlog: null, exit: 'ERR', ms: null, error: String(e) };
        if (entry) logFinish(entry, r);
        return r;
      } finally {
        clearTimeout(timer);
        pending--; setBusy();
      }
    });
    chain = task.catch(() => {});
    return task;
  }

  // ---------- debug log panel ----------
  const logEl = $('log');
  const history = [];
  function logStart(cmd) {
    const div = document.createElement('div');
    div.className = 'log-entry run card mb-2 ps-2';
    div.innerHTML = `<div class="d-flex gap-2 align-items-center py-1 pe-2">
        <span class="text-body-secondary">${stamp()}</span>
        <code class="flex-grow-1">${esc(cmd)}</code>
        <span class="badge text-bg-warning meta">running…</span>
        <button class="btn btn-sm btn-link p-0 copy">copy</button></div><div class="body pe-2 pb-1"></div>`;
    logEl.prepend(div);
    const rec = { time: stamp(), cmd, div };
    history.push(rec);
    div.querySelector('.copy').onclick = () => navigator.clipboard && navigator.clipboard.writeText(recText(rec));
    return rec;
  }
  function section(title, text, open) {
    const t = (text || '').replace(/\s+$/, '');
    const lines = t ? t.split('\n').length : 0;
    return `<details ${open ? 'open' : ''}><summary class="small text-body-secondary">${title} (${lines} lines)</summary>
      <pre class="bg-body-tertiary p-1 rounded">${esc(t || '(nothing)')}</pre></details>`;
  }
  function logFinish(rec, r) {
    Object.assign(rec, r);
    const ok = r.exit === '0';
    rec.div.classList.remove('run');
    rec.div.classList.add(ok ? 'ok' : 'err');
    const meta = rec.div.querySelector('.meta');
    meta.className = 'badge meta ' + (ok ? 'text-bg-success' : 'text-bg-danger');
    meta.textContent = r.error ? 'request failed' : `exit ${r.exit} · ${r.ms} ms`;
    let html = section('reply', r.error ? r.error : r.reply, true);
    if (r.a7 !== null) html += section('A7 capture log (new lines)', r.a7, !r.reply.trim() && !!r.a7.trim());
    if (r.dlog !== null) html += section('Linux dlog (new lines)', r.dlog, false);
    rec.div.querySelector('.body').innerHTML = html;
    applyLogFilter();
  }
  function recText(r) {
    return `[${r.time}] $ ${r.cmd}\nexit ${r.exit} (${r.ms} ms)\n--- reply\n${r.reply || ''}` +
      (r.a7 !== null && r.a7 !== undefined ? `--- A7\n${r.a7}` : '') +
      (r.dlog !== null && r.dlog !== undefined ? `--- dlog\n${r.dlog}` : '') + (r.error ? `--- error\n${r.error}\n` : '');
  }
  function applyLogFilter() {
    const f = $('log-filter').value.toLowerCase();
    for (const r of history) r.div.classList.toggle('d-none', !!f && !recText(r).toLowerCase().includes(f));
  }
  $('log-filter').oninput = applyLogFilter;
  $('btn-log-clear').onclick = () => { history.length = 0; logEl.innerHTML = ''; };
  $('btn-log-save').onclick = () => {
    const blob = new Blob([history.map(recText).join('\n')], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `gear360-log-${new Date().toISOString().replace(/[:.]/g, '-')}.txt`;
    a.click();
  };

  // ---------- confirm modal ----------
  const modal = new bootstrap.Modal($('confirm'));
  function confirmRun(cmd, note) {
    return new Promise((resolve) => {
      $('confirm-text').textContent = cmd;
      $('confirm-note').textContent = note || '';
      const ok = $('confirm-ok');
      const done = (v) => { ok.onclick = null; $('confirm').removeEventListener('hidden.bs.modal', cancel); resolve(v); };
      const cancel = () => done(false);
      ok.onclick = () => { modal.hide(); done(true); };
      $('confirm').addEventListener('hidden.bs.modal', cancel, { once: true });
      modal.show();
    });
  }
  const opts = () => ({ a7: $('opt-a7').checked, dlog: $('opt-dlog').checked });

  // ---------- command menu ----------
  const RISK_NOTE = {
    set: 'Changes a camera setting. Note the current value so you can restore it.',
    action: 'Triggers an action (capture, test, dump…). It may hang the camera app and need a power cycle.',
    unknown: 'Not classified yet. Check what it does before running.',
  };
  async function runFromMenu(c) {
    const cmd = c.run || c.command;
    if (c.risk === 'never') return;
    if (c.risk !== 'read' && !(await confirmRun(cmd, RISK_NOTE[c.risk] || ''))) return;
    const o = opts();
    if (/^st app\b/.test(cmd)) o.dlog = true; // st app prints to dlog, not the reply
    run(cmd, o);
  }
  function renderCommands() {
    const f = $('cmd-filter').value.toLowerCase();
    const showNever = $('opt-never').checked;
    const fams = new Map();
    (window.COMMANDS || []).forEach((c, i) => {
      if (c.risk === 'never' && !showNever) return;
      const hay = `${c.family} ${c.command} ${c.run} ${c.description} ${c.result_notes}`.toLowerCase();
      if (f && !hay.includes(f)) return;
      if (!fams.has(c.family)) fams.set(c.family, []);
      fams.get(c.family).push([i, c]);
    });
    let html = '';
    let n = 0;
    for (const [fam, rows] of fams) {
      const id = 'fam' + (n++);
      html += `<div class="accordion-item"><h2 class="accordion-header">
        <button class="accordion-button ${f ? '' : 'collapsed'} py-2" data-bs-toggle="collapse" data-bs-target="#${id}">
        ${esc(fam)} <span class="badge text-bg-secondary ms-2">${rows.length}</span></button></h2>
        <div id="${id}" class="accordion-collapse collapse ${f ? 'show' : ''}"><div class="accordion-body p-1"><ul class="list-group list-group-flush">`;
      for (const [i, c] of rows) {
        const runnable = c.risk !== 'never' && (c.run || '').trim();
        const tested = c.tested ? `<span class="badge text-bg-dark border">${esc(c.tested)}</span>` : '';
        html += `<li class="list-group-item cmd-row px-1 py-1">
          <div class="d-flex gap-2 align-items-start">
            <span class="badge risk-${esc(c.risk || 'unknown')}">${esc(c.risk || '?')}</span>
            <div class="flex-grow-1"><code>${esc(c.run || c.command)}</code>
              <div class="small text-body-secondary">${esc(c.description)}</div>
              ${c.result_notes ? `<div class="small fst-italic text-info-emphasis">${esc(c.result_notes)}</div>` : ''}</div>
            ${tested}
            ${runnable ? `<button class="btn btn-sm btn-outline-primary run-cmd" data-i="${i}">Run</button>`
                       : `<button class="btn btn-sm btn-outline-secondary use-cmd" data-i="${i}" title="copy to custom box">Edit</button>`}
          </div></li>`;
      }
      html += '</ul></div></div></div>';
    }
    $('cmd-list').innerHTML = html || '<div class="text-body-secondary small p-2">no matches</div>';
    $('cmd-list').querySelectorAll('.run-cmd').forEach((b) => { b.onclick = () => runFromMenu(window.COMMANDS[+b.dataset.i]); });
    $('cmd-list').querySelectorAll('.use-cmd').forEach((b) => {
      b.onclick = () => { const c = window.COMMANDS[+b.dataset.i]; $('cmd-custom').value = c.run || c.command.split(' | ')[0]; $('cmd-custom').focus(); };
    });
  }
  $('cmd-filter').oninput = renderCommands;
  $('opt-never').onchange = renderCommands;
  $('btn-run-custom').onclick = async () => {
    const cmd = $('cmd-custom').value.trim();
    if (!cmd) return;
    if (!(await confirmRun(cmd, 'Custom command: runs as root on the camera.'))) return;
    run(cmd, opts());
  };
  $('cmd-custom').onkeydown = (e) => { if (e.key === 'Enter') $('btn-run-custom').click(); };

  // ---------- status ----------
  const STATUS_CMD = [
    'st cap capdtm getusr 1', 'st cap capdtm getusr 4', 'st cap capdtm getusr 5',
    'st cap iq awb wbgain', "df -h /sdcard | tail -1", 'ls /sdcard/*.raw 2>/dev/null | wc -l',
    'cat /sys/class/power_supply/battery/capacity 2>/dev/null',
  ].join('; echo @@; ');
  function badge(label, val, cls) { return `<span class="badge ${cls || 'text-bg-secondary'}">${esc(label)}: ${esc(val)}</span>`; }
  async function refreshStatus() {
    const r = await run(STATUS_CMD, { quiet: true });
    const p = r.reply.split('@@').map((s) => s.trim());
    const pick = (s) => ((s || '').match(/UserData is (\S+)/) || [])[1] || '?';
    const wb = (p[3] || '').match(/front is \d+ \d+ \d+ ([\d.]+) [\d.]+ ([\d.]+)/);
    const df = (p[4] || '').split(/\s+/);
    $('status').innerHTML =
      badge('mode', pick(p[0]).replace('SHOOTINGMODE_', '')) +
      badge('quality', pick(p[1]).replace('IMAGEQUALITY_', ''), /RAW/.test(p[1]) ? 'text-bg-danger' : 'text-bg-secondary') +
      badge('ISO', pick(p[2]).replace('ISO_', '')) +
      badge('WB R/B', wb ? `${wb[1]} / ${wb[2]}` : '?') +
      badge('SD free', df[3] || '?') +
      badge('raw in root', (p[5] || '?').trim(), 'text-bg-info') +
      (() => {
        const b = parseInt(p[6], 10);
        if (Number.isNaN(b)) return badge('battery', '?');
        return badge('battery', `${b}%`, b <= 15 ? 'text-bg-danger' : b <= 30 ? 'text-bg-warning' : 'text-bg-success');
      })();
    if (r.exit === 'ERR') $('status').innerHTML = badge('camera', 'not reachable', 'text-bg-danger');
  }
  $('btn-status').onclick = refreshStatus;

  // ---------- shooting helpers ----------
  async function listJpgs() {
    const r = await run('ls -1 /sdcard/DCIM/*/*.JPG 2>/dev/null', { quiet: true });
    return r.reply.split('\n').map((s) => s.trim()).filter((s) => /\.jpg$/i.test(s));
  }
  async function waitNewJpg(before, maxS) {
    for (let t = 0; t < maxS / 2; t++) {
      await sleep(2000);
      const j = (await listJpgs()).find((f) => !before.has(f));
      if (j) return j;
    }
    return null;
  }
  const WATCHER = '/sdcard/mods/rawwatch.sh';
  // Start the raw watcher if it isn't running (detached so it outlives this CGI request).
  async function ensureWatcher() {
    const r = await run(`if [ -f /tmp/rawwatch.pid ] && kill -0 $(cat /tmp/rawwatch.pid) 2>/dev/null; then echo running;`
      + ` elif [ -f ${WATCHER} ]; then setsid ${WATCHER} </dev/null >/dev/null 2>&1 & sleep 1; echo started;`
      + ' else echo missing; fi', { quiet: true });
    return r.reply.trim();
  }
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* not remembered */ } },
  };

  // ---------- exposure controls ----------
  // Shutter in 1/3 stops. TV for `st cap capdtm setvar TV n 4` = round(16*log2(1/t)); checked 0 (1 s) .. 207 (1/8000) vs EXIF.
  const SHUTTER_LABELS = ['1 s', '0.8 s', '0.6 s', '1/2', '1/2.5', '1/3', '1/4', '1/5', '1/6', '1/8', '1/10', '1/13', '1/15',
    '1/20', '1/25', '1/30', '1/40', '1/50', '1/60', '1/80', '1/100', '1/125', '1/160', '1/200', '1/250', '1/320', '1/400',
    '1/500', '1/640', '1/800', '1/1000', '1/1250', '1/1600', '1/2000', '1/2500', '1/3200', '1/4000', '1/5000', '1/6400', '1/8000'];
  const secs = (l) => (l.includes('/') ? 1 / parseFloat(l.split('/')[1]) : parseFloat(l));
  const SHUTTERS = SHUTTER_LABELS.map((label) => ({ label, tv: Math.round(16 * Math.log2(1 / secs(label))) }));
  // ISO options are the camera's own USERDATA_ISO table order (index 0 = AUTO).
  const ISOS = ['Auto', '100', '125', '160', '200', '250', '320', '400', '500', '640', '800', '1000', '1250', '1600',
    '2000', '2500', '3200', '4000', '5000', '6400'];
  const hex4 = (n) => n.toString(16).toUpperCase().padStart(4, '0');
  const isoCmd = (i) => `st cap capdtm setusr 5 0x0005${hex4(i)}`;
  const tvCmd = (i) => `st cap capdtm setvar TV ${SHUTTERS[i].tv} 4`;
  const MANUAL_CMD = 'st cap capdtm setusr 0 0x00000004; st cap capdtm setusr 1 0x00010004';  // dial 4 + MANUAL (2021 setup)
  const AUTO_CMD = 'st cap capdtm setusr 0 0x00000002; st cap capdtm setusr 1 0x00010001';    // PROGRAM

  const slS = $('sl-shutter');
  const slI = $('sl-iso');
  function showShutter() { $('lbl-shutter').textContent = SHUTTERS[+slS.value].label; }
  function showIso() { $('lbl-iso').textContent = ISOS[+slI.value]; }
  function setManualUi(manual) {
    $('mode-manual').checked = manual;
    $('mode-auto').checked = !manual;
    slS.disabled = !manual;
    $('hint-shutter').textContent = manual ? '' : '(set by the camera in Auto)';
    $('lab-shutter').classList.toggle('opacity-50', !manual);
    slS.classList.toggle('opacity-50', !manual);
  }
  slS.oninput = showShutter;
  slI.oninput = showIso;
  slS.onchange = () => { if ($('mode-manual').checked) run(tvCmd(+slS.value), opts()); };
  slI.onchange = () => run(isoCmd(+slI.value), opts());
  $('mode-manual').onchange = () => { setManualUi(true); run(`${MANUAL_CMD}; ${tvCmd(+slS.value)}`, opts()); };
  $('mode-auto').onchange = () => { setManualUi(false); run(AUTO_CMD, opts()); };
  $('sw-isonr').onchange = (e) => run(`st cap capdtm setusr 30 ${e.target.checked ? '0x001E0002' : '0x001E0000'}`, opts());
  $('sw-ltnr').onchange = (e) => run(`st cap capdtm setusr 31 ${e.target.checked ? '0x001F0001' : '0x001F0000'}`, opts());
  $('sw-timer').onchange = (e) => {
    store.set('gear360-timer', e.target.checked ? 'on' : 'off');
    run(`st app set timer ${e.target.checked ? 'on' : 'off'}`, { ...opts(), dlog: true });
  };

  // RAW dump: the camera can't report it and it resets on reboot; /tmp/rawdump_on (tmpfs) records it per boot.
  let bootId = '';
  function showRawState() {
    $('raw-state').textContent = $('sw-raw').checked ? 'raw dump on (resets on reboot)' : '';
  }
  $('sw-raw').onchange = async (e) => {
    if (e.target.checked) {
      // /tmp/rawdump_on records that the dump is on (it lives in tmpfs, so it clears on reboot like the dump does);
      // the Power double-press RAW script (mods/G360POWE_G360POW.sh) sets it too
      await run('st cap seq dump on ssif; touch /tmp/rawdump_on', opts());
      const w = await ensureWatcher();
      if (w === 'missing') $('raw-state').textContent = 'watcher script missing on the card!';
      else showRawState();
    } else {
      // Never `st cap seq dump off ssif`: it stores 0xFFFFFFEF into the A7 post-processing dump flag and photos turn
      // green until a reboot. Clear the flag word directly instead (only if it holds exactly 0x10, the ssif dump).
      const r = await run('if st readl 0x8196a1c8 | grep -q "h:00000010,"; then st writel 0x8196a1c8 0;'
        + ' rm -f /tmp/rawdump_on; echo rawdump_cleared; else st readl 0x8196a1c8; fi', opts());
      if (!r.reply.includes('rawdump_cleared')) {
        e.target.checked = true;
        $('raw-state').textContent = 'dump flag not as expected, left alone (reboot clears it)';
      } else showRawState();
    }
  };

  async function readCameraState() {
    const r = await run('cat /proc/sys/kernel/random/boot_id; echo @@; st cap capdtm getusr 1; echo @@; st cap capdtm getusr 5;'
      + ' echo @@; st cap capdtm getvar TV; echo @@; st cap capdtm getusr 30; echo @@; st cap capdtm getusr 31;'
      + ' echo @@; [ -f /tmp/rawdump_on ] && echo rawdump_on', { quiet: true });
    const p = r.reply.split('@@').map((x) => x.trim());
    const opt = (x) => { const m = (x || '').match(/\(0x([0-9a-f]+)\)/i); return m ? parseInt(m[1], 16) & 0xffff : null; };
    bootId = p[0] || '';
    setManualUi(opt(p[1]) === 4);
    const iso = opt(p[2]);
    if (iso !== null && iso < ISOS.length) slI.value = iso;
    const tvm = (p[3] || '').match(/0x[0-9a-f]+_([0-9a-f]+)/i);
    if (tvm) {
      const tv = parseInt(tvm[1], 16);
      let best = 0;
      SHUTTERS.forEach((x, i) => { if (Math.abs(x.tv - tv) < Math.abs(SHUTTERS[best].tv - tv)) best = i; });
      slS.value = best;
    }
    $('sw-isonr').checked = (opt(p[4]) || 0) !== 0;
    $('sw-ltnr').checked = (opt(p[5]) || 0) !== 0;
    $('sw-timer').checked = store.get('gear360-timer') !== 'off';
    $('sw-raw').checked = (p[6] || '').includes('rawdump_on');
    showShutter(); showIso(); showRawState();
  }

  // ---------- take photo / burst ----------
  $('btn-photo').onclick = () => run('st key click s2', opts());
  $('btn-burst').onclick = async () => {
    const n = Math.max(2, Math.min(50, +$('burst-n').value || 5));
    for (let i = 0; i < n; i++) {
      const before = new Set(await listJpgs());
      await run('st key click s2', opts());
      if (!(await waitNewJpg(before, 60))) break;
    }
    refreshFiles();
  };

  // ---------- bracket / HDR ----------
  for (const id of ['br-slow', 'br-fast']) {
    $(id).innerHTML = SHUTTERS.map((x, i) => `<option value="${i}">${x.label}</option>`).join('');
  }
  $('br-slow').value = String(SHUTTER_LABELS.indexOf('1 s'));
  $('br-fast').value = String(SHUTTER_LABELS.indexOf('1/8000'));
  function bracketList() {
    const lo = Math.min(+$('br-slow').value, +$('br-fast').value);
    const hi = Math.max(+$('br-slow').value, +$('br-fast').value);
    const step = +$('br-step').value;   // in 1/3-stop slider steps (3 = 1 stop)
    const out = [];
    for (let i = lo; i <= hi; i += step) out.push(i);
    if (out[out.length - 1] !== hi) out.push(hi);   // always end exactly on the chosen fastest speed
    return out;
  }
  function showBracket() {
    const l = bracketList();
    $('br-preview').textContent = `${l.length} frames: ` + l.map((i) => SHUTTERS[i].label).join(', ');
  }
  ['br-slow', 'br-fast', 'br-step'].forEach((id) => { $(id).onchange = showBracket; });
  showBracket();
  let stopBracket = false;
  $('btn-bracket-stop').onclick = () => { stopBracket = true; };
  $('btn-bracket').onclick = async () => {
    const list = bracketList();
    const isoIdx = +slI.value === 0 ? 1 : +slI.value;   // Auto -> ISO 100
    const timerWasOn = $('sw-timer').checked;
    if (!(await confirmRun(`bracket at ISO ${ISOS[isoIdx]}: ${list.map((i) => SHUTTERS[i].label).join(', ')}`,
      'Switches to Manual with NR off and shoots each speed, waiting for every JPEG.'
      + (timerWasOn ? ' The self-timer delays the first frame only; it is turned off for the rest and back on at the end.' : '')))) return;
    stopBracket = false;
    const el = $('br-steps');
    el.innerHTML = '';
    const add = (t, c) => { const li = document.createElement('li'); li.className = c || ''; li.textContent = `${stamp()}  ${t}`; el.append(li); };
    const setTimer = async (on) => { await run(`st app set timer ${on ? 'on' : 'off'}`, { ...opts(), dlog: true }); };
    await run(`st cap capdtm setusr 30 0x001E0000; st cap capdtm setusr 31 0x001F0000; ${isoCmd(isoIdx)}; ${MANUAL_CMD}`, opts());
    setManualUi(true);
    $('sw-isonr').checked = false;
    $('sw-ltnr').checked = false;
    slI.value = isoIdx; showIso();
    add(`Manual, ISO ${ISOS[isoIdx]}, NR off${timerWasOn ? '; self-timer on for the first frame' : ''}`);
    let timerOff = false;
    const t0 = Date.now();
    const busyBtns = ['btn-bracket', 'btn-photo', 'btn-burst'];
    busyBtns.forEach((id) => { $(id).disabled = true; });
    $('br-progress').classList.remove('d-none');
    $('br-bar').classList.add('progress-bar-animated');
    const progress = (done) => {
      $('br-bar').style.width = `${Math.round((100 * done) / list.length)}%`;
      $('br-bar').textContent = `${done}/${list.length} · ${Math.round((Date.now() - t0) / 1000)} s`;
    };
    progress(0);
    try {
      for (const [k, i] of list.entries()) {
        if (stopBracket) { add('stopped', 'text-warning'); break; }
        const before = new Set(await listJpgs());
        await run(`${tvCmd(i)}; st key click s2`, opts());
        slS.value = i; showShutter();
        const j = await waitNewJpg(before, 60);
        add(j ? `${SHUTTERS[i].label} -> ${j.split('/').pop()}` : `${SHUTTERS[i].label}: no JPEG after 60 s, stopping`,
          j ? 'text-success' : 'text-danger');
        if (!j) break;
        progress(k + 1);
        if (timerWasOn && !timerOff) { await setTimer(false); timerOff = true; add('self-timer off for the remaining frames'); }
      }
    } finally {
      if (timerOff) { await setTimer(true); add('self-timer back on'); }
      busyBtns.forEach((id) => { $(id).disabled = false; });
      $('br-bar').classList.remove('progress-bar-animated');
    }
    add('done');
    refreshFiles();
  };

  // ---------- tools ----------
  $('btn-wb').onclick = () => run('st cap iq awb wbgain', opts());
  $('btn-lockinfo').onclick = () => run('st cap lockinfo', opts());
  $('btn-usrlist').onclick = () => run('st cap capdtm usrlist', opts());
  $('btn-watch-log').onclick = () => run('echo "pid: $(cat /tmp/rawwatch.pid 2>/dev/null)"; cat /tmp/rawwatch.log 2>&1 | tail -n 50', {});

  // ---------- files ----------
  const fmtSize = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB'
    : n >= 1024 ? (n / 1024).toFixed(0) + ' KB' : n + ' B');
  let files = [];
  async function refreshFiles() {
    try {
      const res = await fetch('cgi-bin/files', { cache: 'no-store' });
      files = (await res.text()).split('\n').filter(Boolean).map((l) => {
        const [path, size, mtime] = l.split('|');
        return { path, size: +size, mtime: +mtime };
      }).sort((a, b) => b.mtime - a.mtime);
    } catch (e) { files = []; }
    renderFiles();
    $('files-updated').textContent = `updated ${stamp()} · auto every 15 s`;
  }
  // Group the flat file list into shots: 360_NNNN.JPG + 360_NNNN.raw + 360_NNNN_wb.txt (and leftover root dumps).
  function shotGroups() {
    const g = new Map();
    for (const f of files) {
      const base = f.path.replace(/_wb\.txt$/, '').replace(/\.(jpg|raw|mp4)$/i, '');
      if (!g.has(base)) g.set(base, { base, jpg: null, raw: null, wb: null, mp4: null, mtime: 0 });
      const r = g.get(base);
      if (/\.jpg$/i.test(f.path)) r.jpg = f;
      else if (f.path.endsWith('.raw')) r.raw = f;
      else if (f.path.endsWith('_wb.txt')) r.wb = f;
      else if (/\.mp4$/i.test(f.path)) r.mp4 = f;
      r.mtime = Math.max(r.mtime, f.mtime);
    }
    return [...g.values()].sort((x, y) => y.mtime - x.mtime);
  }
  const fileUrl = (f) => 'cgi-bin/get?path=' + encodeURIComponent(f.path);
  function fileBadges(r) {
    // each badge shows its file's size, e.g. "JPEG 5.3 MB"
    const b = (f, label, cls) => (f
      ? `<a class="badge ${cls} text-decoration-none" href="${esc(fileUrl(f))}&dl=1" download="${esc(f.path.split('/').pop())}" title="download">${label} ${esc(fmtSize(f.size))}</a>`
      : '');
    return b(r.jpg, 'JPEG', 'text-bg-primary') + b(r.raw, 'RAW', 'text-bg-warning')
      + (r.wb ? `<a class="badge text-bg-info text-decoration-none" href="${esc(fileUrl(r.wb))}" target="_blank" title="white balance">WB ${esc(fmtSize(r.wb.size))}</a>` : '')
      + b(r.mp4, 'MP4', 'text-bg-secondary');
  }
  function renderFiles() {
    const k = $('files-kind').value;
    const groups = shotGroups().filter((r) => k === 'all' || (k === 'raw' && r.raw) || (k === 'noraw' && !r.raw));
    $('files-body').innerHTML = groups.map((r) => {
      const view = r.jpg ? `<a href="#" role="button" class="btn btn-sm btn-link p-0 prev" data-p="${esc(r.jpg.path)}">view</a>` : '';
      return `<tr><td class="font-monospace">${esc(r.base.replace('/sdcard/', '').replace(/^DCIM\/[^/]+\//, ''))}</td>
        <td class="text-nowrap">${new Date(r.mtime * 1000).toLocaleString()}</td>
        <td><div class="d-flex gap-1">${fileBadges(r)}</div></td><td>${view}</td></tr>`;
    }).join('') || '<tr><td colspan="4" class="text-body-secondary">no files (press Refresh)</td></tr>';
    $('files-body').querySelectorAll('.prev').forEach((b) => {
      b.onclick = (e) => { e.preventDefault(); openViewer(b.dataset.p); };
    });
    renderLastShot(groups);
    notifyNewShots();
  }

  // ---------- last shot card + toasts ----------
  function renderLastShot() {
    const r = shotGroups().find((x) => x.jpg);
    if (!r) { $('last-shot').classList.add('d-none'); return; }
    $('last-shot').classList.remove('d-none');
    const thumb = 'cgi-bin/thumb?path=' + encodeURIComponent(r.jpg.path);
    if ($('last-thumb').dataset.p !== r.jpg.path) { $('last-thumb').src = thumb; $('last-thumb').dataset.p = r.jpg.path; }
    $('last-thumb').onclick = () => openViewer(r.jpg.path);
    $('last-name').textContent = r.base.split('/').pop();
    $('last-time').textContent = new Date(r.jpg.mtime * 1000).toLocaleTimeString();
    $('last-badges').innerHTML = fileBadges(r);
  }
  const seen = new Map();   // base -> 'jpg' | 'jpg+raw'
  let firstListing = true;
  function toast(html) {
    const el = document.createElement('div');
    el.className = 'toast align-items-center text-bg-dark border-0';
    el.innerHTML = `<div class="d-flex"><div class="toast-body">${html}</div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
    $('toasts').append(el);
    const t = new bootstrap.Toast(el, { delay: 6000 });
    el.addEventListener('hidden.bs.toast', () => el.remove());
    t.show();
  }
  function notifyNewShots() {
    for (const r of shotGroups()) {
      if (!r.jpg) continue;
      const state = r.raw ? 'jpg+raw' : 'jpg';
      const prev = seen.get(r.base);
      if (!firstListing && prev !== state) {
        const name = r.base.split('/').pop();
        toast(prev ? `${esc(name)}: RAW saved` : `${esc(name)} saved${r.raw ? ' (+RAW)' : ''}`);
      }
      seen.set(r.base, state);
    }
    firstListing = false;
  }
  $('btn-files').onclick = refreshFiles;
  // Auto-refresh the file list every 15 s while the page is visible (files CGI only, not the st command queue).
  let filesBusy = false;
  setInterval(async () => {
    if (document.visibilityState !== 'visible' || filesBusy) return;
    filesBusy = true;
    try { await refreshFiles(); } finally { filesBusy = false; }
  }, 15000);
  $('files-kind').onchange = renderFiles;

  // ---------- photo viewer (modal, left/right through the JPEGs) ----------
  const viewer = new bootstrap.Modal($('viewer'));
  let viewList = [];
  let viewIdx = 0;
  // Camera JPEGs carry a 1920x960 preview (MPF "Large Thumbnail") after the main image. Read the first 128 KB,
  // find the MPF index (APP2 "MPF\0"), and return [offset, length] of the second image, or null.
  async function findPreview(path) {
    const head = await fetch(`cgi-bin/get?path=${encodeURIComponent(path)}&off=0&len=131072`, { cache: 'no-store' });
    const d = new DataView(await head.arrayBuffer());
    for (let i = 0; i + 4 < d.byteLength; i++) {
      if (d.getUint32(i) !== 0x4d504600) continue;   // "MPF\0"
      const base = i + 4;
      const le = d.getUint16(base) === 0x4949;
      const u16 = (o) => d.getUint16(base + o, le);
      const u32 = (o) => d.getUint32(base + o, le);
      const ifd = u32(4);
      for (let k = 0; k < u16(ifd); k++) {
        const e = ifd + 2 + 12 * k;
        if (u16(e) !== 0xb002) continue;   // MPEntry: 16 bytes per image (attr, size, offset, 2 x dependent)
        const val = u32(e + 8);
        for (let m = 1; m < u32(e + 4) / 16; m++) {
          const size = u32(val + 16 * m + 4);
          const off = u32(val + 16 * m + 8);
          if (off && size) return [off + base, size];   // MPF offsets are relative to the MP header
        }
      }
      return null;
    }
    return null;
  }
  let viewToken = 0;
  async function showView() {
    const f = viewList[viewIdx];
    if (!f) return;
    const url = 'cgi-bin/get?path=' + encodeURIComponent(f.path);
    const token = ++viewToken;
    $('viewer-res').textContent = 'loading preview…';
    let src = url;
    let res = 'full size (no embedded preview found)';
    try {
      const p = await findPreview(f.path);
      if (p) {
        const r = await fetch(`${url}&off=${p[0]}&len=${p[1]}`, { cache: 'no-store' });
        src = URL.createObjectURL(await r.blob());
        res = `embedded preview, ${fmtSize(p[1])} of ${fmtSize(f.size)}`;
      }
    } catch (e) { /* fall back to the full image */ }
    if (token !== viewToken) return;   // the user already moved to another photo
    const old = $('viewer-img').src;
    if (old.startsWith('blob:')) URL.revokeObjectURL(old);
    $('viewer-img').src = src;
    $('viewer-img').onload = () => {
      $('viewer-res').textContent = `${$('viewer-img').naturalWidth}x${$('viewer-img').naturalHeight} · ${res}`;
    };
    $('viewer-title').textContent = `${f.path.split('/').pop()}  (${viewIdx + 1}/${viewList.length})`;
    $('viewer-dl').href = url + '&dl=1';
    $('viewer-dl').setAttribute('download', f.path.split('/').pop());
  }
  function openViewer(path) {
    viewList = files.filter((f) => /\.jpg$/i.test(f.path));
    viewIdx = Math.max(0, viewList.findIndex((f) => f.path === path));
    showView();
    viewer.show();
  }
  const step = (d) => { if (viewList.length) { viewIdx = (viewIdx + d + viewList.length) % viewList.length; showView(); } };
  $('viewer-prev').onclick = () => step(-1);   // list is newest first: "prev" = newer
  $('viewer-next').onclick = () => step(1);
  document.addEventListener('keydown', (e) => {
    if (!$('viewer').classList.contains('show')) return;
    if (e.key === 'ArrowLeft') step(-1);
    if (e.key === 'ArrowRight') step(1);
  });

  // ---------- clock sync (the hotspot has no internet/NTP, so use this device's clock) ----------
  // Browser's IANA zone (e.g. America/New_York); only simple zone names are passed to the shell.
  const browserTz = (() => {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) { return ''; }
  })();
  const safeTz = /^[A-Za-z0-9_+\-]+(\/[A-Za-z0-9_+\-]+)*$/.test(browserTz) ? browserTz : '';
  async function syncTimezone() {
    if (!safeTz) return;
    const r = await run('readlink /opt/etc/localtime', { quiet: true });
    if (r.reply.trim() === `/usr/share/zoneinfo/${safeTz}`) return;
    await run(`if [ -f /usr/share/zoneinfo/${safeTz} ]; then ln -sf /usr/share/zoneinfo/${safeTz} /opt/etc/localtime`
      + ` && echo "timezone set to ${safeTz}: $(date)"; else echo "timezone ${safeTz} not on camera; left as $(readlink /opt/etc/localtime)"; fi`, {});
  }
  async function syncClock(auto) {
    await syncTimezone();
    const r = await run('date +%s', { quiet: true });
    const cam = parseInt(r.reply, 10);
    const now = Math.round(Date.now() / 1000);
    const badgeEl = $('clock');
    if (Number.isNaN(cam)) { badgeEl.className = 'badge text-bg-danger'; badgeEl.textContent = 'clock ?'; return; }
    const off = now - cam;
    if (auto && Math.abs(off) <= 5) {
      badgeEl.className = 'badge text-bg-success';
      badgeEl.textContent = 'clock OK';
      return;
    }
    // date -s sets the system clock; hwclock -f /dev/rtc0 -w -u writes the hardware RTC in UTC.
    // (hwclock prints select()/adjtime warnings on this camera but the write works; checked 2026-10-10.)
    await run(`date -s @${Math.round(Date.now() / 1000)} >/dev/null && echo "camera clock was off by ${off} s; now: $(date -u)";`
      + ' hwclock -f /dev/rtc0 -w -u >/dev/null 2>&1;'
      + ' echo "RTC (UTC): $(cat /sys/class/rtc/rtc0/date) $(cat /sys/class/rtc/rtc0/time)"', {});
    badgeEl.className = 'badge text-bg-success';
    badgeEl.textContent = `clock synced (was ${off > 0 ? '-' : '+'}${Math.abs(off)} s)`;
  }
  $('btn-clock').onclick = () => syncClock(false);

  // ---------- light/dark theme (light by default; choice remembered per browser) ----------
  function setTheme(t) {
    document.documentElement.setAttribute('data-bs-theme', t);
    $('btn-theme').textContent = t === 'light' ? 'Dark' : 'Light';
    try { localStorage.setItem('gear360-theme', t); } catch (e) { /* storage blocked: theme just isn't remembered */ }
  }
  let savedTheme = 'light';
  try { savedTheme = localStorage.getItem('gear360-theme') || 'light'; } catch (e) { /* use default */ }
  setTheme(savedTheme);
  $('btn-theme').onclick = () => setTheme(document.documentElement.getAttribute('data-bs-theme') === 'light' ? 'dark' : 'light');

  // ---------- start ----------
  renderCommands();
  syncClock(true).then(readCameraState);
  ensureWatcher();
  refreshStatus();
  refreshFiles();
})();
