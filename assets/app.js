const stateList = ["Active", "On Hold", "Complete", "Staged", "Reference"];

const dashboard = {
  data: null,
  aiBudget: null,
  query: "",
  visibleStates: new Set(stateList),
  sortKey: "lastActive",
  sortDirection: "desc",
  selectedId: "",
  calendarDate: "",
  selectedCalendarDate: "",
};

const sortLabels = {
  asc: "Forward",
  desc: "Reverse",
};

function text(id, value) {
  const element = document.getElementById(id);
  if (element) element.textContent = value || "";
}

function formatDate(value) {
  if (!value) return "Unknown";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function formatDayLabel(value) {
  if (!value) return "Unknown";

  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return "Unknown";

  return new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    month: "short",
    day: "numeric",
  }).format(date);
}

function dateKey(value) {
  if (!value) return "";
  const raw = String(value);
  const match = raw.match(/^(\d{4}-\d{2}-\d{2})/);
  if (match) return match[1];

  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString().slice(0, 10);
}

function monthKeyFromDate(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function dateFromMonthKey(monthKey) {
  const [year, month] = String(monthKey || "").split("-").map(Number);
  const date = new Date(year || new Date().getFullYear(), (month || new Date().getMonth() + 1) - 1, 1);
  return Number.isNaN(date.getTime()) ? new Date() : date;
}

function formatDuration(minutes) {
  const value = Number(minutes) || 0;
  if (value < 60) return `${value}m`;

  const hours = Math.floor(value / 60);
  const remaining = value % 60;
  return remaining ? `${hours}h ${remaining}m` : `${hours}h`;
}

function formatMoney(value) {
  const amount = Number(value) || 0;
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: amount < 1 ? 6 : 2,
    maximumFractionDigits: amount < 1 ? 6 : 2,
  }).format(amount);
}

