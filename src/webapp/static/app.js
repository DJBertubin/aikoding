"use strict";

const root = document.getElementById("view-root");
const titleEl = document.getElementById("view-title");
const subtitleEl = document.getElementById("view-subtitle");

const VIEW_META = {
  overview: ["Overview", "Live status of the Python porting workspace."],
  commands: ["Commands", "Browse and search the mirrored command surface."],
  tools: ["Tools", "Browse, filter, and inspect the mirrored tool surface."],
  router: ["Prompt Router", "Score a prompt against the command/tool inventories."],
  bootstrap: ["Bootstrap Session", "Run a full mirrored runtime session for a prompt."],
  turnloop: ["Turn Loop", "Run a stateful multi-turn loop with budget tracking."],
  graphs: ["Graphs & Pools", "Command graph, tool pool, and bootstrap stages."],
  parity: ["Parity Audit", "Coverage of the Python port vs the archived surface."],
  setup: ["Setup Report", "Startup, prefetch, and deferred-init report."],
  modes: ["Runtime Modes", "Simulate remote / ssh / teleport / direct-connect / deep-link."],
  sessions: ["Sessions", "Persist a transcript and reload stored sessions."],
};

// --- tiny DOM + fetch helpers ---------------------------------------------

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children) {
    if (c == null) continue;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return node;
}

function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }

async function apiGet(path) {
  const res = await fetch(path);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
  return data;
}

async function apiPost(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
  return data;
}

function errorBox(message) {
  return el("div", { class: "error-box" }, "⚠ " + message);
}

function panel(titleText, ...children) {
  return el("div", { class: "panel" }, titleText ? el("h2", {}, titleText) : null, ...children);
}

