const API = '/api/tasks';
let refreshInterval;
let _taskCache = {};

document.addEventListener('DOMContentLoaded', () => {
  let qcType = null;
  const qc = document.getElementById('quick-create');
  const qcBadge = document.getElementById('qc-badge');
  const qcInput = document.getElementById('qc-input');
  const qcTimeRow = document.getElementById('qc-time-row');
  const qcTimeLabel = document.getElementById('qc-time-label');
  const qcTime = document.getElementById('qc-time');

  function openQuickCreate(type) {
    qcType = type;
    if (type === 'pr_monitor') {
      qcBadge.textContent = '● PR Monitor';
      qcBadge.className = 'task-type type-pr_monitor';
      qcInput.placeholder = 'PR link [timeout minutes]';
      qcTimeLabel.textContent = 'Timeout (min)';
    } else {
      qcBadge.textContent = '⏰ Reminder';
      qcBadge.className = 'task-type type-reminder';
      qcInput.placeholder = 'Link [delay minutes]';
      qcTimeLabel.textContent = 'Delay (min)';
    }
    qcInput.value = '';
    qcTimeRow.classList.add('hidden');
    qc.classList.remove('hidden');
    qcInput.focus();
  }

  document.getElementById('btn-add-pr').onclick = () => openQuickCreate('pr_monitor');
  document.getElementById('btn-add-reminder').onclick = () => openQuickCreate('reminder');
  document.getElementById('qc-close').onclick = () => qc.classList.add('hidden');

  qcInput.addEventListener('keydown', async (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const raw = qcInput.value.trim();
      if (!raw) return;
      const parts = raw.split(/\s+/);
      const last = parts[parts.length - 1];
      if (parts.length > 1 && /^\d+$/.test(last) && parseInt(last) > 0) {
        await createQuickTask(parts.slice(0, -1).join(' '), parseInt(last));
      } else {
        qcTimeRow.classList.remove('hidden');
        qcTime.value = '30';
        qcTime.focus();
        qcTime.select();
      }
    } else if (e.key === 'Escape') {
      qc.classList.add('hidden');
    }
  });

  qcTime.addEventListener('keydown', async (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const link = qcInput.value.trim();
      const minutes = parseInt(qcTime.value);
      if (link && minutes > 0) await createQuickTask(link, minutes);
    } else if (e.key === 'Escape') {
      qc.classList.add('hidden');
    }
  });

  async function createQuickTask(link, minutes) {
    const body = { type: qcType, link };
    if (qcType === 'reminder') body.delay_minutes = minutes;
    if (qcType === 'pr_monitor') body.timeout_minutes = minutes;
    await fetch(API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    qc.classList.add('hidden');
    qcInput.value = '';
    loadTasks();
  }

  loadTasks();
  loadBreakingPRs();
  refreshInterval = setInterval(loadTasks, 10000);
});

async function loadTasks() {
  const res = await fetch(API);
  const tasks = await res.json();

  const active = tasks.filter(t => t.status === 'active');
  const history = tasks.filter(t => t.status !== 'active');

  _taskCache = {};
  tasks.forEach(t => _taskCache[t.id] = t);

  renderTasks('active-tasks', active, true);
  renderTasks('history-tasks', history, false);

  document.getElementById('no-active').classList.toggle('hidden', active.length > 0);
  document.getElementById('no-history').classList.toggle('hidden', history.length > 0);

  // Update history arrow based on collapsed state
  const historyBody = document.getElementById('history-body');
  const arrow = document.getElementById('history-arrow');
  if (arrow) arrow.textContent = historyBody.classList.contains('hidden') ? '▶' : '▼';
}

function renderTasks(containerId, tasks, showDelete) {
  const container = document.getElementById(containerId);
  container.innerHTML = tasks.map(t => `
    <div class="task-group">
      <div class="task-card" onclick="window.open('${escHtml(t.link)}', '_blank')">
        <button class="btn-expand" onclick="event.stopPropagation(); toggleDetail('${t.id}', this)" title="Details">▶</button>
        <div class="task-info">
          <span class="task-type type-${t.type}">
            ${t.type === 'pr_monitor' ? '● PR Monitor' : '⏰ Reminder'}
          </span>
          <div class="task-desc">${escHtml(t.description || t.link)}</div>
          <div class="task-status">${getStatusText(t)}</div>
          ${t.annotation ? `<div class="task-annotation-preview">📝 ${escHtml(t.annotation)}</div>` : ''}
        </div>
        <div class="task-actions">
          <button class="btn-annotate${t.annotation ? ' has-annotation' : ''}" onclick="event.stopPropagation(); openAnnotation('${t.id}')" title="Annotation">📝</button>
          ${showDelete ? `<button class="btn-danger" onclick="event.stopPropagation(); deleteTask('${t.id}')" title="Remove">✕</button>` : `<button class="btn-rerun" onclick="event.stopPropagation(); rerunTask('${t.id}')" title="Rerun">⟳</button>`}
        </div>
      </div>
      <div id="detail-${t.id}" class="task-detail hidden">
        ${getDetailHtml(t)}
      </div>
      <div id="annotation-${t.id}" class="annotation-panel hidden">
        <textarea class="annotation-input" id="annotation-input-${t.id}" placeholder="Add notes about this task...">${escHtml(t.annotation || '')}</textarea>
        <div class="annotation-actions">
          <button class="btn-annotation-save" onclick="saveAnnotation('${t.id}')">Save</button>
          <button class="btn-annotation-cancel" onclick="closeAnnotation('${t.id}')">Cancel</button>
        </div>
      </div>
    </div>
  `).join('');
}

