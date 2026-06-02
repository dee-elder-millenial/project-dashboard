const dashboard = {
  data: null,
  query: "",
  filter: "all",
  selectedId: "",
};

const filterList = ["all", "Active", "Staged", "Synced", "Reference"];

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

function colorClass(state, prefix) {
  return `${prefix}-${state.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
}

function searchText(project) {
  return [
    project.name,
    project.state,
    project.summary,
    project.path,
    project.resume_file,
    ...(project.next_actions || []),
    ...(project.blockers || []),
    ...(project.tags || []),
  ]
    .join(" ")
    .toLowerCase();
}

function visibleProjects() {
  const query = dashboard.query.trim().toLowerCase();
  return dashboard.data.projects.filter((project) => {
    const stateMatches = dashboard.filter === "all" || project.state === dashboard.filter;
    const queryMatches = !query || searchText(project).includes(query);
    return stateMatches && queryMatches;
  });
}

function renderOverview() {
  const projects = dashboard.data.projects;
  text("projectCount", projects.length.toLocaleString());
  text("activeCount", projects.filter((project) => project.state === "Active").length.toLocaleString());
  text("blockedCount", projects.filter((project) => project.blockers.length > 0).length.toLocaleString());
  text("updatedAt", formatDate(dashboard.data.generated_at));
  text("dashboardStatus", `Tracking ${projects.length} projects from ${dashboard.data.source_root}`);
}

function renderBars() {
  const rows = document.getElementById("stateBars");
  const total = dashboard.data.projects.length || 1;
  rows.innerHTML = "";

  ["Active", "Staged", "Synced", "Reference"].forEach((state) => {
    const count = dashboard.data.projects.filter((project) => project.state === state).length;
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

  filterList.forEach((filter) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = dashboard.filter === filter ? "is-active" : "";
    button.textContent = filter === "all" ? "All" : filter;
    button.addEventListener("click", () => {
      dashboard.filter = filter;
      renderProjects();
      renderFilters();
    });
    filters.appendChild(button);
  });
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
  text("focusPath", project.path);
  text("focusResume", project.resume_file);

  if (state) {
    state.className = `state-pill ${colorClass(project.state, "state")}`;
  }

  listItems("focusActions", project.next_actions, "li");
  listItems("focusBlockers", blockers, "li");

  const link = document.getElementById("focusLink");
  link.href = project.links.primary || "#";
  link.textContent = project.links.primary_label || "Open";
}

function renderProjects() {
  const projects = visibleProjects();
  const cards = document.getElementById("projectCards");
  cards.innerHTML = "";
  text("resultCount", `${projects.length.toLocaleString()} projects`);

  if (!projects.some((project) => project.id === dashboard.selectedId)) {
    dashboard.selectedId = projects[0]?.id || dashboard.data.projects[0]?.id || "";
  }
  renderFocus(dashboard.data.projects.find((project) => project.id === dashboard.selectedId));

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
  const project = dashboard.data.projects.find((item) => item.id === dashboard.selectedId);
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
  const response = await fetch("data/projects.json", { cache: "no-store" });
  dashboard.data = await response.json();
  dashboard.selectedId = dashboard.data.projects[0]?.id || "";

  document.getElementById("search").addEventListener("input", (event) => {
    dashboard.query = event.target.value;
    renderProjects();
  });
  document.getElementById("copyResume").addEventListener("click", copyResume);

  renderOverview();
  renderBars();
  renderFilters();
  renderProjects();
  renderActivity();
}

init().catch((error) => {
  text("dashboardStatus", `Could not load dashboard data: ${error.message}`);
});
