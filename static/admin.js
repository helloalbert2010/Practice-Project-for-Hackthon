const eventsBody = document.querySelector("#events-body");
const sortSelect = document.querySelector("#sort-select");
const refreshButton = document.querySelector("#refresh-button");
const summaryGrid = document.querySelector("#summary-grid");

const urgencyLabels = {
  low: "低",
  medium: "中",
  high: "高",
  critical: "危急",
};

const statusLabels = {
  pending: "待确认",
  confirmed: "已确认",
};

let events = [];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => {
    const entities = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return entities[character];
  });
}

function formatDate(value) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value.replace("T", " ");
  return parsed.toLocaleString("zh-CN", { hour12: false });
}

function renderBadge(text, className = "badge-neutral") {
  return `<span class="badge ${className}">${escapeHtml(text)}</span>`;
}

function urgencyBadge(event) {
  return renderBadge(urgencyLabels[event.urgency] || event.urgency, `badge-${event.urgency}`);
}

function renderSummary() {
  const pending = events.filter((event) => event.status === "pending").length;
  const confirmed = events.filter((event) => event.status === "confirmed").length;
  const critical = events.filter((event) => event.urgency === "critical").length;
  const high = events.filter((event) => event.urgency === "high").length;

  const items = [
    ["待确认", pending],
    ["已确认", confirmed],
    ["危急", critical],
    ["高紧急度", high],
  ];

  summaryGrid.innerHTML = items
    .map(
      ([label, value]) => `
      <div class="summary-item">
        <span>${label}</span>
        <strong>${value}</strong>
      </div>
    `,
    )
    .join("");
}

function renderEvents() {
  renderSummary();

  if (events.length === 0) {
    eventsBody.innerHTML = `
      <tr>
        <td colspan="7">暂无事件。</td>
      </tr>
    `;
    return;
  }

  eventsBody.innerHTML = events
    .map((event) => {
      const action =
        event.status === "pending"
          ? `<button class="secondary-button confirm-button" data-id="${event.id}" type="button">确认</button>`
          : renderBadge("完成");

      return `
        <tr>
          <td>#${escapeHtml(event.id)}</td>
          <td>${renderBadge(event.ai_type)}</td>
          <td>${urgencyBadge(event)}</td>
          <td>${escapeHtml(event.location)}</td>
          <td>${escapeHtml(formatDate(event.occurred_at))}</td>
          <td class="status-${event.status}">${escapeHtml(statusLabels[event.status] || event.status)}</td>
          <td>${action}</td>
        </tr>
        <tr class="description-row">
          <td></td>
          <td colspan="6">
            <strong>描述：</strong>${escapeHtml(event.description)}
            <br />
            <strong>评估：</strong>${escapeHtml(event.assessment_reason)}
          </td>
        </tr>
      `;
    })
    .join("");
}

async function loadEvents() {
  refreshButton.disabled = true;
  try {
    const response = await fetch(`/api/events?sort=${encodeURIComponent(sortSelect.value)}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "加载事件失败。");
    }
    events = payload.events;
    renderEvents();
  } catch (error) {
    eventsBody.innerHTML = `
      <tr>
        <td colspan="7"><div class="error">${error.message}</div></td>
      </tr>
    `;
  } finally {
    refreshButton.disabled = false;
  }
}

async function confirmEvent(eventId, button) {
  button.disabled = true;
  button.textContent = "确认中";
  try {
    const response = await fetch(`/api/events/${eventId}/confirm`, { method: "POST" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "确认失败。");
    }
    await loadEvents();
  } catch (error) {
    window.alert(error.message);
    button.disabled = false;
    button.textContent = "确认";
  }
}

eventsBody.addEventListener("click", (event) => {
  const button = event.target.closest(".confirm-button");
  if (!button) return;
  confirmEvent(button.dataset.id, button);
});

sortSelect.addEventListener("change", loadEvents);
refreshButton.addEventListener("click", loadEvents);

loadEvents();