function toggleDetail(id, btn) {
  const el = document.getElementById('detail-' + id);
  if (el) {
    el.classList.toggle('hidden');
    if (btn) btn.textContent = el.classList.contains('hidden') ? '▶' : '▼';
  }
}

async function loadBreakingPRs() {
  const container = document.getElementById('breaking-prs');
  const noBreaking = document.getElementById('no-breaking');
  const refreshBtn = document.querySelector('#breaking-section .btn-clear');

  // Show loading state
  if (refreshBtn) {
    refreshBtn.textContent = '⟳ Loading...';
    refreshBtn.disabled = true;
  }
  noBreaking.textContent = 'Loading...';
  noBreaking.classList.remove('hidden');

  try {
    const res = await fetch('/api/breaking-prs');
    const prs = await res.json();
    if (prs.length === 0) {
      container.innerHTML = '';
      noBreaking.textContent = 'No breaking change PRs found';
      noBreaking.classList.remove('hidden');
      return;
    }
    noBreaking.classList.add('hidden');
    container.innerHTML = prs.map(pr => {
      const prKey = `${pr.repo}#${pr.number}`;
      return `
      <div class="task-group">
        <div class="task-card" onclick="window.open('${escHtml(pr.url)}', '_blank')">
          <div class="task-info">
            <span class="task-type type-breaking">⚠ ${escHtml(pr.repo.split('/')[1])}</span>
            <div class="task-desc">#${pr.number} ${escHtml(pr.title)}</div>
            <div class="task-status">by ${escHtml(pr.author)} · ${pr.created_at ? timeAgo(pr.created_at) : ''}</div>
            ${pr.annotation ? `<div class="task-annotation-preview">📝 ${escHtml(pr.annotation)}</div>` : ''}
          </div>
          <div class="task-actions">
            <button class="btn-annotate${pr.annotation ? ' has-annotation' : ''}" onclick="event.stopPropagation(); openBPRAnnotation('${escHtml(prKey)}')" title="Annotation">📝</button>
          </div>
        </div>
        <div id="annotation-bpr-${escHtml(prKey)}" class="annotation-panel hidden">
          <textarea class="annotation-input" id="annotation-input-bpr-${escHtml(prKey)}" placeholder="Add notes about this PR...">${escHtml(pr.annotation || '')}</textarea>
          <div class="annotation-actions">
            <button class="btn-annotation-save" onclick="saveBPRAnnotation('${escHtml(prKey)}')">Save</button>
            <button class="btn-annotation-cancel" onclick="closeBPRAnnotation('${escHtml(prKey)}')">Cancel</button>
          </div>
        </div>
      </div>`;
    }).join('');
  } catch (e) {
    noBreaking.textContent = 'Failed to load';
    noBreaking.classList.remove('hidden');
  } finally {
    if (refreshBtn) {
      refreshBtn.textContent = '⟳';
      refreshBtn.disabled = false;
    }
  }
}

function getDetailHtml(t) {
  const rows = [];
  rows.push(`<tr><td>Link</td><td><a href="${escHtml(t.link)}" target="_blank" class="task-link">${escHtml(t.link)}</a></td></tr>`);
  rows.push(`<tr><td>Status</td><td>${t.status}</td></tr>`);
  rows.push(`<tr><td>Created</td><td>${formatTime(t.created_at)}</td></tr>`);
  if (t.description) {
    rows.push(`<tr><td>Description</td><td>${escHtml(t.description)}</td></tr>`);
  }
  if (t.type === 'pr_monitor' && t.pr_monitor) {
    const pr = t.pr_monitor;
    rows.push(`<tr><td>Repo</td><td>${escHtml(pr.repo)}</td></tr>`);
    rows.push(`<tr><td>PR #</td><td>${pr.pr_number}</td></tr>`);
    rows.push(`<tr><td>Poll interval</td><td>${pr.poll_interval_minutes} min</td></tr>`);
    rows.push(`<tr><td>Timeout</td><td>${pr.timeout_minutes} min</td></tr>`);
    if (pr.expire_at) rows.push(`<tr><td>Expires at</td><td>${formatTime(pr.expire_at)}</td></tr>`);
    if (pr.last_status) rows.push(`<tr><td>Last CI status</td><td>${pr.last_status}</td></tr>`);
    if (pr.last_checked) rows.push(`<tr><td>Last checked</td><td>${formatTime(pr.last_checked)}</td></tr>`);
  }
  if (t.type === 'reminder' && t.reminder) {
    rows.push(`<tr><td>Delay</td><td>${t.reminder.delay_minutes} min</td></tr>`);
    rows.push(`<tr><td>Fire at</td><td>${formatTime(t.reminder.fire_at)}</td></tr>`);
  }
  if (t.annotation) {
    rows.push(`<tr><td>Annotation</td><td style="white-space:pre-wrap">${escHtml(t.annotation)}</td></tr>`);
  }
  return `<table>${rows.join('')}</table>`;
}

