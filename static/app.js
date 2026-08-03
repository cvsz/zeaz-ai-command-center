"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  info: null,
  providers: [],
  provider: null,
  rootSchema: null,
  currentSchema: null,
  schemaCache: new Map(),
  commandPath: [],
  activeJob: null,
  outputOffset: 0,
  pollTimer: null,
  elapsedTimer: null,
  startedAt: null,
};

function token() {
  const query = new URLSearchParams(location.search).get("token");
  if (query) {
    sessionStorage.setItem("panel_token", query);
    history.replaceState({}, "", location.pathname);
  }
  return sessionStorage.getItem("panel_token") || "";
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const auth = token();
  if (auth) headers.Authorization = `Bearer ${auth}`;
  const response = await fetch(path, { ...options, headers });
  let data = {};
  try { data = await response.json(); } catch { /* no-op */ }
  if (response.status === 401 && !auth) {
    const entered = prompt("Enter PANEL_TOKEN");
    if (entered) {
      sessionStorage.setItem("panel_token", entered);
      return api(path, options);
    }
  }
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function toast(message, error = false) {
  const node = $("toast");
  node.textContent = message;
  node.className = `toast show${error ? " error" : ""}`;
  clearTimeout(node._timer);
  node._timer = setTimeout(() => node.className = "toast", 3200);
}

function quoteArg(value) {
  const text = String(value);
  if (/^[A-Za-z0-9_@%+=:,./-]+$/.test(text)) return text;
  return `'${text.replaceAll("'", `'"'"'`)}'`;
}

function lines(id) {
  return $(id).value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
}

function parseEnvironment() {
  const output = {};
  for (const line of lines("environment")) {
    const index = line.indexOf("=");
    if (index < 1) throw new Error(`Environment override must use KEY=value: ${line}`);
    output[line.slice(0, index).trim()] = line.slice(index + 1);
  }
  return output;
}

async function boot() {
  bindEvents();
  try {
    const [info] = await Promise.all([api("/api/info"), loadProviders(), loadJobs()]);
    state.info = info;
    $("cwd").value = info.cwd;
    $("allowedRoots").textContent = `Allowed roots: ${info.allowed_roots.join(", ")}`;
  } catch (error) {
    toast(error.message, true);
  }
}

function bindEvents() {
  $("addProvider").addEventListener("click", () => $("providerDialog").showModal());
  $("refreshProviders").addEventListener("click", loadProviders);
  $("refreshSchema").addEventListener("click", () => state.provider && selectProvider(state.provider.id, true));
  $("exportSchema").addEventListener("click", exportSchema);
  $("runButton").addEventListener("click", runCommand);
  $("stopButton").addEventListener("click", stopJob);
  $("clearTerminal").addEventListener("click", () => $("terminal").textContent = "");
  $("copyCommand").addEventListener("click", async () => {
    await navigator.clipboard.writeText($("commandPreview").textContent);
    toast("Command copied");
  });
  $("refreshJobs").addEventListener("click", loadJobs);
  $("probeButton").addEventListener("click", () => inspectProvider(false));
  $("saveProvider").addEventListener("click", () => inspectProvider(true));
  ["cwd", "positionals", "prompt", "rawArgs", "environment", "confirmation"].forEach(id => {
    $(id).addEventListener("input", updatePreview);
  });
}

async function loadProviders() {
  try {
    const data = await api("/api/providers");
    state.providers = data.providers;
    renderProviders();
    if (!state.provider && state.providers.length) await selectProvider(state.providers[0].id);
    if (!state.providers.length) {
      $("providerStatus").textContent = "No AI CLI detected";
      $("providerVersion").textContent = "Add an installed executable";
    }
  } catch (error) {
    toast(error.message, true);
  }
}

function renderProviders() {
  $("providerList").innerHTML = state.providers.map(provider => `
    <button class="provider-item${state.provider?.id === provider.id ? " active" : ""}" data-provider="${escapeHtml(provider.id)}">
      <span class="provider-icon">${escapeHtml(provider.name.slice(0, 2).toUpperCase())}</span>
      <span><strong>${escapeHtml(provider.name)}</strong><small>${escapeHtml(provider.executable)}</small></span>
      ${provider.custom ? '<em title="Custom provider">●</em>' : ""}
    </button>`).join("");
  document.querySelectorAll("[data-provider]").forEach(button => {
    button.addEventListener("click", () => selectProvider(button.dataset.provider));
  });
}

async function selectProvider(providerId, refresh = false) {
  const provider = state.providers.find(item => item.id === providerId);
  if (!provider) return;
  state.provider = provider;
  state.commandPath = [];
  state.schemaCache.clear();
  renderProviders();
  $("providerStatus").textContent = `Loading ${provider.name}…`;
  $("providerVersion").textContent = provider.executable;
  $("providerDot").className = "status-dot working";
  $("runButton").disabled = true;
  try {
    const suffix = refresh ? "?refresh=1" : "";
    const [schema, info] = await Promise.all([
      api(`/api/providers/${encodeURIComponent(provider.id)}/schema${suffix}`),
      api(`/api/providers/${encodeURIComponent(provider.id)}/info`),
    ]);
    state.rootSchema = schema;
    state.currentSchema = schema;
    state.schemaCache.set("", schema);
    $("providerStatus").textContent = provider.name;
    $("providerVersion").textContent = info.version || info.resolved;
    $("providerDot").className = "status-dot online";
    $("pageTitle").textContent = `${provider.name} Command Builder`;
    $("pageSubtitle").textContent = schema.description || `Generated from ${provider.executable} --help`;
    $("runButton").disabled = false;
    await renderCommandPath();
    renderSchemas();
    toast(`Loaded ${schema.commands.length} commands and ${schema.options.length} options`);
  } catch (error) {
    $("providerStatus").textContent = `${provider.name} unavailable`;
    $("providerVersion").textContent = error.message;
    $("providerDot").className = "status-dot offline";
    toast(error.message, true);
  }
}

async function schemaFor(path) {
  const key = path.join("\u0000");
  if (state.schemaCache.has(key)) return state.schemaCache.get(key);
  const query = path.map(item => `command=${encodeURIComponent(item)}`).join("&");
  const schema = await api(`/api/providers/${encodeURIComponent(state.provider.id)}/schema?${query}`);
  state.schemaCache.set(key, schema);
  return schema;
}

async function renderCommandPath() {
  const container = $("commandPath");
  container.innerHTML = "";
  if (!state.rootSchema) return;
  let schema = state.rootSchema;
  const selectedPrefix = [];
  let depth = 0;

  while (schema.commands?.length && depth < 6) {
    const wrapper = document.createElement("label");
    wrapper.className = "field path-field";
    const caption = document.createElement("span");
    caption.textContent = depth === 0 ? "Command" : `Subcommand ${depth}`;
    const select = document.createElement("select");
    select.innerHTML = `<option value="">${depth === 0 ? "Interactive / root" : "No deeper subcommand"}</option>` +
      schema.commands.map(command => `<option value="${escapeHtml(command.name)}">${escapeHtml(command.name)} — ${escapeHtml(command.description)}</option>`).join("");
    const current = state.commandPath[depth] || "";
    select.value = current;
    const prefix = [...selectedPrefix];
    select.addEventListener("change", async () => {
      state.commandPath = select.value ? [...prefix, select.value] : prefix;
      state.currentSchema = await schemaFor(state.commandPath);
      await renderCommandPath();
      renderSchemas();
    });
    wrapper.append(caption, select);
    container.append(wrapper);
    if (!current) break;
    selectedPrefix.push(current);
    schema = await schemaFor(selectedPrefix);
    depth += 1;
  }
  state.currentSchema = await schemaFor(state.commandPath);
  if (!container.children.length) container.innerHTML = '<p class="muted">This provider exposes options without named subcommands.</p>';
}

function renderSchemas() {
  const root = state.rootSchema;
  const current = state.currentSchema || root;
  if (!root) return;
  $("schemaPreview").textContent = JSON.stringify(current, null, 2);
  if (current.usage || root.usage) {
    $("usageBox").classList.remove("hidden");
    $("usageText").textContent = current.usage || root.usage;
  } else $("usageBox").classList.add("hidden");

  renderOptions("globalOptions", root.options || [], "global");
  $("globalSection").classList.toggle("hidden", !root.options?.length);
  $("globalCount").textContent = `${root.options?.length || 0} detected`;

  const rootFlags = new Set((root.options || []).flatMap(item => item.flags || [item.flag]));
  const commandOptions = state.commandPath.length
    ? (current.options || []).filter(item => !(item.flags || [item.flag]).some(flag => rootFlags.has(flag)))
    : [];
  renderOptions("commandOptions", commandOptions, "command");
  $("commandSection").classList.toggle("hidden", !state.commandPath.length || !commandOptions.length);
  $("commandCount").textContent = `${commandOptions.length} detected`;
  $("commandOptionsTitle").textContent = state.commandPath.length ? state.commandPath.join(" ") : "Command settings";
  updatePreview();
}

function renderOptions(containerId, options, scope) {
  const container = $(containerId);
  container.innerHTML = "";
  for (const option of options) {
    const label = document.createElement("label");
    label.className = `generated-option risk-${option.risk || "normal"}`;
    const head = document.createElement("div");
    head.className = "option-head";
    head.innerHTML = `<code>${escapeHtml(option.spec)}</code>${option.risk !== "normal" ? `<span class="mini-risk">${escapeHtml(option.risk)}</span>` : ""}`;
    const description = document.createElement("small");
    description.textContent = option.description || "No description detected.";
    let control;
    if (!option.takes_value) {
      control = document.createElement("input");
      control.type = "checkbox";
      label.classList.add("boolean-option");
    } else if (option.choices?.length) {
      control = document.createElement("select");
      control.innerHTML = '<option value="">Not set</option>' + option.choices.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
    } else if (option.repeatable || option.multi_value) {
      control = document.createElement("textarea");
      control.rows = 2;
      control.placeholder = `One ${option.value_name || "value"} per line`;
    } else {
      control = document.createElement("input");
      control.placeholder = option.value_name || "value";
    }
    control.classList.add("option-control");
    control.dataset.flag = option.flag;
    control.dataset.scope = scope;
    control.dataset.takesValue = option.takes_value ? "1" : "0";
    control.dataset.repeatable = option.repeatable || option.multi_value ? "1" : "0";
    control.dataset.risk = option.risk || "normal";
    control.addEventListener("input", updatePreview);
    control.addEventListener("change", updatePreview);
    if (control.type === "checkbox") {
      const row = document.createElement("div");
      row.className = "boolean-row";
      row.append(control, head);
      label.append(row, description);
    } else {
      label.append(head, control, description);
    }
    container.append(label);
  }
}

function collectOptions(scope) {
  const result = {};
  document.querySelectorAll(`.option-control[data-scope="${scope}"]`).forEach(control => {
    const flag = control.dataset.flag;
    if (control.dataset.takesValue === "0") {
      if (control.checked) result[flag] = true;
    } else if (control.dataset.repeatable === "1") {
      const values = control.value.split(/\r?\n/).map(item => item.trim()).filter(Boolean);
      if (values.length) result[flag] = values;
    } else if (control.value !== "") result[flag] = control.value;
  });
  return result;
}

function optionArgs(scope) {
  const args = [];
  const schema = scope === "global" ? state.rootSchema : state.currentSchema;
  const selected = collectOptions(scope);
  const index = new Map((schema?.options || []).map(item => [item.flag, item]));
  for (const [flag, raw] of Object.entries(selected)) {
    const option = index.get(flag);
    if (!option) continue;
    if (!option.takes_value) args.push(flag);
    else if (Array.isArray(raw)) {
      if (option.multi_value) args.push(flag, ...raw);
      else raw.forEach(value => args.push(flag, value));
    } else args.push(flag, raw);
  }
  return args;
}

function currentPreviewArgv() {
  if (!state.provider) return [];
  return [
    state.provider.executable,
    ...optionArgs("global"),
    ...state.commandPath,
    ...optionArgs("command"),
    ...lines("positionals"),
    ...lines("rawArgs"),
    ...($("prompt").value ? [$("prompt").value] : []),
  ];
}

function riskFromUi() {
  const risks = [...document.querySelectorAll(".option-control")]
    .filter(control => control.type === "checkbox" ? control.checked : Boolean(control.value))
    .map(control => control.dataset.risk);
  const command = state.currentSchema?.commands?.find(item => state.commandPath.includes(item.name));
  if (command?.risk) risks.push(command.risk);
  const argv = currentPreviewArgv().join(" ").toLowerCase();
  if (risks.includes("dangerous") || /danger|no-sandbox|unsafe|full-access|bypass/.test(argv)) return "dangerous";
  if (risks.includes("destructive") || /\b(delete|remove|logout|uninstall|reset|purge|destroy|apply|update|force)\b/.test(argv)) return "destructive";
  return "normal";
}

function updatePreview() {
  const argv = currentPreviewArgv();
  $("commandPreview").textContent = argv.length ? argv.map(quoteArg).join(" ") : "Select a provider…";
  const risk = riskFromUi();
  $("riskBadge").textContent = risk[0].toUpperCase() + risk.slice(1);
  $("riskBadge").className = `badge ${risk}`;
}

function buildPayload() {
  if (!state.provider) throw new Error("Select a provider");
  return {
    provider_id: state.provider.id,
    cwd: $("cwd").value,
    command_path: state.commandPath,
    global_options: collectOptions("global"),
    command_options: collectOptions("command"),
    positionals: lines("positionals"),
    raw_args: lines("rawArgs"),
    prompt: $("prompt").value,
    environment: parseEnvironment(),
    confirmation: $("confirmation").value,
  };
}

async function runCommand() {
  if (state.activeJob) return toast("A job is already running", true);
  try {
    const payload = buildPayload();
    const job = await api("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
    state.activeJob = job.id;
    state.outputOffset = 0;
    state.startedAt = Date.now();
    $("terminal").textContent = `$ ${job.argv.map(quoteArg).join(" ")}\n\n`;
    $("jobId").textContent = `Job ${job.id} · ${job.provider_id}`;
    $("runButton").disabled = true;
    $("stopButton").disabled = false;
    setStatus("queued");
    state.elapsedTimer = setInterval(updateElapsed, 1000);
    pollJob();
  } catch (error) {
    toast(error.message, true);
  }
}

function setStatus(status) {
  $("jobStatus").textContent = status[0].toUpperCase() + status.slice(1);
  $("jobStatus").className = `badge ${status}`;
}

function updateElapsed() {
  const seconds = Math.floor((Date.now() - state.startedAt) / 1000);
  $("elapsed").textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

async function pollJob() {
  if (!state.activeJob) return;
  try {
    const job = await api(`/api/jobs/${state.activeJob}?offset=${state.outputOffset}`);
    if (job.output_truncated) $("terminal").textContent += "\n[command-center] Earlier output was truncated.\n";
    if (job.output) {
      $("terminal").textContent += job.output;
      $("terminal").scrollTop = $("terminal").scrollHeight;
    }
    state.outputOffset = job.next_offset;
    setStatus(job.status);
    if (["queued", "running"].includes(job.status)) {
      state.pollTimer = setTimeout(pollJob, 550);
      return;
    }
    if (job.error) $("terminal").textContent += `\n[command-center] ${job.error}\n`;
    $("terminal").textContent += `\n[command-center] Finished: status=${job.status}, exit=${job.return_code ?? "n/a"}\n`;
    finishActiveJob();
    loadJobs();
  } catch (error) {
    toast(error.message, true);
    state.pollTimer = setTimeout(pollJob, 1500);
  }
}

function finishActiveJob() {
  clearTimeout(state.pollTimer);
  clearInterval(state.elapsedTimer);
  state.activeJob = null;
  $("runButton").disabled = !state.provider;
  $("stopButton").disabled = true;
}

async function stopJob() {
  if (!state.activeJob) return;
  try {
    await api(`/api/jobs/${state.activeJob}/stop`, { method: "POST" });
    toast("Stop signal sent");
  } catch (error) { toast(error.message, true); }
}

async function loadJobs() {
  try {
    const data = await api("/api/jobs");
    if (!data.jobs.length) {
      $("jobHistory").innerHTML = '<p class="muted">No jobs yet.</p>';
      return;
    }
    $("jobHistory").innerHTML = data.jobs.map(job => `
      <button class="job-row" data-job-id="${job.id}">
        <span class="badge ${job.status}">${escapeHtml(job.status)}</span>
        <strong>${escapeHtml(job.provider_id)}</strong>
        <code>${escapeHtml(job.argv.map(quoteArg).join(" "))}</code>
        <span>${new Date(job.created_at * 1000).toLocaleString()}</span>
      </button>`).join("");
    document.querySelectorAll("[data-job-id]").forEach(row => row.addEventListener("click", () => openHistoricalJob(row.dataset.jobId)));
  } catch (error) { toast(error.message, true); }
}

async function openHistoricalJob(id) {
  try {
    const job = await api(`/api/jobs/${id}?offset=0`);
    $("terminal").textContent = `$ ${job.argv.map(quoteArg).join(" ")}\n\n${job.output || ""}\n[command-center] status=${job.status}, exit=${job.return_code ?? "n/a"}\n`;
    $("jobId").textContent = `Historical job ${job.id}`;
    setStatus(job.status);
  } catch (error) { toast(error.message, true); }
}

async function inspectProvider(save) {
  const payload = {
    executable: $("probeExecutable").value,
    name: $("probeName").value,
    help_args: $("probeHelpArgs").value,
    version_args: $("probeVersionArgs").value,
  };
  $("probeResult").innerHTML = '<span class="muted">Inspecting executable…</span>';
  try {
    const result = await api(save ? "/api/providers" : "/api/providers/probe", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    $("probeResult").innerHTML = `
      <strong>${escapeHtml(result.name)}</strong>
      <span>${escapeHtml(result.version || result.resolved)}</span>
      <div><b>${result.schema.commands.length}</b> commands · <b>${result.schema.options.length}</b> options · parser ${escapeHtml(result.schema.parser)}</div>`;
    if (save) {
      await loadProviders();
      $("providerDialog").close();
      await selectProvider(result.id);
      toast(`${result.name} saved`);
    }
  } catch (error) {
    $("probeResult").innerHTML = `<span class="error-text">${escapeHtml(error.message)}</span>`;
  }
}

function exportSchema() {
  if (!state.currentSchema) return toast("No schema loaded", true);
  const bundle = {
    provider: state.provider,
    root_schema: state.rootSchema,
    command_path: state.commandPath,
    current_schema: state.currentSchema,
    exported_at: new Date().toISOString(),
  };
  const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${state.provider.id}-${state.commandPath.join("-") || "root"}-schema.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

document.addEventListener("DOMContentLoaded", boot);
