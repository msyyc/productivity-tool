const API = '/api/tasks';
let refreshInterval;

document.addEventListener('DOMContentLoaded', () => {
  const modal = document.getElementById('modal');
  const modalTitle = modal.querySelector('h2');
  const btnAddPr = document.getElementById('btn-add-pr');
  const btnAddReminder = document.getElementById('btn-add-reminder');
  const btnCancel = document.getElementById('btn-cancel');
  const form = document.getElementById('task-form');
  const typeSelect = document.getElementById('task-type');
  const delayGroup = document.getElementById('delay-group');
  const timeoutGroup = document.getElementById('timeout-group');
  const linkInput = document.getElementById('task-link');

  function openModal(type) {
    typeSelect.value = type;
    typeSelect.dispatchEvent(new Event('change'));
    if (type === 'pr_monitor') {
      modalTitle.textContent = '● Add PR Monitor';
      linkInput.placeholder = 'https://github.com/owner/repo/pull/123';
    } else {
      modalTitle.textContent = '⏰ Add Reminder';
      linkInput.placeholder = 'https://teams.microsoft.com/...';
    }
    modal.classList.remove('hidden');
  }

  btnAddPr.onclick = () => openModal('pr_monitor');
  btnAddReminder.onclick = () => openModal('reminder');
  btnCancel.onclick = () => modal.classList.add('hidden');

  typeSelect.onchange = () => {
    delayGroup.classList.toggle('hidden', typeSelect.value !== 'reminder');
    timeoutGroup.classList.toggle('hidden', typeSelect.value !== 'pr_monitor');
  };
  typeSelect.dispatchEvent(new Event('change'));

  form.onsubmit = async (e) => {
    e.preventDefault();
    const body = {
      type: typeSelect.value,
      link: document.getElementById('task-link').value,
      description: document.getElementById('task-desc').value,
    };
    if (typeSelect.value === 'reminder') {
      body.delay_minutes = parseInt(document.getElementById('task-delay').value);
    }
    if (typeSelect.value === 'pr_monitor') {
      body.timeout_minutes = parseInt(document.getElementById('task-timeout').value);
    }
    await fetch(API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    form.reset();
    typeSelect.dispatchEvent(new Event('change'));
    modal.classList.add('hidden');
    loadTasks();
  };

  loadTasks();
  refreshInterval = setInterval(loadTasks, 10000);
});

async function loadTasks() {
  const res = await fetch(API);
  const tasks = await res.json();

  const active = tasks.filter(t => t.status === 'active');
  const history = tasks.filter(t => t.status !== 'active');

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
      <div class="task-card" onclick="toggleDetail('${t.id}')">
        <div class="task-info">
          <span class="task-type type-${t.type}">
            ${t.type === 'pr_monitor' ? '● PR Monitor' : '⏰ Reminder'}
          </span>
          <div class="task-desc">${escHtml(t.description || t.link)}</div>
          <div class="task-status">${getStatusText(t)}</div>
        </div>
        ${showDelete ? `<button class="btn-danger" onclick="event.stopPropagation(); deleteTask('${t.id}')" title="Remove">✕</button>` : ''}
      </div>
      <div id="detail-${t.id}" class="task-detail hidden">
        ${getDetailHtml(t)}
      </div>
    </div>
  `).join('');
}

function toggleDetail(id) {
  const el = document.getElementById('detail-' + id);
  if (el) el.classList.toggle('hidden');
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