function formatTime(iso) {
  if (!iso) return 'N/A';
  return new Date(iso).toLocaleString();
}

async function deleteTask(id) {
  await fetch(`${API}/${id}`, { method: 'DELETE' });
  loadTasks();
}

async function rerunTask(id) {
  const t = _taskCache[id];
  if (!t) return;
  const body = { type: t.type, link: t.link, description: t.description };
  if (t.type === 'reminder' && t.reminder) {
    body.delay_minutes = t.reminder.delay_minutes;
  }
  if (t.type === 'pr_monitor' && t.pr_monitor) {
    body.timeout_minutes = t.pr_monitor.timeout_minutes;
  }
  await fetch(API, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  loadTasks();
}

async function clearHistory() {
  const btn = document.querySelector('#history-section .btn-clear');
  if (btn) { btn.textContent = 'Clearing...'; btn.disabled = true; }
  await fetch(`${API}/history`, { method: 'DELETE' });
  loadTasks();
  if (btn) { btn.textContent = 'Clear'; btn.disabled = false; }
}

function getStatusText(t) {
  if (t.status === 'triggered') return '✅ Triggered';
  if (t.status === 'dismissed') return '🚫 Dismissed';
  if (t.status === 'error') return '❌ Error';

  if (t.type === 'pr_monitor' && t.pr_monitor) {
    const pr = t.pr_monitor;
    const ci = pr.last_status || 'Waiting...';
    const ago = pr.last_checked ? timeAgo(pr.last_checked) : 'never';
    let timeout = '';
    if (pr.expire_at) {
      const diff = new Date(pr.expire_at) - Date.now();
      timeout = diff > 0 ? ` · timeout in ${Math.ceil(diff / 60000)} min` : ' · timed out';
    }
    return `CI: ${ci} (checked ${ago})${timeout}`;
  }
  if (t.type === 'reminder' && t.reminder) {
    const fire = new Date(t.reminder.fire_at);
    const diff = fire - Date.now();
    if (diff <= 0) return 'Firing...';
    return `Fires in ${Math.ceil(diff / 60000)} min`;
  }
  return t.status;
}

function timeAgo(iso) {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  return `${Math.floor(mins / 60)}h ago`;
}

function escHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function truncate(s, n) {
  return s.length > n ? s.slice(0, n) + '...' : s;
}

function openAnnotation(id) {
  const panel = document.getElementById('annotation-' + id);
  if (panel) {
    panel.classList.toggle('hidden');
    if (!panel.classList.contains('hidden')) {
      const input = document.getElementById('annotation-input-' + id);
      if (input) { input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
    }
  }
}

function closeAnnotation(id) {
  const panel = document.getElementById('annotation-' + id);
  if (panel) panel.classList.add('hidden');
  const t = _taskCache[id];
  if (t) {
    const input = document.getElementById('annotation-input-' + id);
    if (input) input.value = t.annotation || '';
  }
}

async function saveAnnotation(id) {
  const input = document.getElementById('annotation-input-' + id);
  if (!input) return;
  const annotation = input.value.trim();
  await fetch(`${API}/${id}/annotation`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ annotation }),
  });
  loadTasks();
}

function openBPRAnnotation(key) {
  const panel = document.getElementById('annotation-bpr-' + key);
  if (panel) {
    panel.classList.toggle('hidden');
    if (!panel.classList.contains('hidden')) {
      const input = document.getElementById('annotation-input-bpr-' + key);
      if (input) { input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
    }
  }
}

function closeBPRAnnotation(key) {
  const panel = document.getElementById('annotation-bpr-' + key);
  if (panel) panel.classList.add('hidden');
}

async function saveBPRAnnotation(key) {
  const input = document.getElementById('annotation-input-bpr-' + key);
  if (!input) return;
  const annotation = input.value.trim();
  const [repo, number] = key.split('#');
  await fetch(`/api/breaking-prs/${repo}/${number}/annotation`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ annotation }),
  });
  loadBreakingPRs();
}
