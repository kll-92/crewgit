const COLUMNS = [
  ["todo", "Todo"],
  ["blocked", "Blocked"],
  ["running", "Running"],
  ["review", "Review"],
  ["done", "Done"],
];

const GATE_CLASS = { pass: "pass", fail: "fail", skip: "skip", error: "error" };
const AGENT_COLORS = ["#c6ff3d", "#57c7ff", "#c792ea", "#ffc857", "#3ddc97", "#ff8fab"];

const state = { board: null, readOnly: false, busy: false, loaded: false };

const $ = (sel) => document.querySelector(sel);

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function teamCost(totals) {
  if (!totals) return "$0";
  if (totals.runs && totals.unmetered_runs >= totals.runs) return "unmetered";
  return money(totals.cost_usd);
}

function money(value) {
  if (value === null || value === undefined) return "unmetered";
  const number = Number(value);
  if (!Number.isFinite(number) || number === 0) return "$0";
  return "$" + number.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}

function initials(name) {
  const clean = String(name || "?").replace(/[^a-zA-Z0-9]/g, "");
  return (clean.slice(0, 2) || "?").toUpperCase();
}

function colorFor(name) {
  let hash = 0;
  for (const ch of String(name)) hash = (hash * 31 + ch.charCodeAt(0)) % 997;
  return AGENT_COLORS[hash % AGENT_COLORS.length];
}

function gateChips(gates) {
  if (!gates || !gates.length) return '<span class="chip skip">no gates</span>';
  return gates
    .map((gate) => `<span class="chip ${GATE_CLASS[gate.status] || ""}" title="${esc(gate.detail || "")}">${esc(gate.name)} ${esc(gate.status)}</span>`)
    .join("");
}

function card(item) {
  const latest = item.latest_run;
  const canRun = !state.readOnly && ["todo", "blocked"].includes(item.status)
    && !(item.status_reason || "").startsWith("waiting on dependencies")
    && !(latest && latest.status === "running");
  const canMerge = !state.readOnly && latest && latest.status === "passed";
  const canDiff = latest && latest.commit;
  const running = latest && latest.status === "running";

  const diff = latest
    ? `${latest.diff_stat?.files || 0}f <span class="plus">+${latest.diff_stat?.insertions || 0}</span>/<span class="minus">-${latest.diff_stat?.deletions || 0}</span>`
    : "—";
  const reason = item.status_reason && item.status !== "done" ? `<div class="reason">${esc(item.status_reason)}</div>` : "";

  return `<article class="card ${item.status}" data-task="${esc(item.id)}">
    <div class="card-top">
      <span class="tid">${esc(item.id)}</span>
      <span class="agent"><span class="avatar" style="background:${colorFor(item.agent)}">${esc(initials(item.agent || "coder"))}</span>${esc(item.agent || "coder")}</span>
    </div>
    <h3>${esc(item.title)}</h3>
    <div class="gates">${gateChips(latest && latest.gates)}</div>
    ${reason}
    <div class="meta">
      <span>${diff}</span>
      <span class="cost">${money(latest && latest.cost_usd)}</span>
      ${latest ? `<span>${esc(latest.run_id)}</span>` : ""}
    </div>
    <div class="card-actions">
      <button class="accent" data-action="run" ${canRun ? "" : "hidden"}>Run</button>
      <button data-action="merge" ${canMerge ? "" : "hidden"}>Merge</button>
      <button data-action="diff" ${canDiff ? "" : "hidden"}>Diff</button>
    </div>
  </article>`;
}

function render(board) {
  $("#project").textContent = board.project;
  $("#branch").textContent = board.branch;
  $("#stat-done").textContent = board.counts.done;
  $("#stat-runs").textContent = board.totals.runs;
  $("#stat-cost").textContent = teamCost(board.totals);

  const byColumn = Object.fromEntries(COLUMNS.map(([key]) => [key, []]));
  for (const item of board.tasks) {
    (byColumn[item.status] || byColumn.todo).push(item);
  }

  const boardEl = $("#board");
  const previous = boardEl.scrollLeft;
  boardEl.innerHTML = COLUMNS.map(([key, label]) => {
    const items = byColumn[key] || [];
    const body = items.length
      ? items.map(card).join("")
      : '<div class="empty">nothing here</div>';
    return `<section class="column">
      <div class="column-head">
        <span class="dot dot-${key}"></span>
        <h2>${label}</h2>
        <span class="count">${items.length}</span>
      </div>
      ${body}
    </section>`;
  }).join("");
  boardEl.scrollLeft = previous;
}

async function fetchJSON(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || data.error?.message || response.statusText);
  return data;
}

async function load() {
  try {
    if (!state.loaded) {
      const health = await fetchJSON("/api/health");
      state.readOnly = !!health.read_only;
      $("#mode").textContent = state.readOnly ? "read-only" : "live";
      $("#mode").classList.toggle("readonly", state.readOnly);
      state.loaded = true;
    }
    const board = await fetchJSON("/api/board");
    state.board = board;
    render(board);
  } catch (error) {
    toast(error.message, true);
  }
}

function toast(message, isError) {
  const el = $("#toast");
  el.textContent = message;
  el.className = "toast" + (isError ? " error" : "");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.add("hidden"), 4200);
}

async function act(taskId, action, runId) {
  if (state.busy) return;
  state.busy = true;
  try {
    if (action === "run") {
      toast(`starting ${taskId}…`);
      await fetchJSON(`/api/tasks/${encodeURIComponent(taskId)}/run`, {
        method: "POST", headers: { "content-type": "application/json" }, body: "{}",
      });
      toast(`${taskId} finished`);
    }
    if (action === "merge") {
      await fetchJSON(`/api/runs/${encodeURIComponent(runId)}/merge`, {
        method: "POST", headers: { "content-type": "application/json" }, body: "{}",
      });
      toast(`merged ${runId}`);
    }
    await load();
  } catch (error) {
    toast(error.message, true);
  } finally {
    state.busy = false;
  }
}

async function showDiff(runId) {
  try {
    const response = await fetch(`/api/runs/${encodeURIComponent(runId)}/diff`);
    const text = await response.text();
    if (!response.ok) throw new Error(text || "no diff");
    $("#modal-title").textContent = runId + " · diff";
    $("#modal-body").textContent = text || "(empty diff)";
    $("#modal").classList.remove("hidden");
  } catch (error) {
    toast(error.message, true);
  }
}

$("#board").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const cardEl = button.closest(".card");
  const taskId = cardEl?.dataset.task;
  const item = state.board?.tasks.find((entry) => entry.id === taskId);
  const latest = item?.latest_run;
  const action = button.dataset.action;
  if (action === "diff") return showDiff(latest.run_id);
  act(taskId, action, latest?.run_id);
});

$("#refresh").addEventListener("click", load);
$("#modal-close").addEventListener("click", () => $("#modal").classList.add("hidden"));
$("#modal").addEventListener("click", (event) => {
  if (event.target === $("#modal")) $("#modal").classList.add("hidden");
});
document.addEventListener("keydown", (event) => {
  if (event.key === "r" || event.key === "R") load();
  if (event.key === "Escape") $("#modal").classList.add("hidden");
});

load();
setInterval(() => {
  if (!document.hidden) load();
}, 3000);