function moduleTable(rows, onClick) {
  const table = el("table");
  table.appendChild(
    el("thead", {}, el("tr", {},
      el("th", {}, "Name"), el("th", {}, "Responsibility"), el("th", {}, "Source")))
  );
  const tbody = el("tbody");
  if (!rows.length) {
    tbody.appendChild(el("tr", {}, el("td", { colspan: "3", class: "muted" }, "No entries.")));
  }
  for (const m of rows) {
    const tr = el("tr", { class: onClick ? "entry-row" : "" },
      el("td", {}, el("code", {}, m.name)),
      el("td", {}, m.responsibility || "—"),
      el("td", { class: "muted mono" }, m.source_hint || "—"));
    if (onClick) tr.addEventListener("click", () => onClick(m));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  return el("div", { class: "scroll-x" }, table);
}

function setBusy(btn, busy) {
  if (!btn) return;
  btn.disabled = busy;
  if (busy) { btn.dataset.label = btn.textContent; btn.textContent = "Working…"; }
  else if (btn.dataset.label) btn.textContent = btn.dataset.label;
}

// --- views -----------------------------------------------------------------

const views = {};

views.overview = async () => {
  clear(root);
  root.appendChild(el("div", { class: "loading" }, "Loading…"));
  try {
    const [ov, sum] = await Promise.all([apiGet("/api/overview"), apiGet("/api/summary")]);
    clear(root);
    const grid = el("div", { class: "grid" });
    const card = (label, value, sub) =>
      el("div", { class: "stat-card" },
        el("div", { class: "label" }, label),
        el("div", { class: "value" }, String(value)),
        sub ? el("div", { class: "sub" }, sub) : null);
    grid.appendChild(card("Python files", ov.total_python_files, ov.top_level_modules + " top-level modules"));
    grid.appendChild(card("Commands", ov.command_count, "mirrored command entries"));
    grid.appendChild(card("Tools", ov.tool_count, "mirrored tool entries"));
    grid.appendChild(card("Archive present", ov.archive_present ? "yes" : "no",
      "command parity " + ov.parity.command_entry_ratio.join(" / ")));
    root.appendChild(grid);
    root.appendChild(panel("Workspace summary", el("pre", { class: "md" }, sum.markdown)));
  } catch (e) {
    clear(root);
    root.appendChild(errorBox(e.message));
  }
};

function inventoryView(kind) {
  // kind: "commands" | "tools"
  return async () => {
    clear(root);
    const isTool = kind === "tools";
    const queryInput = el("input", { type: "text", placeholder: "Search by name or source…" });
    const limitInput = el("input", { type: "number", value: "25", min: "1", max: "500" });
    const resultBox = el("div", {});
    const detailBox = el("div", {});

    const filters = {};
    if (isTool) {
      filters.simple = el("input", { type: "checkbox" });
      filters.noMcp = el("input", { type: "checkbox" });
    } else {
      filters.noPlugin = el("input", { type: "checkbox" });
      filters.noSkill = el("input", { type: "checkbox" });
    }

    const runBtn = el("button", { class: "btn" }, "Search");

    async function load() {
      clear(detailBox);
      resultBox.replaceChildren(el("div", { class: "loading" }, "Loading…"));
      try {
        const p = new URLSearchParams();
        if (queryInput.value.trim()) p.set("query", queryInput.value.trim());
        p.set("limit", limitInput.value || "25");
        let data;
        if (isTool) {
          if (filters.simple.checked) p.set("simple_mode", "1");
          if (filters.noMcp.checked) p.set("no_mcp", "1");
          data = await apiGet("/api/tools?" + p.toString());
          renderResult(data.tools, data);
        } else {
          if (filters.noPlugin.checked) p.set("no_plugin", "1");
          if (filters.noSkill.checked) p.set("no_skill", "1");
          data = await apiGet("/api/commands?" + p.toString());
          renderResult(data.commands, data);
        }
      } catch (e) {
        resultBox.replaceChildren(errorBox(e.message));
      }
    }

    function renderResult(rows, data) {
      resultBox.replaceChildren(
        el("p", { class: "muted", style: "margin-bottom:10px" },
          `Showing ${data.returned} of ${data.total} entries` + (data.query ? ` matching “${data.query}”` : "")),
        moduleTable(rows, (m) => showDetail(m.name))
      );
    }

    async function showDetail(name) {
      try {
        const m = await apiGet(`/api/${isTool ? "tool" : "command"}/` + encodeURIComponent(name));
        const execLabel = isTool ? "Payload" : "Prompt";
        const execInput = el("input", { type: "text", placeholder: execLabel + " to simulate…", class: "" });
        const execOut = el("div", {});
        const execBtn = el("button", { class: "btn secondary" }, "Simulate execution");
        execBtn.addEventListener("click", async () => {
          setBusy(execBtn, true);
          try {
            const r = isTool
              ? await apiPost("/api/exec-tool", { name: m.name, payload: execInput.value })
              : await apiPost("/api/exec-command", { name: m.name, prompt: execInput.value });
            execOut.replaceChildren(el("pre", { class: "md" }, r.message + "\nhandled=" + r.handled));
          } catch (e) {
            execOut.replaceChildren(errorBox(e.message));
          } finally { setBusy(execBtn, false); }
        });
        detailBox.replaceChildren(panel("Detail — " + m.name,
          el("div", { class: "kv" },
            el("div", { class: "k" }, "Name"), el("div", { class: "v" }, m.name),
            el("div", { class: "k" }, "Responsibility"), el("div", { class: "v" }, m.responsibility),
            el("div", { class: "k" }, "Source hint"), el("div", { class: "v" }, m.source_hint),
            el("div", { class: "k" }, "Status"), el("div", { class: "v" }, m.status)),
          el("div", { class: "form-row", style: "margin-top:16px" },
            el("div", { class: "field grow" }, el("label", {}, execLabel), execInput), execBtn),
          execOut));
      } catch (e) {
        detailBox.replaceChildren(errorBox(e.message));
      }
    }

    const filterRow = isTool
      ? el("div", { class: "checkbox-row" },
          el("label", {}, filters.simple, "simple mode"),
          el("label", {}, filters.noMcp, "exclude MCP"))
      : el("div", { class: "checkbox-row" },
          el("label", {}, filters.noPlugin, "exclude plugin commands"),
          el("label", {}, filters.noSkill, "exclude skill commands"));

    runBtn.addEventListener("click", load);
    queryInput.addEventListener("keydown", (e) => { if (e.key === "Enter") load(); });

    root.replaceChildren(
      panel(null,
        el("div", { class: "form-row" },
          el("div", { class: "field grow" }, el("label", {}, "Search"), queryInput),
          el("div", { class: "field" }, el("label", {}, "Limit"), limitInput),
          runBtn),
        filterRow),
      resultBox, detailBox);
    load();
  };
}

views.commands = inventoryView("commands");
views.tools = inventoryView("tools");

views.router = async () => {
  const promptInput = el("input", { type: "text", placeholder: "e.g. review MCP tool" });
  const limitInput = el("input", { type: "number", value: "5", min: "1", max: "50" });
  const out = el("div", {});
  const btn = el("button", { class: "btn" }, "Route prompt");

  async function run() {
    setBusy(btn, true);
    out.replaceChildren(el("div", { class: "loading" }, "Routing…"));
    try {
      const data = await apiPost("/api/route", {
        prompt: promptInput.value, limit: Number(limitInput.value || 5),
      });
      const table = el("table");
      table.appendChild(el("thead", {}, el("tr", {},
        el("th", {}, "Kind"), el("th", {}, "Name"), el("th", {}, "Score"), el("th", {}, "Source"))));
      const tb = el("tbody");
      if (!data.matches.length) tb.appendChild(el("tr", {}, el("td", { colspan: "4", class: "muted" }, "No matches.")));
      for (const m of data.matches) {
        tb.appendChild(el("tr", {},
          el("td", {}, el("span", { class: "tag " + m.kind }, m.kind)),
          el("td", {}, el("code", {}, m.name)),
          el("td", {}, String(m.score)),
          el("td", { class: "muted mono" }, m.source_hint)));
      }
      table.appendChild(tb);
      out.replaceChildren(el("p", { class: "muted", style: "margin-bottom:10px" },
        `${data.count} match(es) for “${data.prompt}”`), el("div", { class: "scroll-x" }, table));
    } catch (e) {
      out.replaceChildren(errorBox(e.message));
    } finally { setBusy(btn, false); }
  }
  btn.addEventListener("click", run);
  promptInput.addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
  root.replaceChildren(panel(null,
    el("div", { class: "form-row" },
      el("div", { class: "field grow" }, el("label", {}, "Prompt"), promptInput),
      el("div", { class: "field" }, el("label", {}, "Limit"), limitInput), btn)), out);
};

views.bootstrap = async () => {
  const promptInput = el("input", { type: "text", placeholder: "e.g. review MCP tool" });
  const limitInput = el("input", { type: "number", value: "5", min: "1", max: "50" });
  const out = el("div", {});
  const btn = el("button", { class: "btn" }, "Run bootstrap session");

  async function run() {
    setBusy(btn, true);
    out.replaceChildren(el("div", { class: "loading" }, "Bootstrapping session…"));
    try {
      const d = await apiPost("/api/bootstrap", {
        prompt: promptInput.value, limit: Number(limitInput.value || 5),
      });
      const matchPills = el("div", { class: "pill-row" });
      d.routed_matches.forEach((m) =>
        matchPills.appendChild(el("span", { class: "pill" }, `${m.kind}:${m.name} (${m.score})`)));
      out.replaceChildren(
        panel("Routed matches", d.routed_matches.length ? matchPills : el("p", { class: "muted" }, "none")),
        panel("Turn result",
          el("div", { class: "kv" },
            el("div", { class: "k" }, "Stop reason"), el("div", { class: "v" }, d.turn_result.stop_reason),
            el("div", { class: "k" }, "Matched commands"), el("div", { class: "v" }, d.turn_result.matched_commands.join(", ") || "none"),
            el("div", { class: "k" }, "Matched tools"), el("div", { class: "v" }, d.turn_result.matched_tools.join(", ") || "none"),
            el("div", { class: "k" }, "Usage"), el("div", { class: "v" }, `in=${d.turn_result.usage.input_tokens} out=${d.turn_result.usage.output_tokens}`),
            el("div", { class: "k" }, "Session path"), el("div", { class: "v" }, d.persisted_session_path)),
          el("h3", {}, "Output"), el("pre", { class: "md" }, d.turn_result.output)),
        panel("Full session report", el("pre", { class: "md" }, d.markdown)));
    } catch (e) {
      out.replaceChildren(errorBox(e.message));
    } finally { setBusy(btn, false); }
  }
  btn.addEventListener("click", run);
  promptInput.addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
  root.replaceChildren(panel(null,
    el("div", { class: "form-row" },
      el("div", { class: "field grow" }, el("label", {}, "Prompt"), promptInput),
      el("div", { class: "field" }, el("label", {}, "Route limit"), limitInput), btn)), out);
};

views.turnloop = async () => {
  const promptInput = el("input", { type: "text", placeholder: "e.g. review MCP tool" });
  const turnsInput = el("input", { type: "number", value: "3", min: "1", max: "12" });
  const structured = el("input", { type: "checkbox" });
  const out = el("div", {});
  const btn = el("button", { class: "btn" }, "Run turn loop");

  async function run() {
    setBusy(btn, true);
    out.replaceChildren(el("div", { class: "loading" }, "Running loop…"));
    try {
      const d = await apiPost("/api/turn-loop", {
        prompt: promptInput.value,
        max_turns: Number(turnsInput.value || 3),
        structured_output: structured.checked,
      });
      const wrap = el("div", {});
      d.turns.forEach((t) => {
        wrap.appendChild(panel("Turn " + t.index,
          el("div", { class: "kv" },
            el("div", { class: "k" }, "Stop reason"), el("div", { class: "v" }, t.stop_reason),
            el("div", { class: "k" }, "Usage"), el("div", { class: "v" }, `in=${t.usage.input_tokens} out=${t.usage.output_tokens}`)),
          el("pre", { class: "md" }, t.output)));
      });
      out.replaceChildren(wrap.children.length ? wrap : el("p", { class: "muted" }, "No turns produced."));
    } catch (e) {
      out.replaceChildren(errorBox(e.message));
    } finally { setBusy(btn, false); }
  }
  btn.addEventListener("click", run);
  root.replaceChildren(panel(null,
    el("div", { class: "form-row" },
      el("div", { class: "field grow" }, el("label", {}, "Prompt"), promptInput),
      el("div", { class: "field" }, el("label", {}, "Max turns"), turnsInput),
      el("div", { class: "field" }, el("label", {}, " "),
        el("label", { class: "" }, structured, " structured output")),
      btn)), out);
};

views.graphs = async () => {
  const tabs = ["Command graph", "Tool pool", "Bootstrap graph"];
  const body = el("div", {});
  const bar = el("div", { class: "subtabs" });
  let active = 0;

  async function render() {
    body.replaceChildren(el("div", { class: "loading" }, "Loading…"));
    try {
      if (active === 0) {
        const d = await apiGet("/api/command-graph");
        body.replaceChildren(
          el("div", { class: "grid" },
            statMini("Builtins", d.builtins.length),
            statMini("Plugin-like", d.plugin_like.length),
            statMini("Skill-like", d.skill_like.length)),
          panel("Builtins", moduleTable(d.builtins.slice(0, 50))),
          panel("Plugin-like", moduleTable(d.plugin_like.slice(0, 50))),
          panel("Skill-like", moduleTable(d.skill_like.slice(0, 50))));
      } else if (active === 1) {
        const simple = el("input", { type: "checkbox" });
        const noMcp = el("input", { type: "checkbox" });
        const reloadBtn = el("button", { class: "btn secondary" }, "Reassemble");
        const poolBox = el("div", {});
        async function loadPool() {
          poolBox.replaceChildren(el("div", { class: "loading" }, "Loading…"));
          const p = new URLSearchParams();
          if (simple.checked) p.set("simple_mode", "1");
          if (noMcp.checked) p.set("no_mcp", "1");
          const d = await apiGet("/api/tool-pool?" + p.toString());
          poolBox.replaceChildren(
            el("p", { class: "muted", style: "margin-bottom:10px" },
              `${d.tool_count} tools — simple=${d.simple_mode} mcp=${d.include_mcp}`),
            moduleTable(d.tools.slice(0, 80)));
        }
        reloadBtn.addEventListener("click", loadPool);
        body.replaceChildren(panel(null,
          el("div", { class: "checkbox-row", style: "margin-bottom:14px" },
            el("label", {}, simple, "simple mode"),
            el("label", {}, noMcp, "exclude MCP"), reloadBtn), poolBox));
        loadPool();
      } else {
        const d = await apiGet("/api/bootstrap-graph");
        const list = el("div", {});
        d.stages.forEach((s, i) =>
          list.appendChild(el("div", { class: "detail-box" },
            el("div", { class: "k" }, "Stage " + (i + 1)), el("div", { class: "v" }, s))));
        body.replaceChildren(panel("Bootstrap stages", list));
      }
    } catch (e) {
      body.replaceChildren(errorBox(e.message));
    }
  }

  tabs.forEach((t, i) => {
    const b = el("button", { class: "subtab" + (i === 0 ? " active" : "") }, t);
    b.addEventListener("click", () => {
      active = i;
      [...bar.children].forEach((c, j) => c.classList.toggle("active", j === i));
      render();
    });
    bar.appendChild(b);
  });
  root.replaceChildren(bar, body);
  render();
};

function statMini(label, value) {
  return el("div", { class: "stat-card" },
    el("div", { class: "label" }, label),
    el("div", { class: "value" }, String(value)));
}

views.parity = async () => {
  root.replaceChildren(el("div", { class: "loading" }, "Loading…"));
  try {
    const d = await apiGet("/api/parity-audit");
    const ratio = (label, pair) =>
      el("div", { class: "stat-card" },
        el("div", { class: "label" }, label),
        el("div", { class: "value" }, pair[0] + " / " + pair[1]));
    root.replaceChildren(
      el("div", { class: "grid" },
        ratio("Root files", d.root_file_coverage),
        ratio("Directories", d.directory_coverage),
        ratio("Total files", d.total_file_ratio),
        ratio("Commands", d.command_entry_ratio),
        ratio("Tools", d.tool_entry_ratio)),
      panel("Audit report", el("pre", { class: "md" }, d.markdown)));
  } catch (e) {
    root.replaceChildren(errorBox(e.message));
  }
};

views.setup = async () => {
  root.replaceChildren(el("div", { class: "loading" }, "Loading…"));
  try {
    const [setup, sysinit] = await Promise.all([
      apiGet("/api/setup-report"), apiGet("/api/system-init"),
    ]);
    root.replaceChildren(
      panel("Setup report", el("pre", { class: "md" }, setup.markdown)),
      panel("System init message", el("pre", { class: "md" }, sysinit.markdown)));
  } catch (e) {
    root.replaceChildren(errorBox(e.message));
  }
};

views.modes = async () => {
  const modes = ["remote", "ssh", "teleport", "direct-connect", "deep-link"];
  const select = el("select", {});
  modes.forEach((m) => select.appendChild(el("option", { value: m }, m)));
  const target = el("input", { type: "text", placeholder: "target, e.g. workspace", value: "workspace" });
  const out = el("div", {});
  const btn = el("button", { class: "btn" }, "Run mode");

  async function run() {
    setBusy(btn, true);
    out.replaceChildren(el("div", { class: "loading" }, "Running…"));
    try {
      const d = await apiGet(`/api/mode/${encodeURIComponent(select.value)}?target=` + encodeURIComponent(target.value));
      const kv = el("div", { class: "kv" });
      Object.entries(d).forEach(([k, v]) => {
        kv.appendChild(el("div", { class: "k" }, k));
        kv.appendChild(el("div", { class: "v" }, String(v)));
      });
      out.replaceChildren(panel("Result", kv));
    } catch (e) {
      out.replaceChildren(errorBox(e.message));
    } finally { setBusy(btn, false); }
  }
  btn.addEventListener("click", run);
  root.replaceChildren(panel(null,
    el("div", { class: "form-row" },
      el("div", { class: "field" }, el("label", {}, "Mode"), select),
      el("div", { class: "field grow" }, el("label", {}, "Target"), target), btn)), out);
};

views.sessions = async () => {
  const flushPrompt = el("input", { type: "text", placeholder: "prompt to persist…" });
  const flushOut = el("div", {});
  const flushBtn = el("button", { class: "btn" }, "Flush transcript");

  const loadId = el("input", { type: "text", placeholder: "session id" });
  const loadOut = el("div", {});
  const loadBtn = el("button", { class: "btn secondary" }, "Load session");

  flushBtn.addEventListener("click", async () => {
    setBusy(flushBtn, true);
    try {
      const d = await apiPost("/api/flush-transcript", { prompt: flushPrompt.value });
      loadId.value = d.session_id;
      flushOut.replaceChildren(el("pre", { class: "md" },
        `session_id=${d.session_id}\npath=${d.path}\nflushed=${d.flushed}\ntranscript_size=${d.transcript_size}`));
    } catch (e) {
      flushOut.replaceChildren(errorBox(e.message));
    } finally { setBusy(flushBtn, false); }
  });

  loadBtn.addEventListener("click", async () => {
    setBusy(loadBtn, true);
    try {
      const d = await apiGet("/api/session/" + encodeURIComponent(loadId.value.trim()));
      loadOut.replaceChildren(panel("Session " + d.session_id,
        el("div", { class: "kv" },
          el("div", { class: "k" }, "Messages"), el("div", { class: "v" }, String(d.message_count)),
          el("div", { class: "k" }, "Input tokens"), el("div", { class: "v" }, String(d.input_tokens)),
          el("div", { class: "k" }, "Output tokens"), el("div", { class: "v" }, String(d.output_tokens))),
        el("h3", {}, "Messages"),
        el("pre", { class: "md" }, d.messages.join("\n") || "(none)")));
    } catch (e) {
      loadOut.replaceChildren(errorBox(e.message));
    } finally { setBusy(loadBtn, false); }
  });

  root.replaceChildren(
    panel("Persist a transcript",
      el("div", { class: "form-row" },
        el("div", { class: "field grow" }, el("label", {}, "Prompt"), flushPrompt), flushBtn),
      flushOut),
    panel("Load a stored session",
      el("div", { class: "form-row" },
        el("div", { class: "field grow" }, el("label", {}, "Session id"), loadId), loadBtn),
      loadOut));
};

// --- navigation + bootstrap ------------------------------------------------

function navigate(view) {
  const meta = VIEW_META[view] || ["", ""];
  titleEl.textContent = meta[0];
  subtitleEl.textContent = meta[1];
  document.querySelectorAll(".nav-item").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === view));
  if (location.hash !== "#" + view) location.hash = view;
  (views[view] || views.overview)();
}

document.getElementById("nav").addEventListener("click", (e) => {
  const btn = e.target.closest(".nav-item");
  if (btn) navigate(btn.dataset.view);
});

window.addEventListener("hashchange", () => {
  const v = location.hash.replace("#", "");
  if (views[v]) navigate(v);
});

async function checkHealth() {
  const dot = document.getElementById("health-dot");
  const text = document.getElementById("health-text");
  try {
    const ov = await apiGet("/api/overview");
    dot.className = "dot ok";
    text.textContent = `${ov.command_count} cmds · ${ov.tool_count} tools`;
  } catch {
    dot.className = "dot bad";
    text.textContent = "API unreachable";
  }
}

const initial = location.hash.replace("#", "");
navigate(views[initial] ? initial : "overview");
checkHealth();
