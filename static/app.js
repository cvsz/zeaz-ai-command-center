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
  streamController: null,
  elapsedTimer: null,
  startedAt: null,
};

function token() {
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
    const [info] = await Promise.all([api("/api/info"), loadProviders(), loadJobs(), loadPresets(), loadWorkflows(), loadMcpServers(), loadWorktrees()]);
    state.info = info;
    $("cwd").value = info.cwd;
    $("allowedRoots").textContent = `Allowed roots: ${info.allowed_roots.join(", ")}`;
    $("runtimeInfo").textContent = `v${info.version} · ${info.parser} · ${info.environment_policy}`;
  } catch (error) {
    toast(error.message, true);
  }
}

function bindEvents() {
  $("addProvider").addEventListener("click", () => $("providerDialog").showModal());
  $("refreshProviders").addEventListener("click", loadProviders);
  $("refreshSchema").addEventListener("click", () => state.provider && selectProvider(state.provider.id, true));
  $("savePresetBtn").addEventListener("click", saveCurrentPreset);
  $("exportSchema").addEventListener("click", exportSchema);
  $("runButton").addEventListener("click", runCommand);
  $("stopButton").addEventListener("click", stopJob);
  $("clearTerminal").addEventListener("click", () => $("terminal").textContent = "");
  $("copyCommand").addEventListener("click", async () => {
    await navigator.clipboard.writeText($("commandPreview").textContent);
    toast("Command copied");
  });
  $("refreshJobs").addEventListener("click", loadJobs);
  $("refreshPresets").addEventListener("click", loadPresets);
  $("loadFilesBtn").addEventListener("click", loadWorkspaceFiles);
  $("loadDiffBtn").addEventListener("click", loadGitDiff);
  $("saveOverlayBtn").addEventListener("click", saveSchemaOverlay);
  $("addWfBtn").addEventListener("click", createWorkflow);
  $("addMcpBtn").addEventListener("click", createMcpServer);
  $("addWtBtn").addEventListener("click", createWorktree);
  $("createPrBtn").addEventListener("click", createPullRequest);
  $("probeButton").addEventListener("click", () => inspectProvider(false));
  $("saveProvider").addEventListener("click", () => inspectProvider(true));
  $("langSelect").addEventListener("change", (e) => applyI18n(e.target.value));
  ["cwd", "positionals", "prompt", "rawArgs", "environment", "confirmation", "timeoutSeconds"].forEach(id => {
    $(id).addEventListener("input", updatePreview);
  });
}

async function applyI18n(lang) {
  try {
    const res = await fetch("/i18n.json");
    const dict = await res.json();
    const translations = dict[lang] || dict.en;
    if (translations.select_provider && !state.provider) $("pageTitle").textContent = translations.select_provider;
    if (translations.rescan_clis) $("refreshProviders").textContent = translations.rescan_clis;
    if (translations.run_command) $("runButton").textContent = translations.run_command;
    if (translations.save_preset) $("savePresetBtn").textContent = translations.save_preset;
    if (translations.export_schema) $("exportSchema").textContent = translations.export_schema;
  } catch (err) { console.error(err); }
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
    if (info.fingerprint_changed) toast("Provider binary changed since registration; review its fingerprint", true);
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
    if (option.default !== null && option.default !== undefined) description.textContent += ` Default: ${option.default}.`;
    if (option.environment) description.textContent += ` Env: ${option.environment}.`;
    if (option.deprecated) label.classList.add("deprecated-option");
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
    timeout_seconds: $("timeoutSeconds").value ? Number($("timeoutSeconds").value) : undefined,
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
    streamJob(job.id);
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

async function streamJob(jobId) {
  state.streamController?.abort();
  const controller = new AbortController();
  state.streamController = controller;
  try {
    const headers = { Accept: "text/event-stream" };
    const auth = token();
    if (auth) headers.Authorization = `Bearer ${auth}`;
    const response = await fetch(`/api/jobs/${jobId}/events?offset=${state.outputOffset}`, { headers, signal: controller.signal });
    if (!response.ok) {
      let message = `Stream failed (${response.status})`;
      try { message = (await response.json()).error || message; } catch { /* no-op */ }
      throw new Error(message);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const dataLines = block.split("\n").filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart());
        if (!dataLines.length) continue;
        handleJobSnapshot(JSON.parse(dataLines.join("\n")));
      }
    }
  } catch (error) {
    if (error.name !== "AbortError") {
      toast(error.message, true);
      if (state.activeJob === jobId) {
        try { handleJobSnapshot(await api(`/api/jobs/${jobId}?offset=${state.outputOffset}`)); } catch { /* preserve current output */ }
      }
    }
  }
}