function colorClass(state, prefix) {
  return `${prefix}-${state.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
}

function searchText(project) {
  const aiContext = project.ai_context || {};
  const timeTracking = project.time_tracking || {};
  const aiSpend = project.ai_spend || {};
  const sessions = timeTracking.sessions || [];
  const spendSessions = aiSpend.sessions || [];

  return [
    project.name,
    project.state,
    project.summary,
    project.path,
    project.resume_file,
    aiContext.last_machine,
    aiContext.conversation_name,
    timeTracking.notes,
    String(timeTracking.approx_minutes_total || ""),
    aiSpend.notes,
    String(aiSpend.estimated_usd_total || ""),
    ...sessions.flatMap((session) => [
      session.date,
      session.machine,
      session.conversation_name,
      session.summary,
      String(session.approx_minutes || ""),
    ]),
    ...spendSessions.flatMap((session) => [
      session.date,
      session.machine,
      session.conversation_name,
      session.model,
      session.summary,
      String(session.estimated_usd || ""),
    ]),
    ...(project.next_actions || []),
    ...(project.blockers || []),
    ...(project.tags || []),
  ]
    .join(" ")
    .toLowerCase();
}

function dashboardProjects() {
  return dashboard.data.projects.filter((project) => !project.hidden);
}

function dateValue(project, fields) {
  const value = fields.map((field) => project[field]).find(Boolean);
  if (!value) return 0;

  const timestamp = new Date(value).getTime();
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function sortValue(project) {
  if (dashboard.sortKey === "alpha") {
    return project.name.toLocaleLowerCase();
  }

  if (dashboard.sortKey === "startDate") {
    return dateValue(project, ["started_at", "start_date", "created_at", "updated_at"]);
  }

  return dateValue(project, ["last_active_at", "last_active", "updated_at"]);
}

function sortedProjects(projects) {
  const direction = dashboard.sortDirection === "asc" ? 1 : -1;

  return [...projects].sort((a, b) => {
    const aValue = sortValue(a);
    const bValue = sortValue(b);
    let comparison = 0;

    if (typeof aValue === "string" && typeof bValue === "string") {
      comparison = aValue.localeCompare(bValue);
    } else {
      comparison = aValue - bValue;
    }

    if (comparison === 0) {
      comparison = a.name.localeCompare(b.name);
    }

    return comparison * direction;
  });
}

function visibleProjects() {
  const query = dashboard.query.trim().toLowerCase();
  const projects = dashboardProjects().filter((project) => {
    const stateMatches = !stateList.includes(project.state) || dashboard.visibleStates.has(project.state);
    const queryMatches = !query || searchText(project).includes(query);
    return stateMatches && queryMatches;
  });

  return sortedProjects(projects);
}

function workSessions(projects = dashboardProjects()) {
  return projects
    .flatMap((project) =>
      ((project.time_tracking || {}).sessions || []).map((session) => ({
        date: dateKey(session.date),
        projectId: project.id,
        projectName: project.name,
        state: project.state,
        minutes: Number(session.approx_minutes) || 0,
        summary: session.summary || "",
        conversation: session.conversation_name || "",
        machine: session.machine || "",
      }))
    )
    .filter((session) => session.date)
    .sort((a, b) => b.date.localeCompare(a.date) || a.projectName.localeCompare(b.projectName));
}

function latestSessionDate(sessions) {
  return sessions[0]?.date || new Date().toISOString().slice(0, 10);
}

function renderOverview() {
  const projects = dashboardProjects();
  text("projectCount", projects.length.toLocaleString());
  text("activeCount", projects.filter((project) => project.state === "Active").length.toLocaleString());
  text("updatedAt", formatDate(dashboard.data.generated_at));
  text("dashboardStatus", `Tracking ${projects.length} projects from ${dashboard.data.source_root}`);
  renderBudget();
}

function localAiSpendTotal() {
  return dashboardProjects().reduce((total, project) => {
    const spend = project.ai_spend || {};
    return total + (Number(spend.estimated_usd_total) || 0);
  }, 0);
}

function renderBudget() {
  const budget = dashboard.aiBudget;
  const total = budget ? budget.total_usd : localAiSpendTotal();
  const budgetText = budget ? `of ${formatMoney(budget.budget_usd)} cap` : "tracked locally";
  const dailyText = budget ? `${formatMoney(budget.daily_total_usd || 0)} today` : "";
  const guardText = budget ? `max ${formatMoney(budget.per_run_max_usd || 0)} per sync` : "";
  const apiText = budget
    ? budget.api_enabled && budget.sync_enabled
      ? `${budget.model} ready`
      : "sync disabled"
    : "server budget offline";

  text("aiSpendTotal", formatMoney(total));
  text("aiBudgetStatus", [budgetText, dailyText, guardText, apiText].filter(Boolean).join(" · "));
}

function renderBars() {
  const rows = document.getElementById("stateBars");
  const projects = dashboardProjects();
  const total = projects.length || 1;
  rows.innerHTML = "";

  stateList.forEach((state) => {
    const count = projects.filter((project) => project.state === state).length;
    const row = document.createElement("div");
    row.className = "state-bar";
    row.innerHTML = `
      <span>${state}</span>
      <span class="bar-track"><span class="bar-fill ${colorClass(state, "fill")}" style="width: ${(count / total) * 100}%"></span></span>
      <strong>${count}</strong>
    `;
    rows.appendChild(row);
  });
}

function renderFilters() {
  const filters = document.getElementById("filters");
  filters.innerHTML = "";

  const allButton = document.createElement("button");
  allButton.type = "button";
  allButton.className = dashboard.visibleStates.size === stateList.length ? "is-active" : "";
  allButton.textContent = "All";
  allButton.setAttribute("aria-pressed", String(dashboard.visibleStates.size === stateList.length));
  allButton.addEventListener("click", () => {
    dashboard.visibleStates = new Set(stateList);
    renderProjects();
    renderCalendar();
    renderFilters();
  });
  filters.appendChild(allButton);

  stateList.forEach((filter) => {
    const isVisible = dashboard.visibleStates.has(filter);
    const button = document.createElement("button");
    button.type = "button";
    button.className = isVisible ? "is-active" : "is-hidden-state";
    button.textContent = filter;
    button.setAttribute("aria-pressed", String(isVisible));
    button.addEventListener("click", () => {
      if (dashboard.visibleStates.has(filter)) {
        dashboard.visibleStates.delete(filter);
      } else {
        dashboard.visibleStates.add(filter);
      }
      renderProjects();
      renderCalendar();
      renderFilters();
    });
    filters.appendChild(button);
  });
}

function renderSortControls() {
  const sortKey = document.getElementById("sortKey");
  const sortDirection = document.getElementById("sortDirection");

  sortKey.value = dashboard.sortKey;
  sortDirection.textContent = sortLabels[dashboard.sortDirection];
  sortDirection.setAttribute(
    "aria-label",
    dashboard.sortDirection === "asc" ? "Sort in reverse order" : "Sort in forward order"
  );
  sortDirection.classList.toggle("is-forward", dashboard.sortDirection === "asc");
}

function selectProject(projectId, scrollSelector = ".focus-panel") {
  dashboard.selectedId = projectId;
  renderProjects();
  const target = document.querySelector(scrollSelector);
  if (target) target.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderCalendar() {
  const grid = document.getElementById("calendarGrid");
  const details = document.getElementById("calendarDayDetails");
  if (!grid || !details) return;

  const sessions = workSessions(visibleProjects());
  if (!dashboard.calendarDate) {
    dashboard.calendarDate = latestSessionDate(sessions).slice(0, 7);
  }

  const monthDate = dateFromMonthKey(dashboard.calendarDate);
  const monthKey = monthKeyFromDate(monthDate);
  dashboard.calendarDate = monthKey;

  const monthSessions = sessions.filter((session) => session.date.startsWith(monthKey));
  const monthMinutes = monthSessions.reduce((total, session) => total + session.minutes, 0);
  if (!dashboard.selectedCalendarDate || !dashboard.selectedCalendarDate.startsWith(monthKey)) {
    dashboard.selectedCalendarDate = monthSessions[0]?.date || `${monthKey}-01`;
  }

  text(
    "calendarMonthLabel",
    new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" }).format(monthDate)
  );
  text(
    "calendarSummary",
    monthSessions.length
      ? `${monthSessions.length.toLocaleString()} sessions · ${formatDuration(monthMinutes)} tracked this month`
      : "No tracked sessions in the visible project set this month."
  );

  const sessionsByDate = new Map();
  monthSessions.forEach((session) => {
    const items = sessionsByDate.get(session.date) || [];
    items.push(session);
    sessionsByDate.set(session.date, items);
  });

  grid.innerHTML = "";
  ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].forEach((day) => {
    const label = document.createElement("span");
    label.className = "calendar-weekday";
    label.textContent = day;
    grid.appendChild(label);
  });

  for (let index = 0; index < monthDate.getDay(); index += 1) {
    const spacer = document.createElement("span");
    spacer.className = "calendar-empty";
    grid.appendChild(spacer);
  }

  const todayKey = new Date().toISOString().slice(0, 10);
  const daysInMonth = new Date(monthDate.getFullYear(), monthDate.getMonth() + 1, 0).getDate();
  for (let day = 1; day <= daysInMonth; day += 1) {
    const key = `${monthKey}-${String(day).padStart(2, "0")}`;
    const daySessions = sessionsByDate.get(key) || [];
    const dayMinutes = daySessions.reduce((total, session) => total + session.minutes, 0);
    const button = document.createElement("button");
    button.type = "button";
    button.className = [
      "calendar-day",
      daySessions.length ? "has-work" : "",
      key === dashboard.selectedCalendarDate ? "is-selected" : "",
      key === todayKey ? "is-today" : "",
    ]
      .filter(Boolean)
      .join(" ");
    button.setAttribute("aria-label", `${formatDayLabel(key)} ${formatDuration(dayMinutes)} tracked`);

    const number = document.createElement("strong");
    number.textContent = String(day);
    button.appendChild(number);

    const count = document.createElement("span");
    count.textContent = daySessions.length ? formatDuration(dayMinutes) : "";
    button.appendChild(count);

    button.addEventListener("click", () => {
      dashboard.selectedCalendarDate = key;
      renderCalendar();
    });
    grid.appendChild(button);
  }

  renderCalendarDetails(sessionsByDate.get(dashboard.selectedCalendarDate) || []);
}

function renderCalendarDetails(daySessions) {
  const details = document.getElementById("calendarDayDetails");
  if (!details) return;
  details.innerHTML = "";

  const heading = document.createElement("h3");
  heading.textContent = formatDayLabel(dashboard.selectedCalendarDate);
  details.appendChild(heading);

  if (daySessions.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No tracked project sessions for this day.";
    details.appendChild(empty);
    return;
  }

  daySessions
    .slice()
    .sort((a, b) => b.minutes - a.minutes || a.projectName.localeCompare(b.projectName))
    .forEach((session) => {
      const row = document.createElement("article");
      row.className = "calendar-session";

      const projectButton = document.createElement("button");
      projectButton.type = "button";
      projectButton.textContent = session.projectName;
      projectButton.addEventListener("click", () => selectProject(session.projectId));
      row.appendChild(projectButton);

      const meta = document.createElement("p");
      meta.textContent = [
        formatDuration(session.minutes),
        session.machine,
        session.conversation,
      ]
        .filter(Boolean)
        .join(" · ");
      row.appendChild(meta);

      if (session.summary) {
        const summary = document.createElement("p");
        summary.textContent = session.summary;
        row.appendChild(summary);
      }

      details.appendChild(row);
    });
}

function moveCalendarMonth(offset) {
  const date = dateFromMonthKey(dashboard.calendarDate);
  date.setMonth(date.getMonth() + offset);
  dashboard.calendarDate = monthKeyFromDate(date);
  dashboard.selectedCalendarDate = "";
  renderCalendar();
}

function listItems(id, items, tag) {
  const list = document.getElementById(id);
  list.innerHTML = "";

  if (!items || items.length === 0) {
    const item = document.createElement(tag);
    item.textContent = "None recorded.";
    list.appendChild(item);
    return;
  }

  items.forEach((value) => {
    const item = document.createElement(tag);
    item.textContent = value;
    list.appendChild(item);
  });
}

function renderFocus(project) {
  if (!project) return;

  const blockers = project.blockers || [];
  const panel = document.querySelector(".focus-panel");
  const state = document.getElementById("focusState");

  if (panel) {
    panel.classList.toggle("has-blockers", blockers.length > 0);
  }

  text("focusName", project.name);
  text("focusSummary", project.summary);
  text("focusState", project.state);
  text("focusBlockerCount", blockers.length.toLocaleString());
  text("focusTimeSpent", formatDuration(project.time_tracking?.approx_minutes_total));
  text("focusPath", project.path);
  text("focusResume", project.resume_file);

  if (state) {
    state.className = `state-pill ${colorClass(project.state, "state")}`;
  }

  const stateSelect = document.getElementById("projectStateSelect");
  if (stateSelect) {
    stateSelect.innerHTML = stateList.map((item) => `<option value="${item}">${item}</option>`).join("");
    stateSelect.value = project.state;
  }

  listItems("focusActions", project.next_actions, "li");
  listItems("focusBlockers", blockers, "li");

  const link = document.getElementById("focusLink");
  const primaryLink = project.links.primary || "#";
  const hasExternalLink = primaryLink !== "#";

  link.href = hasExternalLink ? primaryLink : "#";
  link.textContent = project.links.primary_label || "Open";
  link.classList.toggle("is-disabled", !hasExternalLink);
  link.toggleAttribute("aria-disabled", !hasExternalLink);

  if (hasExternalLink) {
    link.target = "_blank";
    link.rel = "noopener";
  } else {
    link.removeAttribute("target");
    link.removeAttribute("rel");
  }
}

async function saveProjectState() {
  const project = currentProject();
  const select = document.getElementById("projectStateSelect");
  const button = document.getElementById("saveProjectState");
  if (!project || !select || !button) return;

  const nextState = select.value;
  if (!stateList.includes(nextState)) {
    text("syncStatus", "State update skipped: invalid state.");
    return;
  }
  if (nextState === project.state) {
    text("syncStatus", `${project.name} is already ${nextState}.`);
    return;
  }
  if (!window.confirm(`Move "${project.name}" from ${project.state} to ${nextState}?`)) {
    select.value = project.state;
    text("syncStatus", "State update cancelled.");
    return;
  }

  button.disabled = true;
  text("saveProjectState", "Saving...");
  text("syncStatus", "Saving project state.");

  try {
    const response = await fetch("/api/project-state", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Project-Dashboard-User-Action": "update-project-state",
      },
      body: JSON.stringify({ project_id: project.id, state: nextState, user_action: "update-project-state" }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    dashboard.data = payload.dashboard;
    dashboard.selectedId = project.id;
    dashboard.visibleStates.add(nextState);
    renderAll();
    text("syncStatus", `Moved ${project.name} to ${nextState}.`);
  } catch (error) {
    select.value = project.state;
    text("syncStatus", `State update skipped: ${error.message}`);
  } finally {
    button.disabled = false;
    text("saveProjectState", "Save State");
  }
}

function quoteShell(value) {
  return `'${String(value || "").replace(/'/g, "'\\''")}'`;
}

