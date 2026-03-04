const API = '/api/tasks';
let refreshInterval;

document.addEventListener('DOMContentLoaded', () => {
  const modal = document.getElementById('modal');
  const btnAdd = document.getElementById('btn-add');
  const btnCancel = document.getElementById('btn-cancel');
  const form = document.getElementById('task-form');
  const typeSelect = document.getElementById('task-type');
  const delayGroup = document.getElementById('delay-group');

  btnAdd.onclick = () => modal.classList.remove('hidden');
  btnCancel.onclick = () => modal.classList.add('hidden');

  typeSelect.onchange = () => {
    delayGroup.classList.toggle('hidden', typeSelect.value !== 'reminder');
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
}

function renderTasks(containerId, tasks, showDelete) {
  const container = document.getElementById(containerId);
  container.innerHTML = tasks.map(t => `
    <div class="task-card">
      <div class="task-info">
        <span class="task-type type-${t.type}">
          ${t.type === 'pr_monitor' ? '● PR Monitor' : '⏰ Reminder'}
        </span>
        <div class="task-desc">${escHtml(t.description || t.link)}</div>
        <div class="task-status">${getStatusText(t)}</div>
        <a class="task-link" href="${escHtml(t.link)}" target="_blank">${truncate(t.link, 60)}</a>
      </div>
      ${showDelete ? `<button class="btn-danger" onclick="deleteTask('${t.id}')" title="Remove">✕</button>` : ''}
    </div>
  `).join('');
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
    return `CI: ${ci} (checked ${ago})`;
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
