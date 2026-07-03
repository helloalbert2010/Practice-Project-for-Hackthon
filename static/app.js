const form = document.querySelector("#event-form");
const result = document.querySelector("#submission-result");
const occurredAtInput = form.elements.occurred_at;

const urgencyLabels = {
  low: "低",
  medium: "中",
  high: "高",
  critical: "危急",
};

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

function toLocalDatetimeValue(date) {
  const offset = date.getTimezoneOffset();
  const localDate = new Date(date.getTime() - offset * 60 * 1000);
  return localDate.toISOString().slice(0, 16);
}

function setDefaultTime() {
  occurredAtInput.value = toLocalDatetimeValue(new Date());
}

function getFormPayload() {
  const formData = new FormData(form);
  return Object.fromEntries(formData.entries());
}

function showError(message) {
  result.className = "error";
  result.textContent = message;
}

function renderResult(payload) {
  const event = payload.event;
  const urgency = urgencyLabels[event.urgency] || event.urgency;
  result.className = "result-card";
  result.innerHTML = `
    <div class="result-line"><strong>事件编号</strong><span>#${escapeHtml(event.id)}</span></div>
    <div class="result-line"><strong>系统分类</strong><span>${escapeHtml(event.ai_type)}</span></div>
    <div class="result-line"><strong>紧急度</strong><span>${escapeHtml(urgency)}</span></div>
    <div class="result-line"><strong>评估来源</strong><span>${escapeHtml(event.assessment_source)}</span></div>
    <p>${escapeHtml(event.assessment_reason)}</p>
    <div class="suggestion-block">
      <strong>处理建议</strong>
      <p>${escapeHtml(event.handling_suggestion)}</p>
    </div>
  `;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submitButton = form.querySelector("button[type='submit']");
  submitButton.disabled = true;
  submitButton.textContent = "提交中";

  try {
    const response = await fetch("/api/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(getFormPayload()),
    });
    const payload = await response.json();

    if (!response.ok) {
      const message = payload.errors ? payload.errors.join(" ") : payload.error;
      throw new Error(message || "提交失败。");
    }

    renderResult(payload);
    form.reset();
    setDefaultTime();
  } catch (error) {
    showError(error.message);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "提交事件";
  }
});

form.addEventListener("reset", () => {
  window.setTimeout(setDefaultTime, 0);
});

setDefaultTime();