function serverProjectDirectory(project) {
  const path = project.path || "";
  const cloudMirrorPrefix = "\\\\dees-workbench\\cloud-mirror\\";
  if (path.startsWith("/")) return path;
  if (path.startsWith(cloudMirrorPrefix)) {
    return `/srv/cloud-mirror/${path.slice(cloudMirrorPrefix.length).replace(/\\/g, "/")}`;
  }
  return "/srv/cloud-mirror/project-dashboard";
}

function aiResumePacket(project) {
  const context = project.ai_context || {};
  const stateChange = context.last_state_change || {};
  const tracking = project.time_tracking || {};
  const spend = project.ai_spend || {};
  const sessions = tracking.sessions || [];
  const spendSessions = spend.sessions || [];
  const lines = [
    `Project: ${project.name}`,
    `State: ${project.state}`,
    `Last machine: ${context.last_machine || "Unknown"}`,
    `Conversation: ${context.conversation_name || "Unknown"}`,
    `Last state change: ${
      stateChange.changed_at
        ? `${stateChange.previous_state || "Unknown"} -> ${stateChange.state || project.state} by ${stateChange.changed_by || "unknown"} at ${stateChange.changed_at}`
        : "None recorded"
    }`,
    `Path: ${project.path}`,
    `Resume file: ${project.resume_file}`,
    `Approx project time tracked: ${tracking.approx_minutes_total || 0} minutes`,
    `Time confidence: ${tracking.confidence || "unknown"}`,
    `Estimated AI spend tracked: ${spend.currency || "USD"} ${(spend.estimated_usd_total || 0).toFixed(4)}`,
    "",
    "Summary:",
    project.summary || "None recorded.",
    "",
    "Next actions:",
    ...(project.next_actions || []).map((item) => `- ${item}`),
    "",
    "Blockers:",
    ...((project.blockers || []).length ? project.blockers.map((item) => `- ${item}`) : ["- None recorded."]),
    "",
    "Recent time sessions:",
    ...(sessions.length
      ? sessions.slice(-3).map((session) => {
          const parts = [
            session.date || "Unknown date",
            `${session.approx_minutes || 0} min`,
            session.machine || "unknown machine",
            session.conversation_name || "unknown conversation",
          ];
          return `- ${parts.join(" | ")}${session.summary ? `: ${session.summary}` : ""}`;
        })
      : ["- None recorded."]),
    "",
    "Recent AI spend sessions:",
    ...(spendSessions.length
      ? spendSessions.slice(-3).map((session) => {
          const parts = [
            session.date || "Unknown date",
            session.model || "unknown model",
            `${spend.currency || "USD"} ${(session.estimated_usd || 0).toFixed(4)}`,
            session.conversation_name || "unknown conversation",
          ];
          return `- ${parts.join(" | ")}${session.summary ? `: ${session.summary}` : ""}`;
        })
      : ["- None recorded."]),
    "",
    `Tags: ${(project.tags || []).join(", ") || "None"}`,
  ];

  return lines.join("\n");
}

