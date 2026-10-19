(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const csrf = $('meta[name=csrf]').content;
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const hue = pid => { let h = 0; for (const c of pid) h = (h * 31 + c.charCodeAt(0)) % 360; return h; };
  const color = pid => `hsl(${hue(pid)} 62% 66%)`;

  async function call(url, body) {
    const opt = body === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, body: JSON.stringify(body)
    };
    const r = await fetch(url, opt);
    let data = {};
    try { data = await r.json(); } catch (e) { /* ignore */ }
    if (!r.ok) throw new Error(data.error || (r.status === 401 ? 'Your session expired. Log in again.' : 'Request failed (' + r.status + ').'));
    return data;
  }

  /* ---------- tabs ---------- */
  document.querySelectorAll('.tab').forEach(t => t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(x => x.setAttribute('aria-selected', x === t));
    document.querySelectorAll('.pane').forEach(p => p.hidden = p.id !== t.dataset.pane);
    if (t.dataset.pane === 'p-res') loadRes();
  }));

  /* ---------- editable rows ---------- */
  function addRow(tbody, cells, types) {
    const tr = document.createElement('tr');
    cells.forEach((v, i) => {
      const td = document.createElement('td');
      const inp = document.createElement('input');
      inp.type = types[i]; inp.value = v; if (types[i] === 'number') inp.min = 0;
      td.appendChild(inp); tr.appendChild(td);
    });
    const td = document.createElement('td');
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'btn ghost sm'; b.textContent = 'Remove';
    b.onclick = () => tr.remove(); td.appendChild(b); tr.appendChild(td);
    tbody.appendChild(tr);
  }
  const readRows = (tbody, keys) => [...tbody.querySelectorAll('tr')].map(tr => {
    const v = [...tr.querySelectorAll('input')].map(i => i.value);
    return Object.fromEntries(keys.map((k, i) => [k, v[i]]));
  });

  /* ---------- scheduler ---------- */
  const procRows = $('#procRows');
  [['P1', 0, 5, 2], ['P2', 1, 3, 1], ['P3', 2, 8, 4], ['P4', 3, 6, 3]].forEach(r => addRow(procRows, r, ['text', 'number', 'number', 'number']));
  $('#addProc').onclick = () => addRow(procRows, ['P' + (procRows.children.length + 1), 0, 1, 1], ['text', 'number', 'number', 'number']);
  $('#algo').onchange = e => $('#qWrap').hidden = e.target.value !== 'RR';
  const procs = () => readRows(procRows, ['pid', 'arrival', 'burst', 'priority']);

  function gantt(res) {
    const scale = Math.max(26, Math.min(48, 900 / Math.max(1, res.gantt[res.gantt.length - 1].end)));
    const total = res.gantt[res.gantt.length - 1].end * scale;
    let seg = '', ticks = '';
    res.gantt.forEach(g => {
      const idle = g.pid === 'IDLE';
      seg += `<div class="gseg ${idle ? 'idle' : ''}" style="position:absolute;left:${g.start * scale}px;width:${(g.end - g.start) * scale}px;${idle ? '' : 'background:' + color(g.pid)}">${esc(idle ? 'idle' : g.pid)}</div>`;
    });
    const marks = [...new Set(res.gantt.flatMap(g => [g.start, g.end]))];
    marks.forEach(t => ticks += `<span style="position:absolute;left:${t * scale}px;border-left:1px solid var(--line);padding-left:3px;font-size:.75rem;color:var(--muted)">${t}</span>`);
    return `<div class="tscroll"><div style="position:relative;width:${total}px;height:46px;margin-top:.5rem;border:1px solid var(--line)">${seg}</div>
      <div style="position:relative;width:${total}px;height:22px">${ticks}</div></div>`;
  }

  function schedHtml(res) {
    const rows = res.table.map(r => `<tr><td><b style="color:${color(r.pid)}">${esc(r.pid)}</b></td><td>${r.arrival}</td><td>${r.burst}</td><td>${r.priority}</td><td>${r.completion}</td><td>${r.turnaround}</td><td>${r.waiting}</td><td>${r.response}</td></tr>`).join('');
    const states = res.states.map(s => `<li class="${s.to === 'RUNNING' ? 'RUNNING' : s.to === 'COMPLETED' ? 'COMPLETED' : 'READY'}"><b>t=${s.time}</b>${esc(s.pid)}: ${s.from} to ${s.to}</li>`).join('');
    const q = res.quantum ? ` (quantum ${res.quantum})` : '';
    return `<div class="panel mt"><h3>Gantt chart: ${esc(res.algorithm)}${q}</h3>${gantt(res)}
      <div class="stats mt"><div class="stat"><b>${res.avg_waiting}</b>Average waiting time</div><div class="stat"><b>${res.avg_turnaround}</b>Average turnaround</div>
      <div class="stat"><b>${res.avg_response}</b>Average response</div><div class="stat"><b>${res.cpu_utilization}%</b>CPU utilisation</div></div>
      <div class="tscroll"><table class="tbl"><thead><tr><th>Process</th><th>Arrival</th><th>Burst</th><th>Priority</th><th>Completion</th><th>Turnaround</th><th>Waiting</th><th>Response</th></tr></thead><tbody>${rows}</tbody></table></div></div>
      <div class="panel mt"><h3>Process manager: state changes</h3><ul class="log">${states}</ul></div>`;
  }

  $('#runSched').onclick = async () => {
    $('#schedErr').textContent = '';
    try {
      const res = await call('/api/schedule', { algorithm: $('#algo').value, quantum: $('#quantum').value, processes: procs() });
      $('#schedOut').innerHTML = schedHtml(res);
    } catch (e) { $('#schedErr').textContent = e.message; }
  };
  $('#runAll').onclick = async () => {
    $('#schedErr').textContent = '';
    try {
      const out = [];
      for (const a of ['FCFS', 'SJF', 'PRIORITY', 'RR'])
        out.push(await call('/api/schedule', { algorithm: a, quantum: $('#quantum').value, processes: procs() }));
      const best = Math.min(...out.map(o => o.avg_waiting));
      const rows = out.map(o => `<tr><td><b>${o.algorithm}</b>${o.quantum ? ' (q=' + o.quantum + ')' : ''}</td><td>${o.avg_waiting} ${o.avg_waiting === best ? '<span class="chip ok">lowest</span>' : ''}</td><td>${o.avg_turnaround}</td><td>${o.avg_response}</td><td>${o.cpu_utilization}%</td></tr>`).join('');
      $('#schedOut').innerHTML = `<div class="panel mt"><h3>Algorithm comparison</h3><div class="tscroll"><table class="tbl"><thead><tr><th>Algorithm</th><th>Avg waiting</th><th>Avg turnaround</th><th>Avg response</th><th>CPU use</th></tr></thead><tbody>${rows}</tbody></table></div></div>` +
        out.map(schedHtml).join('');
    } catch (e) { $('#schedErr').textContent = e.message; }
  };

  /* ---------- synchronisation ---------- */
  const syncRows = $('#syncRows');
  [['P1', 'A5', 0, 3], ['P2', 'A5', 1, 2], ['P3', 'B2', 1, 2]].forEach(r => addRow(syncRows, r, ['text', 'text', 'number', 'number']));
  $('#addSync').onclick = () => addRow(syncRows, ['P' + (syncRows.children.length + 1), 'A5', 0, 1], ['text', 'text', 'number', 'number']);
  async function runSync(useLock) {
    $('#syncErr').textContent = '';
    try {
      const res = await call('/api/sync', { use_lock: useLock, requests: readRows(syncRows, ['pid', 'seat', 'arrival', 'hold']) });
      const ev = res.events.map(e => `<li class="${e.state}"><b>t=${e.time}</b>${esc(e.message)}</li>`).join('');
      const rows = res.results.map(r => `<tr><td>${esc(r.pid)}</td><td>${esc(r.seat)}</td><td>${r.arrival}</td><td>${r.start}</td><td>${r.finish}</td><td>${r.wait}</td><td><span class="chip ${r.outcome === 'BOOKED' ? 'ok' : 'bad'}">${r.outcome}</span></td></tr>`).join('');
      $('#syncOut').innerHTML = `<div class="note ${res.conflicts.length ? 'bad' : 'good'}"><b>${res.use_lock ? 'With seat lock' : 'Without lock'}:</b> ${esc(res.summary)}</div>
        <div class="cols"><div class="panel"><h3>Timeline</h3><ul class="log">${ev}</ul></div>
        <div class="panel tscroll"><h3>Outcome</h3><table class="tbl"><thead><tr><th>Process</th><th>Seat</th><th>Arrives</th><th>Lock at</th><th>Done</th><th>Waited</th><th>Result</th></tr></thead><tbody>${rows}</tbody></table>
        <p class="small muted mt">In the real app this lock is <code>SELECT ... FOR UPDATE</code> on the seat rows inside one MySQL transaction.</p></div></div>`;
    } catch (e) { $('#syncErr').textContent = e.message; }
  }
  $('#runLock').onclick = () => runSync(true);
  $('#runNoLock').onclick = () => runSync(false);

  /* ---------- deadlock ---------- */
  const dl = $('#dl');
  const presets = {
    dead: 'P1 holds A5\nP2 holds A6\nP1 requests A6\nP2 requests A5',
    safe: 'P1 holds A5\nP2 requests A5\nP3 holds B1'
  };
  dl.value = presets.dead;
  $('#presetDead').onclick = () => dl.value = presets.dead;
  $('#presetSafe').onclick = () => dl.value = presets.safe;

  function parseLocks(text) {
    const holds = {}, requests = {};
    text.split('\n').forEach((line, i) => {
      if (!line.trim()) return;
      const m = line.trim().match(/^(\S+)\s+(holds|requests)\s+(\S+)$/i);
      if (!m) throw new Error(`Line ${i + 1}: write it as "P1 holds A5" or "P2 requests A5".`);
      const target = m[2].toLowerCase() === 'holds' ? holds : requests;
      (target[m[1]] = target[m[1]] || []).push(m[3].toUpperCase());
    });
    return { holds, requests };
  }

  function drawGraph(graph, cycles) {
    const svg = $('#graphSvg'), nodes = Object.keys(graph).sort();
    const cx = 200, cy = 130, R = nodes.length > 1 ? 90 : 0, pos = {};
    nodes.forEach((n, i) => { const a = -Math.PI / 2 + 2 * Math.PI * i / nodes.length; pos[n] = [cx + R * Math.cos(a), cy + R * Math.sin(a)]; });
    const inCycle = new Set();
    cycles.forEach(c => c.forEach((n, i) => inCycle.add(n + '>' + c[(i + 1) % c.length])));
    let out = `<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#b09d90"/></marker>
      <marker id="ahr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#e2776f"/></marker></defs>`;
    nodes.forEach(a => graph[a].forEach(b => {
      if (!pos[b]) return;
      const [x1, y1] = pos[a], [x2, y2] = pos[b];
      const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1, ux = dx / len, uy = dy / len;
      const sx = x1 + ux * 22, sy = y1 + uy * 22, ex = x2 - ux * 24, ey = y2 - uy * 24;
      const mx = (sx + ex) / 2 - uy * 22, my = (sy + ey) / 2 + ux * 22;
      const hot = inCycle.has(a + '>' + b);
      out += `<path d="M${sx},${sy} Q${mx},${my} ${ex},${ey}" fill="none" stroke="${hot ? '#e2776f' : '#b09d90'}" stroke-width="${hot ? 2.5 : 1.6}" marker-end="url(#${hot ? 'ahr' : 'ah'})"/>`;
    }));
    nodes.forEach(n => {
      const [x, y] = pos[n];
      out += `<circle cx="${x}" cy="${y}" r="20" fill="#22101a" stroke="${color(n)}" stroke-width="2.5"/><text x="${x}" y="${y + 4}" text-anchor="middle" fill="#f5ebd7" font-size="12" font-weight="700">${esc(n)}</text>`;
    });
    svg.innerHTML = out;
  }

  $('#runDead').onclick = async () => {
    $('#deadErr').textContent = '';
    try {
      const res = await call('/api/deadlock', parseLocks(dl.value));
      drawGraph(res.graph, res.cycles);
      const edges = Object.entries(res.graph).flatMap(([a, t]) => t.map(b => `${esc(a)} waits for ${esc(b)}`)).join('; ') || 'no waiting at all';
      let html = `<div class="note ${res.deadlock ? 'bad' : 'good'}"><b>${res.deadlock ? 'Deadlock detected' : 'No deadlock'}</b><br>${esc(res.explanation)}<br><span class="small muted">Wait-for edges: ${edges}.</span></div>`;
      if (res.deadlock) {
        html += `<div class="cols"><div class="panel"><h3>Recovery</h3><ol>${res.recovery.map(r => `<li>${esc(r)}</li>`).join('')}</ol>
          <p class="small muted">Graph after aborting ${res.victims.map(esc).join(', ')}: ${Object.keys(res.graph_after).length ? Object.entries(res.graph_after).map(([a, t]) => esc(a) + (t.length ? ' waits for ' + t.map(esc).join(', ') : ' is free to run')).join('; ') : 'empty'}.</p></div>
          <div class="panel"><h3>Prevention in CineSync</h3><ul>${res.prevention.map(r => `<li>${esc(r)}</li>`).join('')}</ul></div></div>`;
      }
      $('#deadOut').innerHTML = html;
    } catch (e) { $('#deadErr').textContent = e.message; }
  };

  /* ---------- resource monitor ---------- */
  let timer = null;
  async function loadRes() {
    try {
      const d = await call('/api/resources');
      $('#resMeta').textContent = `${d.totals.allocated} of ${d.totals.seats} seats allocated across the next ${d.shows.length} shows. Connection pool size: ${d.db_pool}. Updated ${d.server_time}.`;
      $('#resOut').innerHTML = d.shows.map(s => `<div class="bar"><span>${esc(s.title)}<br><span class="muted small">${esc(s.theatre)}, ${esc(s.when)}</span></span>
        <div class="meter"><i class="${s.pct >= 80 ? 'hot' : ''}" style="width:${s.pct}%"></i></div><span class="right">${s.sold}/${s.total} (${s.pct}%)</span></div>`).join('') || '<p class="muted">No upcoming shows.</p>';
    } catch (e) { $('#resMeta').textContent = e.message; }
  }
  $('#refreshRes').onclick = loadRes;
  $('#auto').onchange = e => { clearInterval(timer); if (e.target.checked) timer = setInterval(loadRes, 5000); };
})();