function handleJobSnapshot(job) {
  if (job.output_truncated) $("terminal").textContent += "\n[command-center] Earlier output was truncated.\n";
  if (job.output) {
    $("terminal").textContent += job.output;
    $("terminal").scrollTop = $("terminal").scrollHeight;
  }
  state.outputOffset = job.next_offset;
  setStatus(job.status);
  if (["queued", "running", "stopping"].includes(job.status)) return;
  if (job.error) $("terminal").textContent += `\n[command-center] ${job.error}\n`;
  $("terminal").textContent += `\n[command-center] Finished: status=${job.status}, exit=${job.return_code ?? "n/a"}\n`;
  finishActiveJob();
  loadJobs();
}

function finishActiveJob() {
  state.streamController?.abort();
  state.streamController = null;
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
      <div class="job-row-wrap">
        <button class="job-row" data-job-id="${job.id}">
          <span class="badge ${job.status}">${escapeHtml(job.status)}</span>
          <strong>${escapeHtml(job.provider_id)}</strong>
          <code>${escapeHtml(job.argv.map(quoteArg).join(" "))}</code>
          <span>${new Date(job.created_at * 1000).toLocaleString()}</span>
        </button>
        ${["succeeded", "failed", "stopped", "timed_out", "orphaned"].includes(job.status) ? `<button class="icon-button delete-job" data-delete-job="${job.id}" title="Delete job" aria-label="Delete job ${job.id}">×</button>` : ""}
      </div>`).join("");
    document.querySelectorAll("[data-job-id]").forEach(row => row.addEventListener("click", () => openHistoricalJob(row.dataset.jobId)));
    document.querySelectorAll("[data-delete-job]").forEach(button => button.addEventListener("click", () => deleteJob(button.dataset.deleteJob)));
  } catch (error) { toast(error.message, true); }
}

async function openHistoricalJob(id) {
  try {
    const job = await api(`/api/jobs/${id}?offset=0`);
    $("terminal").textContent = `$ ${job.argv.map(quoteArg).join(" ")}\n\n${job.output || ""}\n[command-center] status=${job.status}, exit=${job.return_code ?? "n/a"}\n`;
    $("jobId").innerHTML = `Historical job ${job.id} · <a href="#" id="downloadLogBtn" style="color:var(--accent,#38bdf8);text-decoration:underline;">Download Log</a>`;
    const logBtn = $("downloadLogBtn");
    if (logBtn) {
      logBtn.onclick = (e) => {
        e.preventDefault();
        const blob = new Blob([$("terminal").textContent], { type: "text/plain" });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `job-${job.id}.log`;
        anchor.click();
        URL.revokeObjectURL(url);
      };
    }
    setStatus(job.status);
  } catch (error) { toast(error.message, true); }
}

async function deleteJob(id) {
  if (!confirm(`Delete job ${id} from history?`)) return;
  try {
    await api(`/api/jobs/${id}`, { method: "DELETE" });
    await loadJobs();
    toast(`Deleted job ${id}`);
  } catch (error) { toast(error.message, true); }
}

async function saveCurrentPreset() {
  if (!state.provider) return toast("Select a provider first", true);
  const name = prompt("Enter preset name:", `${state.provider.name} - ${state.commandPath.join(" ") || "default"}`);
  if (!name) return;
  try {
    const payload = {
      name,
      provider_id: state.provider.id,
      command_path: state.commandPath,
      global_options: collectOptions("global"),
      command_options: collectOptions("command"),
      positionals: lines("positionals"),
      raw_args: lines("rawArgs"),
      prompt: $("prompt").value,
    };
    await api("/api/presets", { method: "POST", body: JSON.stringify(payload) });
    await loadPresets();
    toast(`Preset "${name}" saved`);
  } catch (error) { toast(error.message, true); }
}

async function loadPresets() {
  try {
    const data = await api("/api/presets");
    if (!data.presets.length) {
      $("presetList").innerHTML = '<p class="muted">No presets saved yet.</p>';
      return;
    }
    $("presetList").innerHTML = data.presets.map(preset => `
      <div class="job-row-wrap">
        <button class="job-row" data-preset-id="${preset.id}">
          <span class="badge normal">${escapeHtml(preset.provider_id)}</span>
          <strong>${escapeHtml(preset.name)}</strong>
          <code>${escapeHtml(preset.command_path.join(" ") || "root")}</code>
          <span>${new Date(preset.created_at * 1000).toLocaleDateString()}</span>
        </button>
        <button class="icon-button delete-job" data-delete-preset="${preset.id}" title="Delete preset" aria-label="Delete preset ${preset.id}">×</button>
      </div>`).join("");
    document.querySelectorAll("[data-preset-id]").forEach(row => row.addEventListener("click", () => applyPreset(row.dataset.presetId)));
    document.querySelectorAll("[data-delete-preset]").forEach(button => button.addEventListener("click", () => deletePreset(button.dataset.deletePreset)));
  } catch (error) { toast(error.message, true); }
}

async function applyPreset(id) {
  try {
    const data = await api("/api/presets");
    const preset = data.presets.find(item => item.id === id);
    if (!preset) return;
    if (state.provider?.id !== preset.provider_id) {
      await selectProvider(preset.provider_id);
    }
    state.commandPath = preset.command_path || [];
    await renderCommandPath();
    renderSchemas();
    $("positionals").value = (preset.positionals || []).join("\n");
    $("rawArgs").value = (preset.raw_args || []).join("\n");
    $("prompt").value = preset.prompt || "";
    updatePreview();
    toast(`Applied preset "${preset.name}"`);
  } catch (error) { toast(error.message, true); }
}

async function deletePreset(id) {
  if (!confirm(`Delete preset?`)) return;
  try {
    await api(`/api/presets/${id}`, { method: "DELETE" });
    await loadPresets();
    toast(`Deleted preset`);
  } catch (error) { toast(error.message, true); }
}

async function loadWorkspaceFiles() {
  try {
    const cwd = encodeURIComponent($("cwd").value || "");
    const data = await api(`/api/files?cwd=${cwd}`);
    if (!data.items?.length) {
      $("fileBrowserPreview").textContent = "No files found in workspace.";
      return;
    }
    $("fileBrowserPreview").textContent = data.items.map(item => `${item.is_dir ? "[DIR] " : "      "}${item.name} (${item.size} bytes)`).join("\n");
  } catch (error) {
    $("fileBrowserPreview").textContent = `Error: ${error.message}`;
  }
}

async function loadGitDiff() {
  try {
    const cwd = encodeURIComponent($("cwd").value || "");
    const data = await api(`/api/diff?cwd=${cwd}`);
    $("gitDiffPreview").textContent = data.diff || "No uncommitted git changes detected in workspace.";
  } catch (error) {
    $("gitDiffPreview").textContent = `Error: ${error.message}`;
  }
}

async function saveSchemaOverlay() {
  if (!state.provider) return toast("Select a provider first", true);
  try {
    const text = $("overlayText").value.trim();
    const overlay = text ? JSON.parse(text) : {};
    await api(`/api/providers/${encodeURIComponent(state.provider.id)}/overlay`, {
      method: "POST",
      body: JSON.stringify(overlay),
    });
    await selectProvider(state.provider.id, true);
    toast("Schema correction overlay applied");
  } catch (error) {
    toast(`Invalid overlay JSON: ${error.message}`, true);
  }
}

async function loadWorkflows() {
  try {
    const data = await api("/api/workflows");
    if (!data.workflows?.length) {
      $("workflowList").innerHTML = '<p class="muted">No workflows created yet.</p>';
      return;
    }
    $("workflowList").innerHTML = data.workflows.map(wf => `
      <div class="job-row-wrap">
        <div class="job-row">
          <span class="badge ${wf.status === "active" ? "running" : "neutral"}">${escapeHtml(wf.status)}</span>
          <strong>${escapeHtml(wf.name)}</strong>
          <code>${wf.steps.length} steps configured</code>
        </div>
      </div>`).join("");
  } catch (error) { toast(error.message, true); }
}

async function createWorkflow() {
  const name = prompt("Enter workflow name:", "CI/CD Auto Pipeline");
  if (!name) return;
  try {
    await api("/api/workflows", {
      method: "POST",
      body: JSON.stringify({ name, steps: [{ name: "Lint and Test", command: "pytest" }], status: "active" }),
    });
    await loadWorkflows();
    toast(`Workflow "${name}" created`);
  } catch (error) { toast(error.message, true); }
}

async function loadMcpServers() {
  try {
    const data = await api("/api/mcp");
    if (!data.mcp_servers?.length) {
      $("mcpList").innerHTML = '<p class="muted">No MCP servers registered yet.</p>';
      return;
    }
    $("mcpList").innerHTML = data.mcp_servers.map(srv => `
      <div class="job-row-wrap">
        <div class="job-row">
          <span class="badge running">${escapeHtml(srv.status)}</span>
          <strong>${escapeHtml(srv.name)}</strong>
          <code>${escapeHtml(srv.command)} ${escapeHtml(srv.args.join(" "))}</code>
        </div>
      </div>`).join("");
  } catch (error) { toast(error.message, true); }
}

async function createMcpServer() {
  const name = prompt("Enter MCP Server name:", "Context Tool Server");
  if (!name) return;
  try {
    await api("/api/mcp", {
      method: "POST",
      body: JSON.stringify({ name, command: "npx", args: ["-y", "@modelcontextprotocol/server-memory"], status: "active" }),
    });
    await loadMcpServers();
    toast(`MCP Server "${name}" registered`);
  } catch (error) { toast(error.message, true); }
}

async function loadWorktrees() {
  try {
    const data = await api("/api/worktrees");
    if (!data.worktrees?.length) {
      $("worktreeList").innerHTML = '<p class="muted">No Git worktrees active.</p>';
      return;
    }
    $("worktreeList").innerHTML = data.worktrees.map(wt => `
      <div class="job-row-wrap">
        <div class="job-row">
          <span class="badge ${wt.status === "active" ? "running" : "neutral"}">${escapeHtml(wt.status)}</span>
          <strong>${escapeHtml(wt.branch)}</strong>
          <code>${escapeHtml(wt.path)}</code>
        </div>
      </div>`).join("");
  } catch (error) { toast(error.message, true); }
}

async function createWorktree() {
  const branch = prompt("Enter branch for worktree:", `feature/task-${Date.now().toString(36)}`);
  if (!branch) return;
  try {
    const res = await api("/api/worktrees", {
      method: "POST",
      body: JSON.stringify({ branch }),
    });
    await loadWorktrees();
    toast(`Created worktree at "${res.path}"`);
  } catch (error) { toast(error.message, true); }
}

async function createPullRequest() {
  const title = prompt("Enter PR Title:", "Automated AI Update v3.0");
  if (!title) return;
  try {
    const res = await api("/api/github/pulls", {
      method: "POST",
      body: JSON.stringify({ title, body: "Generated by ZEAZ AI Command Center v3.0 platform workflow" }),
    });
    if (res.ok) {
      toast("Pull Request created successfully");
    } else {
      toast(`PR creation output: ${res.output.slice(0, 100)}`, true);
    }
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