function terminalResumeCommand(project) {
  const directory = serverProjectDirectory(project);
  const remoteCommand = `cd ${quoteShell(directory)} && exec bash -l`;
  return `ssh -t dee@dees-workbench ${quoteShell(remoteCommand)}`;
}

function hereDocCommand(command, marker, body) {
  return `${command} <<'${marker}'\n${body}\n${marker}`;
}

function codexResumeCommand(project) {
  const context = project.ai_context || {};
  const resumeCommand = context.codex_resume_command || "codex resume <session id unavailable>";
  return sshCodexResumeCommand(project, resumeCommand);
}

function sshCodexResumeCommand(project, resumeCommand) {
  const directory = serverProjectDirectory(project);
  const remoteCommand = `cd ${quoteShell(directory)} && ${resumeCommand}`;
  return `ssh -t dee@dees-workbench ${quoteShell(remoteCommand)}`;
}

function base64Utf8(value) {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

function chatGptResumeCommand(project) {
  const encoded = base64Utf8(aiResumePacket(project));
  return [
    "python3 - <<'PY'",
    "import base64, shutil, subprocess",
    `text = base64.b64decode(${JSON.stringify(encoded)}).decode("utf-8")`,
    "copied = False",
    "for command, args in (('wl-copy', []), ('xclip', ['-selection', 'clipboard']), ('xsel', ['--clipboard', '--input']), ('pbcopy', [])):",
    "    if shutil.which(command):",
    "        subprocess.run([command, *args], input=text.encode('utf-8'), check=False)",
    "        copied = True",
    "        break",
    "if not copied:",
    "    print(text)",
    "opener = shutil.which('xdg-open') or shutil.which('open')",
    "if opener:",
    "    subprocess.Popen([opener, 'https://chatgpt.com/'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)",
    "else:",
    "    print('https://chatgpt.com/')",
    "PY",
  ].join("\n");
}

function resumeShellCommand(project, target) {
  if (target === "chatgpt") return chatGptResumeCommand(project);
  if (target === "codex") return codexResumeCommand(project);
  return terminalResumeCommand(project);
}

async function copyText(value, elementId, restoredLabel) {
  const element = document.getElementById(elementId);
  try {
    await navigator.clipboard.writeText(value);
    text(elementId, "Copied");
  } catch {
    text(elementId, "Copy failed");
  }
  window.setTimeout(() => text(elementId, restoredLabel), 1400);
}

function currentProject() {
  return dashboardProjects().find((item) => item.id === dashboard.selectedId);
}

async function copyResumeShellCommand(target, elementId, restoredLabel) {
  const project = currentProject();
  if (!project) return;
  if (target === "codex") {
    try {
      const response = await fetch(`/api/codex-resume-command?project_id=${encodeURIComponent(project.id)}`, {
        cache: "no-store",
      });
      const payload = await response.json();
      if (!response.ok || !payload.command) throw new Error(payload.error || `HTTP ${response.status}`);
      await copyText(sshCodexResumeCommand(project, payload.command), elementId, restoredLabel);
    } catch {
      await copyText(codexResumeCommand(project), elementId, restoredLabel);
    }
    return;
  }
  await copyText(resumeShellCommand(project, target), elementId, restoredLabel);
}

async function loadAiBudget() {
  try {
    const response = await fetch("/api/ai-budget", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    dashboard.aiBudget = payload.budget || null;
  } catch {
    dashboard.aiBudget = null;
  }
  renderBudget();
}

async function loadDashboardData() {
  const failureMessage = "Database/API unavailable. Dashboard is not using fallback project data.";
  const response = await fetch("/api/dashboard", { cache: "no-store" });
  const payload = await response.json().catch(() => ({}));
  if (response.status === 401 || response.status === 403) {
    throw new Error(payload.error || "Not authorized to read dashboard data. Sign in through Cloudflare Access.");
  }
  if (!response.ok) throw new Error(payload.error || failureMessage);
  if (!payload.ok || !payload.dashboard) throw new Error(payload.error || "API dashboard payload missing");
  if (!Array.isArray(payload.dashboard.projects)) throw new Error(failureMessage);
  return payload.dashboard;
}

function renderAll() {
  renderOverview();
  renderBars();
  renderFilters();
  renderSortControls();
  renderProjects();
  renderCalendar();
  renderActivity();
}

async function syncSelectedProject() {
  const project = currentProject();
  const button = document.getElementById("syncSelectedProject");
  if (!project || !button) return;

  const budget = dashboard.aiBudget;
  const maxCost = budget ? formatMoney(budget.per_run_max_usd || 0) : "$0.010000";
  if (!window.confirm(`Run one AI sync for "${project.name}"? Server guardrail max is ${maxCost} for this click.`)) {
    text("syncStatus", "Sync cancelled.");
    return;
  }

  button.disabled = true;
  text("syncSelectedProject", "Syncing...");
  text("syncStatus", "Running one AI call for the selected project only.");

  try {
    const response = await fetch("/api/sync-selected-project", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Project-Dashboard-User-Action": "sync-selected",
      },
      body: JSON.stringify({ project_id: project.id, user_action: "sync-selected" }),
    });
    const payload = await response.json();
    if (response.status === 401 || response.status === 403) {
      throw new Error(payload.error || "Not authorized to sync the selected project.");
    }
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    dashboard.data = payload.dashboard;
    dashboard.aiBudget = payload.budget;
    dashboard.selectedId = project.id;
    renderAll();
    text("syncStatus", `Synced ${project.name}.`);
  } catch (error) {
    text("syncStatus", `Sync skipped: ${error.message}`);
    await loadAiBudget();
  } finally {
    button.disabled = false;
    text("syncSelectedProject", "Sync");
  }
}

