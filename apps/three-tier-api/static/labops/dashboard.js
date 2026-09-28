/* LabOps operations workspace: real API data, no fixtures, no third-party JS. */
"use strict";

(() => {
  const byId = (id) => document.getElementById(id);
  const state = {
    incidents: [],
    selectedId: null,
    selectionVersion: 0,
    analysisVersion: 0,
    pendingEvent: null,
    loading: false,
  };
  const statuses = new Set(["open", "investigating", "resolved"]);
  const severities = new Set(["low", "medium", "high", "critical"]);
  const route = "/api/v1/incidents";

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }

  function show(id, visible) {
    byId(id).classList.toggle("hidden", !visible);
  }

  function formatTime(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat(undefined, {
      month: "short", day: "numeric", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    }).format(date);
  }

  function shortId(value) {
    return typeof value === "string" ? "INC-" + value.slice(0, 8).toUpperCase() : "—";
  }

  function badge(value) {
    const label = node("span", "badge", value);
    if (statuses.has(value) || severities.has(value)) label.dataset.value = value;
    return label;
  }

  function errorMessage(error) {
    return error && error.message ? error.message : "Unable to reach the LabOps API.";
  }

  async function request(path, options) {
    const config = Object.assign({
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" },
    }, options || {});
    const response = await fetch(path, config);
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const message = data && data.error && data.error.message
        ? data.error.message : "Request failed (" + response.status + ").";
      throw new Error(message);
    }
    return data;
  }

  function connection(online) {
    byId("connection-pill").dataset.state = online ? "online" : "offline";
    byId("connection-text").textContent = online ? "Database connected" : "Database unavailable";
  }

  function globalError(message) {
    byId("global-error-text").textContent = message;
    show("global-error", true);
  }

  function metrics() {
    const list = state.incidents;
    for (const [name, count] of [
      ["visible", list.length],
      ["open", list.filter((item) => item.status === "open").length],
      ["investigating", list.filter((item) => item.status === "investigating").length],
      ["resolved", list.filter((item) => item.status === "resolved").length],
    ]) byId("count-" + name).textContent = count.toLocaleString();
  }

  function renderList() {
    const query = byId("incident-search").value.trim().toLowerCase();
    const status = byId("status-filter").value;
    const items = state.incidents.filter((incident) =>
      (status === "all" || incident.status === status) &&
      (!query || incident.title.toLowerCase().includes(query) ||
        incident.id.toLowerCase().includes(query) ||
        shortId(incident.id).toLowerCase().includes(query))
    );

    byId("incident-list-count").textContent = String(items.length);
    const container = byId("incident-list");
    container.replaceChildren();
    const fragment = document.createDocumentFragment();

    items.forEach((incident) => {
      const row = node("button", "incident-row");
      row.type = "button";
      row.dataset.severity = severities.has(incident.severity) ? incident.severity : "medium";
      row.setAttribute("aria-pressed", String(incident.id === state.selectedId));
      row.setAttribute("aria-label", shortId(incident.id) + ", " + incident.title + ", " + incident.status);
      if (incident.id === state.selectedId) row.classList.add("selected");
      row.append(node("span", "row-accent"));

      const copy = node("span", "row-copy");
      copy.append(node("span", "row-title", incident.title));
      const meta = node("span", "row-meta");
      meta.append(node("span", "mono", shortId(incident.id)));
      meta.append(node("span", "sep", "•"));
      meta.append(node("span", null, incident.severity.toUpperCase()));
      copy.append(meta);
      row.append(copy);

      const side = node("span", "row-side");
      side.append(badge(incident.status));
      side.append(node("span", "row-time", formatTime(incident.created_at)));
      row.append(side);
      row.addEventListener("click", () => selectIncident(incident.id));
      fragment.append(row);
    });

    container.append(fragment);
    show("incidents-loading", false);
    show("incidents-empty", items.length === 0);
    byId("incidents-empty-text").textContent = state.incidents.length
      ? "Nothing matches those filters. Try a different search or status."
      : "Create your first synthetic incident to begin.";
    show("empty-create-button", state.incidents.length === 0);
  }

  function clearDetail() {
    show("detail-placeholder", true);
    show("detail-content", false);
    show("investigation-empty", true);
    show("investigation-result", false);
    byId("event-count").textContent = "—";
    byId("new-event-button").disabled = true;
    show("event-action-message", false);
    const cell = node("td", "table-empty", "Select an incident to view associated events.");
    cell.colSpan = 4;
    const row = node("tr");
    row.append(cell);
    byId("event-rows").replaceChildren(row);
  }

  function displayDetail(incident) {
    if (!incident) return clearDetail();
    show("detail-placeholder", false);
    show("detail-content", true);
    byId("case-id").textContent = shortId(incident.id);
    const severity = byId("case-severity");
    severity.textContent = incident.severity;
    severity.dataset.value = severities.has(incident.severity) ? incident.severity : "";
    byId("case-title").textContent = incident.title;
    byId("case-description").textContent = incident.description;
    byId("case-created").textContent = formatTime(incident.created_at);
    byId("case-updated").textContent = formatTime(incident.updated_at);
    byId("case-status").value = statuses.has(incident.status) ? incident.status : "open";
    byId("case-notes").value = incident.notes || "";
    byId("triage-message").textContent = "";
  }

  function viewSelection(id) {
    const incident = state.incidents.find((item) => item.id === id);
    displayDetail(incident || null);
    if (!incident) return;
    byId("new-event-button").disabled = false;
    show("event-action-message", false);
    byId("event-count").textContent = "…";
    const cell = node("td", "table-empty", "Loading associated events…");
    cell.colSpan = 4;
    const tr = node("tr");
    tr.append(cell);
    byId("event-rows").replaceChildren(tr);
    show("investigation-result", false);
    show("investigation-empty", true);
    byId("investigation-empty").querySelector("strong").textContent = "Running read-only analysis…";
    byId("investigation-empty").querySelector("p").textContent = "Querying PostgreSQL for this incident.";
  }

  async function selectIncident(id) {
    if (id === state.selectedId && byId("detail-content").classList.contains("hidden") === false) return;
    state.selectedId = id;
    const version = ++state.selectionVersion;
    renderList();
    viewSelection(id);
    const url = new URL(window.location.href);
    url.searchParams.set("incident", id);
    history.replaceState(null, "", url.pathname + url.search + url.hash);
    await Promise.all([loadEvents(id, version), runInvestigation(id, version)]);
  }

  async function loadEvents(id, version) {
    try {
      const data = await request(route + "/" + encodeURIComponent(id) + "/events?limit=100");
      if (version !== state.selectionVersion || id !== state.selectedId) return;
      const rows = byId("event-rows");
      const events = data.events || [];
      byId("event-count").textContent = String(events.length);
      const fragment = document.createDocumentFragment();
      if (!events.length) {
        const tr = node("tr");
        const td = node("td", "table-empty", "No security events recorded for this incident.");
        td.colSpan = 4;
        tr.append(td);
        fragment.append(tr);
      }
      events.forEach((event) => {
        const tr = node("tr");
        tr.append(node("td", "mono", event.source_ip));
        tr.append(node("td", null, event.username));
        tr.append(node("td", "event-type", event.event_type));
        tr.append(node("td", null, formatTime(event.observed_at)));
        fragment.append(tr);
      });
      rows.replaceChildren(fragment);
    } catch (error) {
      if (version !== state.selectionVersion) return;
      byId("event-count").textContent = "—";
      const tr = node("tr");
      const td = node("td", "table-empty", "Unable to load events: " + errorMessage(error));
      td.colSpan = 4;
      tr.append(td);
      byId("event-rows").replaceChildren(tr);
    }
  }

  function displayInvestigation(report) {
    byId("analysis-attempts").textContent = report.total_failed_logins.toLocaleString();
    byId("analysis-ips").textContent = report.distinct_source_ips.toLocaleString();
    byId("analysis-window").textContent = String(report.window_minutes) + " min";
    byId("analysis-range").textContent =
      formatTime(report.window_start) + " — " + formatTime(report.window_end);

    const chart = byId("source-chart");
    chart.replaceChildren();
    const sources = report.sources || [];
    if (!sources.length) {
      chart.append(node("p", "analysis-note", "No failed SSH logins in this observation window."));
    }
    const maximum = Math.max(1, ...sources.map((source) => source.failed_logins));
    sources.forEach((source) => {
      const row = node("div", "source-row");
      row.dataset.signal = String(Boolean(source.threshold_met));
      const name = node("div", "source-name");
      name.append(node("strong", "mono", source.source_ip));
      name.append(node("small", String(source.distinct_usernames) + " usernames"));
      const track = node("div", "source-track");
      const bar = node("div", "source-bar");
      bar.style.width = String(Math.max(2, source.failed_logins / maximum * 100)) + "%";
      bar.setAttribute("role", "img");
      bar.setAttribute("aria-label", String(source.failed_logins) + " failed logins");
      track.append(bar);
      const count = node("div", "source-value", source.failed_logins.toLocaleString());
      count.append(node("small", source.threshold_met ? "Above threshold" : "Below threshold"));
      row.append(name, track, count);
      chart.append(row);
    });
    byId("analysis-note").textContent = report.source_ips_truncated
      ? "Showing the first 100 sources; full-window totals include additional sources. A threshold is a signal, not proof of attack."
      : "A threshold is an investigation signal, not a determination of intent. No response was executed.";
    show("investigation-empty", false);
    show("investigation-result", true);
  }

  async function runInvestigation(id, version) {
    if (!id) return;
    const analysisVersion = ++state.analysisVersion;
    const button = byId("run-investigation");
    button.disabled = true;
    show("investigation-empty", true);
    show("investigation-result", false);
    byId("investigation-empty").querySelector("strong").textContent = "Running read-only analysis…";
    byId("investigation-empty").querySelector("p").textContent = "Aggregating failed logins in PostgreSQL.";
    try {
      const params = new URLSearchParams({
        window_minutes: byId("window-filter").value,
        threshold: byId("threshold-filter").value,
      });
      const result = await request(
        route + "/" + encodeURIComponent(id) +
        "/investigations/ssh-login-failures?" + params.toString()
      );
      if (version !== state.selectionVersion || analysisVersion !== state.analysisVersion ||
          id !== state.selectedId) return;
      displayInvestigation(result.investigation);
    } catch (error) {
      if (version !== state.selectionVersion || analysisVersion !== state.analysisVersion) return;
      byId("investigation-empty").querySelector("strong").textContent = "Investigation unavailable";
      byId("investigation-empty").querySelector("p").textContent = errorMessage(error);
    } finally {
      if (version === state.selectionVersion && analysisVersion === state.analysisVersion) {
        button.disabled = false;
      }
    }
  }

  async function refresh(preferredId) {
    if (state.loading) return;
    state.loading = true;
    byId("refresh-button").disabled = true;
    show("global-error", false);
    if (!state.incidents.length) show("incidents-loading", true);
    try {
      const results = await Promise.allSettled([
        request("/health"),
        request(route + "?limit=100"),
      ]);
      const health = results[0];
      connection(health.status === "fulfilled" && health.value.status === "ok");
      if (results[1].status !== "fulfilled") throw results[1].reason;

      state.incidents = results[1].value.incidents || [];
      metrics();
      byId("last-sync").textContent = formatTime(new Date().toISOString());
      const initialId = preferredId || state.selectedId ||
        new URL(window.location.href).searchParams.get("incident");
      const selected = state.incidents.find((incident) => incident.id === initialId)
        || state.incidents[0];
      if (!selected) {
        state.selectedId = null;
        ++state.selectionVersion;
        renderList();
        clearDetail();
      } else {
        // Force a refresh of events and analysis even if the selected ID is unchanged.
        state.selectedId = null;
        await selectIncident(selected.id);
      }
    } catch (error) {
      globalError("Unable to fetch incidents: " + errorMessage(error));
      show("incidents-loading", false);
    } finally {
      state.loading = false;
      byId("refresh-button").disabled = false;
    }
  }

  async function createIncident(event) {
    event.preventDefault();
    const button = byId("submit-create");
    const title = byId("new-title").value.trim();
    const description = byId("new-description").value.trim();
    const severity = byId("new-severity").value;
    if (!title || !description || !severities.has(severity)) {
      byId("create-error").textContent = "Title and description are required.";
      show("create-error", true);
      return;
    }
    button.disabled = true;
    show("create-error", false);
    try {
      const data = await request(route, {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ title, description, severity }),
      });
      byId("create-dialog").close();
      byId("create-form").reset();
      byId("incident-search").value = "";
      byId("status-filter").value = "all";
      await refresh(data.incident.id);
    } catch (error) {
      byId("create-error").textContent = errorMessage(error);
      show("create-error", true);
    } finally {
      button.disabled = false;
    }
  }

  async function saveTriage(event) {
    event.preventDefault();
    const id = state.selectedId;
    if (!id) return;
    const version = state.selectionVersion;
    const button = byId("save-triage");
    const message = byId("triage-message");
    button.disabled = true;
    message.textContent = "Saving…";
    try {
      const data = await request(route + "/" + encodeURIComponent(id), {
        method: "PATCH",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({
          status: byId("case-status").value,
          notes: byId("case-notes").value,
        }),
      });
      if (version !== state.selectionVersion || id !== state.selectedId) return;
      state.incidents = state.incidents.map((item) =>
        item.id === id ? data.incident : item
      );
      metrics();
      renderList();
      displayDetail(data.incident);
      message.textContent = "Saved to PostgreSQL";
    } catch (error) {
      if (version === state.selectionVersion) message.textContent = errorMessage(error);
    } finally {
      button.disabled = false;
    }
  }

  function documentationIp(value) {
    const address = value.trim();
    const v4 = /^(192\.0\.2|198\.51\.100|203\.0\.113)\.(\d{1,3})$/.exec(address);
    if (v4) return Number(v4[2]) <= 255;
    // PostgreSQL/the API performs final IPv6 validation; only the RFC 3849
    // documentation prefix is accepted from this synthetic browser workflow.
    return /^2001:db8:/i.test(address) && address.length <= 45;
  }

  function newEventIdentity() {
    // crypto.randomUUID is not exposed on every HTTP origin (including the
    // operator /32 AWS lab). Use a nonsecret, per-form idempotency key there.
    const suffix = window.crypto && typeof window.crypto.randomUUID === "function"
      ? window.crypto.randomUUID()
      : Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
    return {
      source_event_id: "manual-ui-" + suffix,
      observed_at: new Date().toISOString(),
    };
  }

  function prepareEvent() {
    state.pendingEvent = newEventIdentity();
    byId("new-event-observed").textContent = formatTime(state.pendingEvent.observed_at);
    show("event-create-error", false);
  }

  function eventDialog(open) {
    const modal = byId("event-dialog");
    if (open) {
      const incident = state.incidents.find((item) => item.id === state.selectedId);
      if (!incident) return;
      byId("event-form").reset();
      byId("event-incident-title").textContent = incident.title;
      prepareEvent();
      modal.showModal();
      byId("new-event-ip").focus();
    } else {
      modal.close();
      state.pendingEvent = null;
    }
  }

  async function attachEvent(event) {
    event.preventDefault();
    const id = state.selectedId;
    if (!id || !state.pendingEvent) return;
    const version = state.selectionVersion;
    const ip = byId("new-event-ip").value.trim();
    const username = byId("new-event-username").value.trim();
    if (!documentationIp(ip)) {
      byId("event-create-error").textContent =
        "Use a reserved documentation IP such as 198.51.100.23; never a real address.";
      show("event-create-error", true);
      return;
    }
    if (!username || username.length > 128) {
      byId("event-create-error").textContent = "Enter an attempted username (1–128 characters).";
      show("event-create-error", true);
      return;
    }
    const payload = {
      source: "cowrie",
      event_type: "cowrie.login.failed",
      ...state.pendingEvent,
      source_ip: ip,
      username,
    };
    const button = byId("submit-event");
    button.disabled = true;
    show("event-create-error", false);
    try {
      await request(route + "/" + encodeURIComponent(id) + "/events", {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      eventDialog(false);
      if (version !== state.selectionVersion || id !== state.selectedId) return;
      byId("event-action-message").textContent =
        "Synthetic SSH evidence saved. Event history and read-only analysis refreshed.";
      byId("event-action-message").dataset.state = "success";
      show("event-action-message", true);
      await Promise.all([loadEvents(id, version), runInvestigation(id, version)]);
    } catch (error) {
      // Keep the exact event ID and UTC time on retries. If the response was
      // lost after commit, PostgreSQL returns the existing event rather than
      // inserting a duplicate.
      byId("event-create-error").textContent = errorMessage(error) + " You can retry this entry.";
      show("event-create-error", true);
    } finally {
      button.disabled = false;
    }
  }

  function dialog(open) {
    const modal = byId("create-dialog");
    if (open) {
      show("create-error", false);
      modal.showModal();
      byId("new-title").focus();
    } else modal.close();
  }

  byId("new-event-button").addEventListener("click", () => eventDialog(true));
  byId("close-event-dialog").addEventListener("click", () => eventDialog(false));
  byId("cancel-event-create").addEventListener("click", () => eventDialog(false));
  byId("event-form").addEventListener("submit", attachEvent);
  for (const id of ["new-event-ip", "new-event-username"]) {
    byId(id).addEventListener("input", prepareEvent);
  }
  byId("event-dialog").addEventListener("click", (event) => {
    if (event.target === byId("event-dialog")) eventDialog(false);
  });
  byId("event-dialog").addEventListener("close", () => { state.pendingEvent = null; });
  byId("new-incident-button").addEventListener("click", () => dialog(true));
  byId("empty-create-button").addEventListener("click", () => dialog(true));
  byId("close-dialog").addEventListener("click", () => dialog(false));
  byId("cancel-create").addEventListener("click", () => dialog(false));
  byId("create-form").addEventListener("submit", createIncident);
  byId("triage-form").addEventListener("submit", saveTriage);
  byId("refresh-button").addEventListener("click", () => refresh());
  byId("retry-button").addEventListener("click", () => refresh());
  byId("incident-search").addEventListener("input", renderList);
  byId("status-filter").addEventListener("change", renderList);
  byId("run-investigation").addEventListener("click", () =>
    runInvestigation(state.selectedId, state.selectionVersion)
  );
  for (const id of ["window-filter", "threshold-filter"]) {
    byId(id).addEventListener("change", () =>
      runInvestigation(state.selectedId, state.selectionVersion)
    );
  }
  byId("create-dialog").addEventListener("click", (event) => {
    if (event.target === byId("create-dialog")) dialog(false);
  });

  clearDetail();
  refresh();
})();
