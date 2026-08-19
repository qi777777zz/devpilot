const taskForm = document.querySelector("#task-form");
const runList = document.querySelector("#run-list");
const template = document.querySelector("#run-template");
const formMessage = document.querySelector("#form-message");
const refreshButton = document.querySelector("#refresh");
let refreshTimer;

function formatTime(value) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit"
  }).format(new Date(value));
}

function stepLabel(event) {
  return (event.step || event.kind).replaceAll("_", " ").replaceAll(".", " ");
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail || `Request failed with ${response.status}`);
  }
  return response.json();
}

async function expandRun(card, taskId) {
  const detail = card.querySelector(".run-detail");
  const summary = card.querySelector(".run-summary");
  if (!detail.hidden) {
    detail.hidden = true;
    summary.setAttribute("aria-expanded", "false");
    card.querySelector(".disclosure").textContent = "＋";
    return;
  }
  const task = await request(`/api/v1/tasks/${taskId}`);
  detail.querySelector(".requirement").textContent = task.requirement;
  const trace = detail.querySelector(".trace");
  trace.replaceChildren(...task.events.map((event) => {
    const row = document.createElement("div");
    row.className = "trace-event";
    row.innerHTML = `
      <span class="trace-dot" aria-hidden="true"></span>
      <span class="trace-step"></span>
      <p class="trace-message"></p>`;
    row.querySelector(".trace-step").textContent = stepLabel(event);
    row.querySelector(".trace-message").textContent = event.message;
    return row;
  }));
  const artifacts = detail.querySelector(".artifact-grid");
  const jobCards = task.jobs.map((job) => {
    const item = document.createElement("div");
    item.className = "artifact";
    const title = document.createElement("strong");
    title.textContent = `Queue · ${job.state}`;
    const kind = document.createElement("span");
    kind.textContent = `attempt ${job.attempts}/${job.max_attempts}`;
    item.append(title, kind);
    return item;
  });
  const artifactCards = task.artifacts.map((artifact) => {
    const item = document.createElement("div");
    item.className = "artifact";
    const title = document.createElement("strong");
    title.textContent = artifact.name;
    const kind = document.createElement("span");
    kind.textContent = artifact.kind.replaceAll("_", " ");
    item.append(title, kind);
    return item;
  });
  artifacts.replaceChildren(...jobCards, ...artifactCards);
  detail.hidden = false;
  summary.setAttribute("aria-expanded", "true");
  card.querySelector(".disclosure").textContent = "−";
}

function renderTasks(tasks) {
  runList.replaceChildren(...tasks.map((task) => {
    const fragment = template.content.cloneNode(true);
    const card = fragment.querySelector(".run-card");
    card.dataset.status = task.status;
    card.querySelector(".run-title").textContent = task.title;
    const step = task.current_step ? ` · ${task.current_step.replaceAll("_", " ")}` : "";
    card.querySelector(".run-meta").textContent = `${formatTime(task.created_at)}${step}`;
    card.querySelector(".status-chip").textContent = task.status;
    card.querySelector(".run-summary").addEventListener("click", () => expandRun(card, task.id));
    return fragment;
  }));
  const hasActiveTask = tasks.some((task) =>
    ["pending", "queued", "running", "retrying"].includes(task.status)
  );
  clearTimeout(refreshTimer);
  if (hasActiveTask) refreshTimer = setTimeout(loadTasks, 1200);
}

async function loadTasks() {
  try {
    renderTasks(await request("/api/v1/tasks"));
  } catch (error) {
    runList.textContent = `Tasks could not be loaded: ${error.message}`;
  }
}

taskForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = taskForm.querySelector("button[type=submit]");
  button.disabled = true;
  formMessage.textContent = "Creating the run…";
  const body = {
    title: taskForm.elements.title.value,
    requirement: taskForm.elements.requirement.value,
    repository_path: taskForm.elements.repository_path.value,
  };
  try {
    const task = await request("/api/v1/tasks", { method: "POST", body: JSON.stringify(body) });
    await request(`/api/v1/tasks/${task.id}/run`, { method: "POST" });
    formMessage.textContent = "Run scheduled. Its trace will appear on the right.";
    await loadTasks();
  } catch (error) {
    formMessage.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

refreshButton.addEventListener("click", loadTasks);
loadTasks();