function renderProjects() {
  const projects = visibleProjects();
  const cards = document.getElementById("projectCards");
  cards.innerHTML = "";
  text("resultCount", `${projects.length.toLocaleString()} projects`);

  if (!projects.some((project) => project.id === dashboard.selectedId)) {
    dashboard.selectedId = projects[0]?.id || dashboardProjects()[0]?.id || "";
  }
  renderFocus(dashboardProjects().find((project) => project.id === dashboard.selectedId));

  if (projects.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No projects match this filter.";
    cards.appendChild(empty);
    return;
  }

  projects.forEach((project) => {
    const card = document.createElement("article");
    card.className = `project-card${project.id === dashboard.selectedId ? " is-selected" : ""}`;
    card.innerHTML = `
      <div class="project-card-heading">
        <div>
          <span class="state-pill ${colorClass(project.state, "state")}">${project.state}</span>
          <h3>${project.name}</h3>
          <p>${project.summary}</p>
        </div>
        <button type="button">Select</button>
      </div>
      <dl class="project-meta">
        <div>
          <dt>Updated</dt>
          <dd>${formatDate(project.updated_at)}</dd>
        </div>
        <div>
          <dt>Path</dt>
          <dd class="mono">${project.path}</dd>
        </div>
        <div>
          <dt>Next</dt>
          <dd>${project.next_actions[0] || "No next action recorded."}</dd>
        </div>
      </dl>
      <div class="tag-row">
        ${project.tags.map((tag) => `<span>${tag}</span>`).join("")}
      </div>
    `;
    card.querySelector("button").addEventListener("click", () => {
      dashboard.selectedId = project.id;
      renderProjects();
      document.querySelector(".focus-panel").scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
    cards.appendChild(card);
  });
}

function renderActivity() {
  const rows = document.getElementById("activityRows");
  rows.innerHTML = "";

  dashboard.data.recent_activity.forEach((activity) => {
    const row = document.createElement("article");
    row.className = "activity-row";
    row.innerHTML = `
      <div>
        <strong>${activity.title}</strong>
        <p>${activity.summary}</p>
      </div>
      <span class="mono">${formatDate(activity.updated_at)}</span>
    `;
    rows.appendChild(row);
  });
}

async function copyResume() {
  const project = currentProject();
  if (!project) return;
  try {
    await navigator.clipboard.writeText(project.resume_file || project.path);
    text("copyResume", "Copied");
  } catch {
    text("copyResume", "Copy failed");
  }
  window.setTimeout(() => text("copyResume", "Copy Resume"), 1200);
}

async function init() {
  dashboard.data = await loadDashboardData();
  dashboard.selectedId = dashboardProjects()[0]?.id || "";

  document.getElementById("search").addEventListener("input", (event) => {
    dashboard.query = event.target.value;
    renderProjects();
    renderCalendar();
  });
  document.getElementById("sortKey").addEventListener("change", (event) => {
    dashboard.sortKey = event.target.value;
    renderProjects();
    renderCalendar();
    renderSortControls();
  });
  document.getElementById("sortDirection").addEventListener("click", () => {
    dashboard.sortDirection = dashboard.sortDirection === "asc" ? "desc" : "asc";
    renderProjects();
    renderCalendar();
    renderSortControls();
  });
  document.getElementById("calendarPrev").addEventListener("click", () => moveCalendarMonth(-1));
  document.getElementById("calendarToday").addEventListener("click", () => {
    const today = new Date().toISOString().slice(0, 10);
    dashboard.calendarDate = today.slice(0, 7);
    dashboard.selectedCalendarDate = today;
    renderCalendar();
  });
  document.getElementById("calendarNext").addEventListener("click", () => moveCalendarMonth(1));
  document.getElementById("copyResume").addEventListener("click", copyResume);
  document.getElementById("saveProjectState").addEventListener("click", saveProjectState);
  document.getElementById("syncSelectedProject").addEventListener("click", syncSelectedProject);
  document.getElementById("openChatGPT").addEventListener("click", () => {
    copyResumeShellCommand("chatgpt", "openChatGPT", "ChatGPT");
  });
  document.getElementById("openCodex").addEventListener("click", () => {
    copyResumeShellCommand("codex", "openCodex", "Codex");
  });
  document.getElementById("copyTerminal").addEventListener("click", () => {
    copyResumeShellCommand("terminal", "copyTerminal", "Terminal");
  });

  renderAll();
  loadAiBudget();
}

init().catch((error) => {
  text("dashboardStatus", `Could not load dashboard data: ${error.message}`);
});
