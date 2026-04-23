  // ---- Status polling ----
  async function updateStatus() {
    try {
      const { ddb_connected, foundry_clients } = await fetch("/api/status").then(r => r.json());
      const ddb = document.getElementById("pill-ddb");
      ddb.textContent = `DDB: ${ddb_connected ? "Connected" : "Disconnected"}`;
      ddb.className = `pill ${ddb_connected ? "ok" : "err"}`;
      const fc = document.getElementById("pill-foundry");
      fc.textContent = `Foundry: ${foundry_clients} client${foundry_clients !== 1 ? "s" : ""}`;
      fc.className = `pill ${foundry_clients > 0 ? "ok" : "dim"}`;
    } catch {}
  }
  setInterval(updateStatus, 2000);
  updateStatus();

  // ---- Logs ----
  const logOutput = document.getElementById("log-output");
  let autoScroll = true;
  logOutput.addEventListener("scroll", () => {
    autoScroll = logOutput.scrollHeight - logOutput.scrollTop - logOutput.clientHeight < 40;
  });

  function appendLog(e) {
    if (e.level === "ddb" && e.roll_summary) return; // shown in rolls panel instead
    const div = document.createElement("div");
    div.className = "log-entry";
    div.innerHTML =
      `<span class="log-ts">${e.ts}</span>` +
      `<span class="log-lvl ${e.level}">${e.level.toUpperCase()}</span>` +
      `<span class="log-msg">${esc(e.msg)}</span>`;
    logOutput.appendChild(div);
    if (autoScroll) logOutput.scrollTop = logOutput.scrollHeight;
  }

  async function clearLogs() {
    await fetch("/api/logs", { method: "DELETE" });
    logOutput.innerHTML = "";
  }

  async function clearRolls() {
    await fetch("/api/rolls", { method: "DELETE" });
    rolls = [];
    activeRollId = null;
    renderRolls();
    toast("Roll history cleared.");
  }
  function esc(s) { return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
  function now() { return new Date().toLocaleTimeString("de-DE"); }

  const evtSource = new EventSource("/api/logs/stream");
  evtSource.onmessage = e => {
    const data = JSON.parse(e.data);
    appendLog(data);
    if (data.level === "ddb" && data.roll_summary) {
      prependRoll(data.roll_summary);
    }
  };
  evtSource.onerror = () => appendLog({ ts: now(), level: "warn", msg: "SSE reconnecting..." });

  // ---- Rolls list ----
  let rolls = [];
  let activeRollId = null;

  async function loadRolls() {
    rolls = await fetch("/api/rolls").then(r => r.json());
    renderRolls();
  }

  function prependRoll(summary) {
    rolls.unshift(summary);
    if (rolls.length > 100) rolls.pop();
    renderRolls();
  }

  function rollTypeClass(rt) {
    const t = (rt || "").toLowerCase();
    if (t === "to hit" || t === "attack") return "attack";
    if (t === "damage") return "damage";
    if (t === "save") return "save";
    if (t === "check") return "check";
    if (t === "initiative") return "initiative";
    return "other";
  }

  // ---- Tab switching ----
  let _activeTab = "dashboard";
  function switchTab(tab) {
    _activeTab = tab;
    document.getElementById("view-dashboard").classList.toggle("active", tab === "dashboard");
    document.getElementById("view-stats").classList.toggle("active",     tab === "stats");
    document.getElementById("view-config").classList.toggle("active",    tab === "config");
    document.getElementById("tab-dashboard").classList.toggle("active",  tab === "dashboard");
    document.getElementById("tab-stats").classList.toggle("active",      tab === "stats");
    document.getElementById("tab-config").classList.toggle("active",     tab === "config");
    if (tab === "stats") renderStats();
  }

  // ---- Charts ----
  const _charts = {};
  const CHART_DEFAULTS = {
    responsive: true,
    plugins: { legend: { labels: { color: "#8b949e", font: { size: 11 } } } },
  };
  Chart.defaults.color = "#8b949e";

  function upsertChart(id, type, data, options = {}) {
    if (_charts[id]) _charts[id].destroy();
    _charts[id] = new Chart(document.getElementById(id), {
      type, data,
      options: { ...CHART_DEFAULTS, ...options },
    });
  }

  function renderStats() {
    if (!rolls.length) return;

    // Aggregate
    const chars = {};
    const typeCounts = {};
    const dist = Array(20).fill(0); // index 0 = roll result 1
    let totalNat20 = 0, totalNat1 = 0, allTotals = [];

    for (const r of rolls) {
      const c = r.character || "Unknown";
      if (!chars[c]) chars[c] = { totals: [], nat20: 0, nat1: 0 };
      const s = chars[c];

      const rt = (r.rollType || "other").toLowerCase();
      typeCounts[rt] = (typeCounts[rt] || 0) + 1;

      const d20 = (r.dice || []).filter(d => d.faces === 20);
      if (d20.length) {
        s.totals.push(r.total);
        allTotals.push(r.total);
        d20.forEach(d => { if (d.result >= 1 && d.result <= 20) dist[d.result - 1]++; });
        if (d20.some(d => d.result === 20)) { s.nat20++; totalNat20++; }
        if (d20.some(d => d.result === 1))  { s.nat1++;  totalNat1++;  }
      }
    }

    const avgAll = allTotals.length ? (allTotals.reduce((a,b)=>a+b,0)/allTotals.length).toFixed(1) : "—";
    const charNames = Object.keys(chars);

    // Stat cards
    document.getElementById("s-total").textContent = rolls.length;
    document.getElementById("s-nat20").textContent = totalNat20;
    document.getElementById("s-nat1").textContent  = totalNat1;
    document.getElementById("s-avg").textContent   = avgAll;
    document.getElementById("s-crits").textContent = `${totalNat20} / ${totalNat1}`;

    // Chart: Nat 20 / Nat 1 per character
    upsertChart("chart-nat", "bar", {
      labels: charNames,
      datasets: [
        { label: "Nat 20 🎯", data: charNames.map(n => chars[n].nat20), backgroundColor: "#2ea04388", borderColor: "#56d364", borderWidth: 1 },
        { label: "Nat 1 💀",  data: charNames.map(n => chars[n].nat1),  backgroundColor: "#8b1a1a88", borderColor: "#f85149", borderWidth: 1 },
      ],
    }, { scales: { x: { ticks: { color: "#8b949e" }, grid: { color: "#21262d" } }, y: { ticks: { color: "#8b949e", stepSize: 1 }, grid: { color: "#21262d" }, beginAtZero: true } } });

    // Chart: Roll type donut
    const typeLabels = Object.keys(typeCounts);
    const typeColors = { "to hit": "#388bfd", damage: "#f85149", save: "#e3b341", check: "#a371f7", initiative: "#56d364", heal: "#2ea043", other: "#484f58" };
    upsertChart("chart-types", "doughnut", {
      labels: typeLabels,
      datasets: [{ data: typeLabels.map(t => typeCounts[t]), backgroundColor: typeLabels.map(t => typeColors[t] ?? "#484f58"), borderWidth: 0 }],
    }, { plugins: { legend: { position: "right", labels: { color: "#8b949e", font: { size: 11 } } } } });

    // Chart: d20 distribution
    upsertChart("chart-dist", "bar", {
      labels: Array.from({length:20},(_,i)=>i+1),
      datasets: [{ label: "Rolls", data: dist, backgroundColor: dist.map((_,i) => i===19?"#56d36488":i===0?"#f8514988":"#388bfd55"), borderColor: dist.map((_,i) => i===19?"#56d364":i===0?"#f85149":"#388bfd"), borderWidth: 1 }],
    }, { plugins: { legend: { display: false } }, scales: { x: { ticks: { color: "#8b949e" }, grid: { color: "#21262d" } }, y: { ticks: { color: "#8b949e", stepSize: 1 }, grid: { color: "#21262d" }, beginAtZero: true } } });

    // Roll log
    renderRollList("stats-roll-list");

    // Chart: avg per character
    upsertChart("chart-avg", "bar", {
      labels: charNames,
      datasets: [{ label: "Avg Total", data: charNames.map(n => chars[n].totals.length ? (chars[n].totals.reduce((a,b)=>a+b,0)/chars[n].totals.length).toFixed(1) : 0), backgroundColor: "#388bfd55", borderColor: "#388bfd", borderWidth: 1 }],
    }, { plugins: { legend: { display: false } }, scales: { x: { ticks: { color: "#8b949e" }, grid: { color: "#21262d" } }, y: { ticks: { color: "#8b949e" }, grid: { color: "#21262d" }, beginAtZero: true } } });
  }

  function renderRolls() {
    if (_activeTab === "stats") renderStats();
    document.getElementById("roll-count").textContent = `${rolls.length} roll${rolls.length !== 1 ? "s" : ""}`;
    renderRollList("roll-list");
  }

  function renderRollList(listId) {
    const list = document.getElementById(listId);
    if (!list) return;
    list.innerHTML = rolls.map(r => {
      const tc = rollTypeClass(r.rollType);
      const active = r.id === activeRollId ? " active" : "";
      return `<div class="roll-item${active}" onclick="openRoll('${esc(r.id)}')" style="cursor:pointer;">
        <div class="roll-item-header">
          <span class="roll-char">${esc(r.character)}</span>
          <span class="roll-total">${r.total}</span>
        </div>
        <div class="roll-item-header" style="margin-top:3px;">
          <span class="roll-action">${esc(r.action)}</span>
          <span class="roll-type-badge ${tc}">${esc(r.rollType)}</span>
        </div>
        <div style="font-size:0.72em; color:#484f58; margin-top:2px;">${r.ts}</div>
      </div>`;
    }).join("");
  }

  // ---- Modal ----
  async function openRoll(id) {
    activeRollId = id;
    renderRollList("roll-list");
    renderRollList("stats-roll-list");

    // Show modal immediately with loading state
    const body = document.getElementById("modal-body");
    document.getElementById("modal-title").textContent = "Loading...";
    body.innerHTML = `<div style="color:#484f58; padding:20px;">Loading roll detail...</div>`;
    document.getElementById("modal-backdrop").classList.add("open");
    document.querySelector(".modal").classList.add("open");

    const detail = await fetch(`/api/rolls/${encodeURIComponent(id)}`).then(r => r.json());

    if (!detail) {
      document.getElementById("modal-title").textContent = "Roll not found";
      body.innerHTML = `<div style="color:#f85149; padding:20px;">This roll is no longer in history. Try clearing rolls and rolling again.</div>`;
      return;
    }

    document.getElementById("modal-title").textContent =
      `${detail.character} — ${detail.action} (${detail.rollType})`;

    const diceHtml = (detail.dice || []).length
      ? detail.dice.map(d => `<span class="die-chip">d${d.faces}: <strong>${d.result}</strong></span>`).join("")
      : "<span style='color:#484f58'>—</span>";

    body.innerHTML = `
      <div class="detail-grid">
        <div class="detail-card">
          <h4>Character</h4>
          <div class="detail-row"><span class="detail-label">Name</span><span class="detail-value">${esc(detail.character)}</span></div>
          <div class="detail-row"><span class="detail-label">Entity ID</span><span class="detail-value">${esc(detail.entity_id || "—")}</span></div>
          <div class="detail-row"><span class="detail-label">Entity Type</span><span class="detail-value">${esc(detail.entity_type || "—")}</span></div>
          <div class="detail-row"><span class="detail-label">Game ID</span><span class="detail-value">${esc(detail.game_id || "—")}</span></div>
          <div class="detail-row"><span class="detail-label">Roll ID</span><span class="detail-value" style="font-size:0.75em">${esc(detail.id)}</span></div>
        </div>
        <div class="detail-card">
          <h4>Roll</h4>
          <div class="detail-row"><span class="detail-label">Action</span><span class="detail-value">${esc(detail.action)}</span></div>
          <div class="detail-row"><span class="detail-label">Type</span><span class="detail-value">${esc(detail.rollType)}</span></div>
          <div class="detail-row"><span class="detail-label">Total</span><span class="detail-value" style="font-size:1.2em; color:#58a6ff;">${detail.total}</span></div>
          <div class="detail-row"><span class="detail-label">Breakdown</span><span class="detail-value">${esc(detail.text)}</span></div>
          <div class="detail-row"><span class="detail-label">Modifier</span><span class="detail-value">${detail.constant >= 0 ? "+" : ""}${detail.constant}</span></div>
          <div class="detail-row" style="flex-direction:column; align-items:flex-start; gap:6px;">
            <span class="detail-label">Dice</span>
            <div class="dice-list">${diceHtml}</div>
          </div>
        </div>
      </div>

      <div class="json-section">
        <details>
          <summary>▶ Raw DDB JSON</summary>
          <pre class="json-viewer">${esc(JSON.stringify(detail.raw, null, 2))}</pre>
        </details>
      </div>`;
  }

  function closeModal(e) {
    if (e && e.target !== document.getElementById("modal-backdrop")) return;
    document.getElementById("modal-backdrop").classList.remove("open");
    document.querySelector(".modal").classList.remove("open");
  }

  async function resendRoll() {
    if (!activeRollId) return;
    const btn = document.getElementById("resend-btn");
    btn.disabled = true;
    btn.textContent = "Sending...";
    try {
      const res = await fetch(`/api/rolls/${encodeURIComponent(activeRollId)}/resend`, { method: "POST" });
      if (res.ok) toast("Roll resent to Foundry!");
      else toast("Resend failed.", true);
    } catch { toast("Resend failed.", true); }
    btn.disabled = false;
    btn.textContent = "↺ Resend to Foundry";
  }

  // ---- Campaign switcher ----
  function switchGameId() {
    const id = document.getElementById("quick-game-id").value.trim();
    if (!id) { toast("Please enter a Game ID.", true); return; }
    document.getElementById("game-id").value = id;
    saveConfig(true);
  }

  // ---- Config ----
  async function loadConfig() {
    const cfg = await fetch("/api/config").then(r => r.json());
    document.getElementById("cobalt-token").value = cfg.DDB_COBALT_TOKEN;
    document.getElementById("game-id").value       = cfg.DDB_GAME_ID;
    document.getElementById("user-id").value       = cfg.DDB_USER_ID;
  }

  async function saveConfig(andRestart) {
    const body = {
      DDB_COBALT_TOKEN: document.getElementById("cobalt-token").value,
      DDB_GAME_ID:      document.getElementById("game-id").value,
      DDB_USER_ID:      document.getElementById("user-id").value,
    };
    const res = await fetch("/api/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.ok) { toast("Configuration saved!"); if (andRestart) await restartDDB(); }
    else toast("Save failed.", true);
  }

  async function restartDDB() {
    await fetch("/api/restart", { method: "POST" });
    toast("DDB connection restarting...");
  }

  function togglePw(id, btn) {
    const el = document.getElementById(id);
    const show = el.type === "password";
    el.type = show ? "text" : "password";
    btn.textContent = show ? "Hide" : "Show";
  }

  function toast(msg, err = false) {
    const t = document.getElementById("toast");
    t.textContent = msg;
    t.className = err ? "err" : "";
    t.style.display = "block";
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.style.display = "none", 2500);
  }

  // Keyboard: Escape closes modal
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") { document.getElementById("modal-backdrop").classList.remove("open"); document.querySelector(".modal").classList.remove("open"); }
  });

  // ---- Webhooks ----
  async function loadWebhooks() {
    const urls = await fetch("/api/webhooks").then(r => r.json()).catch(() => []);
    const list = document.getElementById("webhook-list");
    if (!urls.length) {
      list.innerHTML = `<div style="font-size:0.82em;color:#8b949e;">No webhooks configured.</div>`;
      return;
    }
    list.innerHTML = urls.map((url, i) => `
      <div style="display:flex;align-items:center;gap:6px;background:#161b22;border:1px solid #30363d;border-radius:5px;padding:6px 10px;">
        <span style="flex:1;font-size:0.85em;color:#e6edf3;word-break:break-all;">${url}</span>
        <button class="btn small danger" onclick="removeWebhook(${i})">✕</button>
      </div>`).join("");
  }

  async function addWebhook() {
    const input = document.getElementById("webhook-input");
    const url = input.value.trim();
    if (!url) return;
    await fetch("/api/webhooks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }) });
    input.value = "";
    loadWebhooks();
    toast("Webhook added.");
  }

  async function removeWebhook(index) {
    await fetch(`/api/webhooks/${index}`, { method: "DELETE" });
    loadWebhooks();
    toast("Webhook removed.");
  }

  document.getElementById("webhook-input").addEventListener("keydown", e => {
    if (e.key === "Enter") addWebhook();
  });

  loadConfig();
  loadRolls();
  loadWebhooks();

  // ══════════════════════════════════════════════════════════════
  // MODULE SWITCHER
  // ══════════════════════════════════════════════════════════════

  let _activeModule = "ab";

  function toggleModulePick(e) {
    e.stopPropagation();
    document.getElementById("module-pick").classList.toggle("open");
  }
  document.addEventListener("click", () => document.getElementById("module-pick").classList.remove("open"));

  function switchModule(mod) {
    _activeModule = mod;
    document.getElementById("module-pick").classList.remove("open");

    const isAb = mod === "ab";
    document.getElementById("module-icon").textContent = isAb ? "⬡" : "🕯️";
    document.getElementById("module-name").textContent = isAb ? "AstralBridge" : "Dancing Lights";
    document.getElementById("tabs-ab").style.display = isAb ? "" : "none";
    document.getElementById("tabs-dl").style.display        = isAb ? "none" : "";
    document.getElementById("dl-live-strip").style.display  = isAb ? "none" : "";
    document.getElementById("pill-ddb").style.display      = isAb ? "" : "none";
    document.getElementById("pill-foundry").style.display  = isAb ? "" : "none";
    document.getElementById("dl-hdr-toggle").style.display = isAb ? "none" : "";
    document.getElementById("mopt-ab").classList.toggle("active", isAb);
    document.getElementById("mopt-dl").classList.toggle("active", !isAb);

    if (isAb) {
      stopDlPolling();
      // Clear DL view inline styles so CSS classes control them
      document.querySelectorAll(".dl-view").forEach(el => { el.style.display=""; el.classList.remove("active"); });
      // Clear inline styles on AB views so classList works again
      ["view-dashboard","view-stats","view-config"].forEach(id => {
        const el = document.getElementById(id); if (el) el.style.display = "";
      });
      switchTab(_activeTab || "dashboard");
    } else {
      // Clear AB views
      ["view-dashboard","view-stats","view-config"].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.classList.remove("active"); el.style.display = "none"; }
      });
      document.querySelectorAll(".dl-view").forEach(el => { el.style.display=""; el.classList.remove("active"); });
      switchDlTab(_activeDlTab || "dashboard");
      dlLoadAll();
      startDlPolling();
    }
  }

  // ══════════════════════════════════════════════════════════════
  // DANCING LIGHTS — state & helpers
  // ══════════════════════════════════════════════════════════════

  let _activeDlTab   = "events";
  let _dlEvents      = {};
  let _dlData        = { ip: "", total_leds: 60, brightness: 180, players: [], corners: [], active_player: null, current_ambient: null, roll_active: false };
  let _dlSelected    = null;
  let _dlDrag        = null;
  let _dlHover       = null;
  let _dlCornerDrag  = null;
  let _dlPreviewTick = false;

  const DL_EFFECTS = [[0,"Solid"],[2,"Breathe"],[4,"Wipe"],[9,"Blink"],[11,"Strobe"],[13,"Chase"],
    [17,"Dissolve"],[25,"Fire 2012"],[28,"Colorwave"],[38,"Colorloop"],[45,"Fireworks"],
    [46,"Rain"],[56,"Pride 2015"],[58,"Oscillate"],[65,"Glitter"],[73,"Scan"],
    [77,"Fade"],[88,"Ripple"],[91,"BPM"],[98,"Sunrise"]];

  const DL_ICONS = { nat20:"⭐",nat1:"💀",damage:"🔥",heal:"💚",initiative:"⚔️",save:"🛡️",check:"🎲",attack:"🗡️" };

  function dlRgbToHex(rgb) { return "#" + rgb.map(v => v.toString(16).padStart(2,"0")).join(""); }
  function dlHexToRgb(hex) { return [parseInt(hex.slice(1,3),16),parseInt(hex.slice(3,5),16),parseInt(hex.slice(5,7),16)]; }

  function switchDlTab(tab) {
    _activeDlTab = tab;
    ["dashboard","events","ambient","config","devices"].forEach(t => {
      const view = document.getElementById(`view-dl-${t}`);
      const btn  = document.getElementById(`tab-dl-${t}`);
      if (view) view.classList.toggle("active", t === tab);
      if (btn)  btn.classList.toggle("active", t === tab);
    });
    if (tab === "config") {
      requestAnimationFrame(() => { dlDrawStrip(); dlDrawScreen(); dlInitCanvas(); });
    }
  }

  async function dlLoadAll() {
    await Promise.all([dlLoadDlConfig(), dlLoadHaConfig(), dlLoadEvents(), dlLoadDs(), dlLoadAmbient(), dlLoadDashboard(), devLoadAll()]);
  }

  let _dlPollInterval = null;

  function startDlPolling() {
    if (_dlPollInterval) return;
    _dlPollInterval = setInterval(async () => {
      const data = await fetch("/dl/api/dungeon-screen").then(r => r.json()).catch(() => null);
      if (!data) return;
      _dlData.current_ambient = data.current_ambient;
      _dlData.roll_active     = data.roll_active;
      _dlData.roll_event      = data.roll_event;
      _dlData.active_player   = data.active_player;
      dlRenderAmbientButtons();
      dlDrawStrip();
      dlDrawScreen();
      dlDrawLive();
    }, 3000);
  }

  function stopDlPolling() {
    clearInterval(_dlPollInterval);
    _dlPollInterval = null;
  }

  // ─── Dashboard ────────────────────────────────────────────────

  let _dlManualMode    = false;
  let _dlCustomDebounce = null;
  let _dlActivePreset   = null;

  async function dlLoadDashboard() {
    const data = await fetch("/dl/api/mode").then(r => r.json()).catch(() => null);
    if (data) _dlManualMode = data.manual;
    dlUpdateModeUI(_dlManualMode);
    // Populate custom effect dropdown
    const fxSel = document.getElementById("dl-custom-fx");
    if (fxSel && !fxSel.options.length) {
      fxSel.innerHTML = DL_EFFECTS.map(([id,name]) => `<option value="${id}">${name}</option>`).join("");
    }
    // Init brightness from _dlData
    const briInput = document.getElementById("dl-custom-bri");
    if (briInput) {
      briInput.value = _dlData.brightness || 180;
      document.getElementById("dlCustomBriLabel").textContent = briInput.value;
    }
    if (!Object.keys(_dlAmbientModes).length) await dlLoadAmbient();
    dlRenderPresetButtons();
  }

  function dlUpdateModeUI(manual) {
    document.getElementById("dl-mode-label").textContent = manual ? "Manual" : "Automatic";
    document.getElementById("dl-mode-desc").textContent  = manual ? "You control the LEDs directly" : "Events & combat turns run automatically";
    const toggle = document.getElementById("dl-mode-toggle");
    const knob   = document.getElementById("dl-mode-knob");
    toggle.style.background  = manual ? "#3a1a1a" : "#1a3a1a";
    toggle.style.borderColor = manual ? "#7a2a2a" : "#2a7a2a";
    knob.style.background    = manual ? "#c44"    : "#4c4";
    knob.style.left          = manual ? "2px"     : "26px";
    document.getElementById("dl-auto-content").style.display   = manual ? "none" : "";
    document.getElementById("dl-manual-content").style.display = manual ? ""     : "none";
  }

  async function dlToggleMode() {
    const data = await fetch("/dl/api/mode", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({manual: !_dlManualMode})
    }).then(r => r.json()).catch(() => null);
    if (data != null) {
      _dlManualMode = data.manual;
      dlUpdateModeUI(_dlManualMode);
    }
  }

  function dlRenderPresetButtons() {
    const container = document.getElementById("dl-preset-buttons");
    if (!container) return;
    const icons = {tavern:"🍺",dungeon:"🌑",forest:"🌲",hell:"🔥",ocean:"🌊",magic:"✨",ice:"❄️",combat:"⚔️"};
    let html = "";
    for (const key of Object.keys(_dlAmbientModes)) {
      const label = DL_AMBIENT_LABELS[key] || (key.charAt(0).toUpperCase() + key.slice(1));
      const icon  = icons[key] ? icons[key] + " " : "";
      html += `<button class="btn small" id="dl-preset-${key}" onclick="dlApplyPreset('${key}')">${icon}${label}</button>`;
    }
    html += `<button class="btn small" id="dl-preset-off" onclick="dlApplyPreset('off')">⬛ Off</button>`;
    container.innerHTML = html;
  }

  async function dlApplyPreset(key) {
    _dlActivePreset = key;
    document.querySelectorAll("#dl-preset-buttons .btn").forEach(b => b.style.outline = "");
    const btn = document.getElementById(`dl-preset-${key}`);
    if (btn) btn.style.outline = "2px solid var(--accent, #6060ff)";
    if (key === "off") {
      await fetch("/dl/api/dungeon-screen/manual-apply", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({on:false})});
      return;
    }
    const mode = _dlAmbientModes[key];
    if (!mode) return;
    clearTimeout(_dlCustomDebounce);
    const colorEl = document.getElementById("dl-custom-color");
    const fxEl    = document.getElementById("dl-custom-fx");
    const briEl   = document.getElementById("dl-custom-bri");
    const sxEl    = document.getElementById("dl-custom-sx");
    if (colorEl) colorEl.value = dlRgbToHex(mode.color || [255,255,255]);
    if (fxEl)    fxEl.value    = mode.fx ?? 0;
    if (briEl)   { briEl.value = mode.bri ?? 180; document.getElementById("dlCustomBriLabel").textContent = briEl.value; }
    if (sxEl)    { sxEl.value  = mode.sx  ?? 128; document.getElementById("dlCustomSxLabel").textContent  = sxEl.value; }
    await fetch("/dl/api/dungeon-screen/manual-apply", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({on:true, color: mode.color || [255,255,255], fx: mode.fx ?? 0, bri: mode.bri ?? 180, sx: mode.sx ?? 128})
    });
  }

  function dlCustomChanged() {
    _dlActivePreset = null;
    document.querySelectorAll("#dl-preset-buttons .btn").forEach(b => b.style.outline = "");
    clearTimeout(_dlCustomDebounce);
    _dlCustomDebounce = setTimeout(dlCustomApply, 150);
  }

  async function dlCustomApply() {
    clearTimeout(_dlCustomDebounce);
    const color = dlHexToRgb(document.getElementById("dl-custom-color").value);
    const fx    = parseInt(document.getElementById("dl-custom-fx").value);
    const bri   = parseInt(document.getElementById("dl-custom-bri").value);
    const sx    = parseInt(document.getElementById("dl-custom-sx").value);
    await fetch("/dl/api/dungeon-screen/manual-apply", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({on:true, color, fx, bri, sx})
    });
  }

  async function dlStripOff() {
    await fetch("/dl/api/dungeon-screen/manual-apply", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({on:false})
    });
  }

  async function dlStripOn() {
    await fetch("/dl/api/dungeon-screen/manual-apply", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({on:true})
    });
  }

  // ─── Ambient ──────────────────────────────────────────────────
  const DL_AMBIENT_LABELS = {
    tavern:"Tavern", dungeon:"Dungeon", forest:"Forest", hell:"Hell",
    ocean:"Ocean", magic:"Magic", ice:"Ice", combat:"Combat"
  };

  let _dlAmbientModes = {};
  let _dlAmbientSelected = null;

  async function dlLoadAmbient() {
    // Populate effect dropdowns
    const effectOpts = DL_EFFECTS.map(([id,name]) => `<option value="${id}">${name}</option>`).join("");
    const fxSel = document.getElementById("dl-ambient-fx");
    const fxAdd = document.getElementById("dl-add-amb-fx");
    if (fxSel) fxSel.innerHTML = effectOpts;
    if (fxAdd) fxAdd.innerHTML = effectOpts;

    const data = await fetch("/dl/api/dungeon-screen/ambient").then(r=>r.json()).catch(()=>null);
    if (!data) return;
    _dlAmbientModes = data.modes || {};
    _dlData.current_ambient = data.current;
    dlRenderAmbientButtons();
  }

  function dlRenderAmbientButtons() {
    const container = document.getElementById("dl-ambient-btns");
    if (!container) return;
    const active = _dlData.current_ambient;
    const modeKeys = Object.keys(_dlAmbientModes);
    container.innerHTML = modeKeys.map(key => {
      const isActive = key === active;
      const label = DL_AMBIENT_LABELS[key] || key;
      return `<span style="display:inline-flex;align-items:center;gap:2px;">` +
        `<button onclick="dlAmbientActivate('${key}')" style="
          padding:5px 12px;font-size:.8em;border-radius:5px 0 0 5px;cursor:pointer;border:1px solid;border-right:none;
          background:${isActive ? "var(--accent,#7c3aed)" : "var(--bg)"};
          color:${isActive ? "#fff" : "var(--text)"};
          border-color:${isActive ? "var(--accent,#7c3aed)" : "var(--border)"};
          font-weight:${isActive ? "700" : "400"};
        ">${label}</button>` +
        `<button onclick="dlDeleteAmbientMode('${key}')" title="Löschen" style="
          padding:5px 7px;font-size:.75em;border-radius:0 5px 5px 0;cursor:pointer;border:1px solid;
          background:var(--bg);color:var(--text-muted);
          border-color:${isActive ? "var(--accent,#7c3aed)" : "var(--border)"};
        ">✕</button>` +
        `</span>`;
    }).join("") + `<button onclick="dlAmbientOff()" style="
      padding:5px 12px;font-size:.8em;border-radius:5px;cursor:pointer;border:1px solid;
      background:${!active ? "var(--danger,#c0392b)" : "var(--bg)"};
      color:${!active ? "#fff" : "var(--text-muted)"};
      border-color:${!active ? "var(--danger,#c0392b)" : "var(--border)"};
    ">Aus</button>`;
  }

  async function dlAmbientActivate(mode) {
    _dlAmbientSelected = mode;
    await fetch(`/dl/api/dungeon-screen/ambient/${mode}`, {method:"POST"});
    _dlData.current_ambient = mode;
    dlRenderAmbientButtons();
    dlShowAmbientEditor(mode);
  }

  async function dlAmbientOff() {
    await fetch("/dl/api/dungeon-screen/ambient", {method:"DELETE"});
    _dlData.current_ambient = null;
    _dlAmbientSelected = null;
    dlRenderAmbientButtons();
    document.getElementById("dl-ambient-editor").style.display = "none";
  }

  function dlShowAmbientEditor(mode) {
    const m = _dlAmbientModes[mode];
    if (!m) return;
    document.getElementById("dl-ambient-editor").style.display = "block";
    document.getElementById("dl-ambient-editor-label").textContent = DL_AMBIENT_LABELS[mode] || mode;
    const [r,g,b] = m.color;
    document.getElementById("dl-ambient-color").value = "#" + [r,g,b].map(x=>x.toString(16).padStart(2,"0")).join("");
    const fxSel = document.getElementById("dl-ambient-fx");
    if (fxSel) fxSel.value = m.fx ?? 0;
    document.getElementById("dl-ambient-bri").value = m.bri;
    document.getElementById("dl-ambient-sx").value = m.sx;
  }

  let _dlAmbientPatchTimer = null;

  // ── Simple Devices ─────────────────────────────────────────────────────────
  let _devList        = [];
  let _devSelected    = null;   // id of selected device
  let _devType        = "wled"; // type of selected device
  let _devManualMode  = false;
  let _devEvents      = {};
  let _devAmbientModes = {};
  let _devAmbientSelected = null;
  let _devCustomTimer = null;
  let _devAmbientPatchTimer = null;
  let _devActivePreset = null;

  async function dlAmbientPatch() {
    if (!_dlAmbientSelected) return;
    clearTimeout(_dlAmbientPatchTimer);
    _dlAmbientPatchTimer = setTimeout(async () => {
      const hex = document.getElementById("dl-ambient-color").value;
      const color = [1,3,5].map(i => parseInt(hex.slice(i,i+2),16));
      const fx = parseInt(document.getElementById("dl-ambient-fx")?.value ?? 0);
      const bri = parseInt(document.getElementById("dl-ambient-bri").value);
      const sx = parseInt(document.getElementById("dl-ambient-sx").value);
      _dlAmbientModes[_dlAmbientSelected] = {...(_dlAmbientModes[_dlAmbientSelected]||{}), color, fx, bri, sx};
      await fetch(`/dl/api/dungeon-screen/ambient/${_dlAmbientSelected}`, {
        method:"PATCH", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({color, fx, bri, sx})
      });
    }, 150);
  }

  async function dlDeleteAmbientMode(key) {
    if (!confirm(`Delete mode "${DL_AMBIENT_LABELS[key] || key}"?`)) return;
    const r = await fetch(`/dl/api/dungeon-screen/ambient/${key}`, {method:"DELETE"});
    if (!r.ok) { toast("Error deleting."); return; }
    delete _dlAmbientModes[key];
    if (_dlData.current_ambient === key) {
      _dlData.current_ambient = null;
      _dlAmbientSelected = null;
      document.getElementById("dl-ambient-editor").style.display = "none";
    }
    dlRenderAmbientButtons();
    toast(`Mode "${DL_AMBIENT_LABELS[key] || key}" deleted.`);
  }

  async function dlAddAmbientMode() {
    const name = document.getElementById("dl-add-amb-name").value.trim().toLowerCase().replace(/[^a-z0-9_]/g,"");
    if (!name) { toast("Please enter a valid name."); return; }
    if (_dlAmbientModes[name]) { toast(`Mode "${name}" already exists.`); return; }
    const hex = document.getElementById("dl-add-amb-color").value;
    const color = [1,3,5].map(i => parseInt(hex.slice(i,i+2),16));
    const fx = parseInt(document.getElementById("dl-add-amb-fx").value);
    const bri = parseInt(document.getElementById("dl-add-amb-bri").value);
    const sx = parseInt(document.getElementById("dl-add-amb-sx").value);
    const r = await fetch(`/dl/api/dungeon-screen/ambient/${name}`, {
      method:"PUT", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({color, fx, bri, sx})
    });
    if (!r.ok) { toast("Error adding."); return; }
    _dlAmbientModes[name] = {color, fx, bri, sx};
    document.getElementById("dl-add-amb-name").value = "";
    dlRenderAmbientButtons();
    toast(`Mode "${name}" added.`);
  }

  // ─── DL Config (enabled flag) ────────────────────────────────
  async function dlLoadDlConfig() {
    const cfg = await fetch("/dl/api/config").then(r => r.json()).catch(() => ({ enabled: false }));
    document.getElementById("dl-enabled-chk").checked = cfg.enabled;
    dlUpdateBadge(cfg.enabled);
  }

  async function dlLoadHaConfig() {
    const data = await fetch("/dl/api/ha-config").then(r => r.json()).catch(() => null);
    if (!data) return;
    document.getElementById("ha-url").value = data.url || "";
    const status = document.getElementById("ha-config-status");
    if (status) status.textContent = data.token_set ? "Token gesetzt ✓" : "Kein Token";
  }

  async function dlSaveHaConfig() {
    const url   = document.getElementById("ha-url").value.trim();
    const token = document.getElementById("ha-token").value.trim();
    const r = await fetch("/dl/api/ha-config", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url, token})
    });
    if (r.ok) {
      const data = await r.json();
      const status = document.getElementById("ha-config-status");
      if (status) status.textContent = data.token_set ? "Token gesetzt ✓" : "Kein Token";
      document.getElementById("ha-token").value = "";
      toast("Home Assistant Konfiguration gespeichert.");
    } else {
      toast("Fehler beim Speichern.");
    }
  }

  function dlUpdateBadge(enabled) {
    const badge = document.getElementById("dl-badge");
    if (!badge) return;
    badge.textContent = enabled ? "ON" : "OFF";
    badge.className = "dl-badge" + (enabled ? " on" : "");
  }

  async function setDlEnabled(enabled) {
    await fetch("/dl/api/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    dlUpdateBadge(enabled);
    toast(enabled ? "Dancing Lights enabled." : "Dancing Lights disabled.");
  }


  // ─── DL Events ───────────────────────────────────────────────
  async function dlLoadEvents() {
    const effectOpts = DL_EFFECTS.map(([id,name]) => `<option value="${id}">${name}</option>`).join("");
    const addFx = document.getElementById("dl-add-ev-fx");
    if (addFx) addFx.innerHTML = effectOpts;
    _dlEvents = await fetch("/dl/api/events").then(r => r.json()).catch(() => ({}));
    dlRenderEvents(_dlEvents);
  }

  function dlRenderEvents(events) {
    const grid = document.getElementById("dl-event-grid");
    const effectOpts = DL_EFFECTS.map(([id,name]) => `<option value="${id}">${name}</option>`).join("");
    grid.innerHTML = Object.entries(events).map(([key, ev]) => `
      <div class="dl-event-card" id="dl-ecard-${key}">
        <div class="dl-ev-header">
          <span class="dl-ev-icon">${DL_ICONS[key]||"🎲"}</span>
          <span class="dl-ev-name">${ev.label||key}</span>
          <label class="dl-toggle"><input type="checkbox" id="dl-ev-en-${key}" ${ev.enabled?"checked":""}><div class="dl-toggle-track"></div></label>
        </div>
        <div class="dl-ev-row"><label>Color</label><input type="color" id="dl-ev-col-${key}" value="${dlRgbToHex(ev.color||[255,255,255])}"><div style="flex:1"></div><label style="width:auto;margin:0;">Effect</label><select id="dl-ev-fx-${key}" style="width:115px;">${effectOpts}</select></div>
        <div class="dl-ev-row"><label>Brightness</label><input type="range" id="dl-ev-bri-${key}" min="0" max="255" value="${ev.brightness??200}" oninput="document.getElementById('dl-bv-${key}').textContent=this.value"><span class="dl-slider-val" id="dl-bv-${key}">${ev.brightness??200}</span></div>
        <div class="dl-ev-row"><label>Speed</label><input type="range" id="dl-ev-spd-${key}" min="0" max="255" value="${ev.speed??128}" oninput="document.getElementById('dl-sv-${key}').textContent=this.value"><span class="dl-slider-val" id="dl-sv-${key}">${ev.speed??128}</span></div>
        <div class="dl-ev-row"><label>Duration</label><input type="number" id="dl-ev-dur-${key}" value="${ev.duration??2000}" min="500" max="10000" step="100" style="width:80px;"><span style="font-size:.75em;color:var(--text-muted);">ms</span></div>
        <div style="display:flex;gap:6px;margin-top:10px;">
          <button class="btn small" style="background:var(--green-dim);border-color:rgba(52,208,104,.3);color:var(--green);" onclick="dlTestEvent('${key}')">▶ Test</button>
          <button class="btn small danger" onclick="dlDeleteEvent('${key}')">✕ Löschen</button>
        </div>
      </div>`).join("");
    Object.entries(events).forEach(([key,ev]) => {
      const sel = document.getElementById(`dl-ev-fx-${key}`);
      if (sel) sel.value = ev.effect ?? 0;
    });
  }

  function dlCollectEvents() {
    return Object.fromEntries(Object.entries(_dlEvents).map(([key,ev]) => [key, {
      label:      ev.label,
      enabled:    document.getElementById(`dl-ev-en-${key}`)?.checked ?? ev.enabled,
      color:      dlHexToRgb(document.getElementById(`dl-ev-col-${key}`)?.value || "#ffffff"),
      effect:     parseInt(document.getElementById(`dl-ev-fx-${key}`)?.value ?? ev.effect),
      brightness: parseInt(document.getElementById(`dl-ev-bri-${key}`)?.value ?? ev.brightness),
      speed:      parseInt(document.getElementById(`dl-ev-spd-${key}`)?.value ?? ev.speed),
      duration:   parseInt(document.getElementById(`dl-ev-dur-${key}`)?.value ?? ev.duration),
    }]));
  }

  async function dlSaveEvents() {
    const events = dlCollectEvents();
    const res = await fetch("/dl/api/events", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(events) });
    if (res.ok) toast("Events saved!");
  }

  async function dlTestEvent(name) {
    await fetch(`/dl/api/events/${name}/trigger`, { method:"POST" });
    toast(`Triggered: ${name}`);
  }

  async function dlDeleteEvent(key) {
    if (!confirm(`Delete event "${_dlEvents[key]?.label || key}"?`)) return;
    const r = await fetch(`/dl/api/events/${key}`, {method:"DELETE"});
    if (!r.ok) { toast("Error deleting."); return; }
    delete _dlEvents[key];
    dlRenderEvents(_dlEvents);
    toast(`Event "${key}" deleted.`);
  }

  async function dlAddEvent() {
    const key = document.getElementById("dl-add-ev-key").value.trim().toLowerCase().replace(/[^a-z0-9_]/g,"");
    if (!key) { toast("Please enter a valid key."); return; }
    if (_dlEvents[key]) { toast(`Event "${key}" already exists.`); return; }
    const label  = document.getElementById("dl-add-ev-label").value.trim() || key;
    const color  = dlHexToRgb(document.getElementById("dl-add-ev-color").value);
    const effect = parseInt(document.getElementById("dl-add-ev-fx").value);
    const bri    = parseInt(document.getElementById("dl-add-ev-bri").value);
    const speed  = parseInt(document.getElementById("dl-add-ev-spd").value);
    const dur    = parseInt(document.getElementById("dl-add-ev-dur").value);
    const enabled = document.getElementById("dl-add-ev-en").checked;
    const body = {label, enabled, color, effect, brightness: bri, speed, duration: dur};
    const r = await fetch(`/dl/api/events/${key}`, {
      method:"PUT", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)
    });
    if (!r.ok) { toast("Error adding."); return; }
    _dlEvents[key] = body;
    document.getElementById("dl-add-ev-key").value = "";
    document.getElementById("dl-add-ev-label").value = "";
    dlRenderEvents(_dlEvents);
    toast(`Event "${key}" added.`);
  }

  // ─── DL Dungeon Screen ───────────────────────────────────────
  async function dlLoadDs() {
    _dlData = await fetch("/dl/api/dungeon-screen").then(r => r.json()).catch(() => _dlData);
    document.getElementById("dl-ds-ip").value    = _dlData.ip || "";
    document.getElementById("dl-ds-total").value = _dlData.total_leds || 60;
    document.getElementById("dl-ds-bri").value   = _dlData.brightness || 180;
    document.getElementById("dl-ds-led-label").textContent = `LED ${(_dlData.total_leds||60)-1}`;
    document.getElementById("dl-ambient-during-turn").checked = _dlData.ambient_during_turn !== false;
    document.getElementById("dl-turn-buffer").value = _dlData.turn_buffer_leds ?? 2;
    if (!_dlData.corners || _dlData.corners.length < 3) {
      const t = _dlData.total_leds || 60;
      _dlData.corners = [Math.round(t*.25), Math.round(t*.5), Math.round(t*.75)];
    }
    dlRenderPlayers();
    dlDrawStrip();
    dlDrawScreen();
    dlDrawLive();
  }

  async function dlSaveDsConfig() {
    const newTotal = parseInt(document.getElementById("dl-ds-total").value) || 60;
    let corners = _dlData.corners || [];
    if (corners.length < 3) corners = [Math.round(newTotal*.25), Math.round(newTotal*.5), Math.round(newTotal*.75)];
    const body = {
      ip: document.getElementById("dl-ds-ip").value.trim(),
      total_leds: newTotal,
      brightness: parseInt(document.getElementById("dl-ds-bri").value) || 180,
      players: _dlData.players || [],
      corners,
    };
    await fetch("/dl/api/dungeon-screen", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body) });
    _dlData = { ..._dlData, ...body };
    document.getElementById("dl-ds-led-label").textContent = `LED ${body.total_leds - 1}`;
    dlDrawStrip(); dlDrawScreen();
    toast("Dungeon Screen saved.");
  }

  async function dlSaveTurnSettings() {
    _dlData.ambient_during_turn = document.getElementById("dl-ambient-during-turn").checked;
    _dlData.turn_buffer_leds    = parseInt(document.getElementById("dl-turn-buffer").value) || 0;
    await fetch("/dl/api/dungeon-screen", {
      method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(_dlData)
    });
  }

  async function dlPingDs() {
    const el = document.getElementById("dl-ds-ping");
    el.textContent = "Pinging…";
    const res = await fetch("/dl/api/dungeon-screen/ping").then(r => r.json()).catch(() => ({online:false}));
    el.style.color = res.online ? "var(--green)" : "var(--red)";
    el.textContent = res.online ? `✓ Online — ${res.name||"WLED"} v${res.version||"?"} · ${res.leds||"?"} LEDs` : `✗ Unreachable — ${res.error||""}`;
  }

  // ─── Live LED strip ──────────────────────────────────────────
  function dlDrawLive() {
    const canvas = document.getElementById("dl-live-canvas");
    if (!canvas) return;
    const total  = _dlData.total_leds || 60;
    const cssW   = canvas.parentElement?.offsetWidth || 600;
    if (canvas.width !== cssW) canvas.width = cssW;
    const padX   = 6;
    const ledW   = (cssW - padX * 2) / total;
    const ledR   = Math.min(ledW * 0.42, 8);
    const midY   = canvas.height / 2;
    const ctx    = canvas.getContext("2d");
    ctx.clearRect(0, 0, cssW, canvas.height);
    ctx.fillStyle = "#050709"; ctx.fillRect(0, 0, cssW, canvas.height);

    const roll        = _dlData.roll_active;
    const playerId    = _dlData.active_player;
    const ambientKey  = _dlData.current_ambient;
    const ambientOn   = _dlData.ambient_during_turn !== false;
    const buffer      = parseInt(_dlData.turn_buffer_leds ?? 2);
    const player      = playerId ? (_dlData.players||[]).find(p => p.id === playerId) : null;
    const ambientCfg  = ambientKey ? _dlAmbientModes[ambientKey] : null;
    const ambColor    = ambientCfg?.color ?? null;

    // Build per-LED color array
    const colors = new Array(total).fill(null);
    if (roll) {
      for (let i = 0; i < total; i++) colors[i] = [255, 200, 40];
    } else if (player) {
      if (ambientOn && ambColor) for (let i = 0; i < total; i++) colors[i] = ambColor;
      const bufS = Math.max(0, player.start - buffer);
      const bufE = Math.min(total, player.end + buffer);
      for (let i = bufS; i < bufE; i++) colors[i] = null;                     // buffer: off
      for (let i = player.start; i < player.end && i < total; i++) colors[i] = player.color;
    } else if (ambColor) {
      for (let i = 0; i < total; i++) colors[i] = ambColor;
    }

    for (let i = 0; i < total; i++) {
      const lx = padX + i * ledW + ledW / 2;
      const c  = colors[i];
      if (c) {
        const [r, g, b] = c;
        const grd = ctx.createRadialGradient(lx, midY, 0, lx, midY, ledR * 2.4);
        grd.addColorStop(0, `rgba(${r},${g},${b},0.65)`);
        grd.addColorStop(1, "transparent");
        ctx.beginPath(); ctx.arc(lx, midY, ledR * 2.4, 0, Math.PI * 2); ctx.fillStyle = grd; ctx.fill();
        ctx.beginPath(); ctx.arc(lx, midY, ledR, 0, Math.PI * 2); ctx.fillStyle = `rgb(${r},${g},${b})`; ctx.fill();
      } else {
        ctx.beginPath(); ctx.arc(lx, midY, ledR * 0.5, 0, Math.PI * 2); ctx.fillStyle = "#1a2235"; ctx.fill();
      }
    }

    ctx.font = "bold 10px Outfit,sans-serif";
    ctx.textAlign = "center";
    if (roll && _dlData.roll_event) {
      // Roll event label — centered, event color (gold fallback)
      const ec = [255, 200, 40];
      ctx.fillStyle = `rgb(${ec[0]},${ec[1]},${ec[2]})`;
      ctx.fillText(_dlData.roll_event, cssW / 2, midY - ledR - 3);
    } else if (player) {
      // Player name above their segment
      const mid = padX + (player.start + player.end) / 2 * ledW;
      const [r, g, b] = player.color;
      ctx.fillStyle = `rgb(${r},${g},${b})`;
      ctx.fillText(player.name, mid, midY - ledR - 3);
      // Ambient name below the dots when ambient_during_turn is on
      if (ambColor && ambientKey && _dlData.ambient_during_turn !== false) {
        const [ar, ag, ab] = ambColor;
        ctx.font = "9px Outfit,sans-serif";
        ctx.fillStyle = `rgba(${ar},${ag},${ab},0.75)`;
        const label = DL_AMBIENT_LABELS[ambientKey] || (ambientKey.charAt(0).toUpperCase() + ambientKey.slice(1));
        ctx.fillText(label, cssW / 2, midY + ledR + 10);
      }
    } else if (ambColor && ambientKey) {
      // Ambient mode name — centered
      const [r, g, b] = ambColor;
      ctx.fillStyle = `rgba(${r},${g},${b},0.85)`;
      const label = DL_AMBIENT_LABELS[ambientKey] || (ambientKey.charAt(0).toUpperCase() + ambientKey.slice(1));
      ctx.fillText(label, cssW / 2, midY - ledR - 3);
    }
  }

  // ─── Canvas helpers ──────────────────────────────────────────
  function _dlLayout(canvas) {
    const total = _dlData.total_leds || 60;
    const padX = 12, W = canvas.width;
    const ledW = (W - padX * 2) / total;
    const ledR = Math.min(ledW * 0.42, 7);
    const midY = 44;
    return { total, padX, W, ledW, ledR, midY };
  }

  function _dlLedFromX(x, canvas) {
    const { total, padX, ledW } = _dlLayout(canvas);
    return Math.max(0, Math.min(total, Math.floor((x - padX) / ledW)));
  }

  function _dlHitTest(x, canvas) {
    const { padX, ledW } = _dlLayout(canvas);
    const EDGE = Math.max(7, Math.min(ledW * 1.2, 14));
    for (let i = 0; i < (_dlData.corners||[]).length; i++) {
      const cx = padX + _dlData.corners[i] * ledW;
      if (Math.abs(x - cx) <= EDGE) return { type:"corner", index:i };
    }
    for (const p of [...(_dlData.players||[])].reverse()) {
      const x0 = padX + p.start * ledW;
      const x1 = padX + p.end   * ledW;
      if (Math.abs(x - x0) <= EDGE) return { type:"resize-left",  player:p };
      if (Math.abs(x - x1) <= EDGE) return { type:"resize-right", player:p };
      if (x > x0 + EDGE && x < x1 - EDGE) return { type:"move", player:p };
    }
    return null;
  }

  function dlDrawStrip() {
    const canvas = document.getElementById("dl-ds-canvas");
    if (!canvas) return;
    const cssW = canvas.parentElement?.offsetWidth || 600;
    if (canvas.width !== cssW) canvas.width = cssW;
    canvas.height = 70;
    const { total, padX, ledW, ledR, midY } = _dlLayout(canvas);
    const players = _dlData.players || [];
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, 70);
    ctx.fillStyle = "#050709"; ctx.fillRect(0,0,canvas.width,70);

    const ledColors = new Array(total).fill(null);
    players.forEach(p => { for (let i = p.start; i < p.end && i < total; i++) ledColors[i] = p.color; });

    const dragId  = _dlDrag?.player?.id;
    const hoverId = _dlHover?.player?.id;

    players.forEach(p => {
      if (p.end <= p.start) return;
      const x = padX + p.start * ledW, w = (p.end - p.start) * ledW;
      const [r,g,b] = p.color;
      const isDragging = p.id === dragId, isHovered = p.id === hoverId, isActive = _dlData.active_player === p.id;
      const alpha = isDragging ? 0.22 : isHovered ? 0.14 : 0.08;
      ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`;
      ctx.beginPath(); ctx.roundRect(x,20,w,midY-20+ledR+4,4); ctx.fill();
      if (isActive) { ctx.strokeStyle=`rgba(${r},${g},${b},0.5)`; ctx.lineWidth=1.5; ctx.beginPath(); ctx.roundRect(x+1,21,w-2,midY-21+ledR+3,4); ctx.stroke(); }
      const mid = padX + (p.start+p.end)/2*ledW;
      ctx.fillStyle = isActive ? `rgb(${r},${g},${b})` : `rgba(${r},${g},${b},0.85)`;
      ctx.font = `${isActive||isDragging?"bold ":""}11px Outfit,sans-serif`; ctx.textAlign = "center";
      ctx.fillText(p.name, mid, 13);
      if (isDragging) { ctx.fillStyle=`rgba(${r},${g},${b},0.7)`; ctx.font="10px monospace"; ctx.fillText(`${p.start}–${p.end-1}`,mid,24); }
      const hA = (isDragging||isHovered) ? 0.9 : 0.35;
      ctx.fillStyle = `rgba(${r},${g},${b},${hA})`;
      ctx.beginPath(); ctx.roundRect(x-2,midY-ledR-4,4,ledR*2+8,2); ctx.fill();
      ctx.beginPath(); ctx.roundRect(x+w-2,midY-ledR-4,4,ledR*2+8,2); ctx.fill();
    });

    for (let i = 0; i < total; i++) {
      const lx = padX + i*ledW + ledW/2, color = ledColors[i];
      if (color) {
        const [r,g,b] = color;
        const grd = ctx.createRadialGradient(lx,midY,0,lx,midY,ledR*2.5);
        grd.addColorStop(0,`rgba(${r},${g},${b},0.55)`); grd.addColorStop(1,"transparent");
        ctx.beginPath(); ctx.arc(lx,midY,ledR*2.5,0,Math.PI*2); ctx.fillStyle=grd; ctx.fill();
        ctx.beginPath(); ctx.arc(lx,midY,ledR,0,Math.PI*2); ctx.fillStyle=`rgb(${r},${g},${b})`; ctx.fill();
      } else {
        ctx.beginPath(); ctx.arc(lx,midY,ledR*0.55,0,Math.PI*2); ctx.fillStyle="#1a2235"; ctx.fill();
      }
    }

    (_dlData.corners||[]).forEach((ledPos, idx) => {
      const cx = padX + ledPos * ledW;
      const isDragging = _dlCornerDrag?.index === idx;
      const isHovered  = _dlHover?.type === "corner" && _dlHover?.index === idx;
      const a = (isDragging||isHovered) ? 1.0 : 0.72;
      ctx.save(); ctx.strokeStyle=`rgba(201,168,76,${a})`; ctx.lineWidth=isDragging?2:1.5; ctx.setLineDash([4,3]);
      ctx.beginPath(); ctx.moveTo(cx,14); ctx.lineTo(cx,70); ctx.stroke(); ctx.setLineDash([]); ctx.restore();
      ctx.fillStyle=`rgba(201,168,76,${a})`;
      ctx.beginPath(); ctx.moveTo(cx-6,0); ctx.lineTo(cx+6,0); ctx.lineTo(cx,11); ctx.closePath(); ctx.fill();
      ctx.font=`${isDragging?"bold ":""}9px monospace`; ctx.textAlign="center";
      ctx.fillText(`C${idx+1}`,cx,22);
      if (isDragging||isHovered) { ctx.font="8px monospace"; ctx.fillText(ledPos,cx,31); }
    });
  }

  function dlDrawScreen() {
    const canvas = document.getElementById("dl-ds-screen");
    if (!canvas) return;
    const cssW = canvas.parentElement?.offsetWidth || 600;
    if (canvas.width !== cssW) canvas.width = cssW;
    canvas.height = 200;
    const ctx = canvas.getContext("2d");
    const W = canvas.width, H = canvas.height;
    ctx.clearRect(0,0,W,H); ctx.fillStyle="#050709"; ctx.fillRect(0,0,W,H);
    const total = _dlData.total_leds || 60;
    const corners = (_dlData.corners||[]).slice(0,3).map(Number);
    const players = _dlData.players || [];
    if (corners.length < 3) {
      ctx.fillStyle="#3a4560"; ctx.font="12px Outfit,sans-serif"; ctx.textAlign="center";
      ctx.fillText("Drag the 3 corner markers ▼ on the strip above to define the screen layout", W/2, H/2);
      return;
    }
    const [c1,c2,c3] = corners;
    const pad=24, thick=18, rX=pad, rY=pad, rW=W-2*pad, rH=H-2*pad;
    ctx.fillStyle="#111825"; ctx.beginPath(); ctx.roundRect(rX,rY,rW,rH,6); ctx.fill();
    ctx.fillStyle="#0a0d14"; ctx.fillRect(rX+thick,rY+thick,rW-2*thick,rH-2*thick);
    ctx.fillStyle="#1e2535"; ctx.font="13px Outfit,sans-serif"; ctx.textAlign="center";
    ctx.fillText("🖥️  Dungeon Screen", W/2, H/2+5);

    function drawEdgeBand(ledFrom,ledTo,x,y,w,h,horiz,reversed) {
      const count = ledTo-ledFrom; if (count<=0) return;
      ctx.fillStyle="#1a2235"; ctx.fillRect(x,y,w,h);
      players.forEach(p => {
        const s=Math.max(p.start,ledFrom), e=Math.min(p.end,ledTo);
        if (e<=s) return;
        let t0=(s-ledFrom)/count, t1=(e-ledFrom)/count;
        if (reversed) { [t0,t1]=[1-t1,1-t0]; }
        const [r,g,b]=p.color, isActive=_dlData.active_player===p.id;
        ctx.fillStyle=isActive?`rgb(${r},${g},${b})`:`rgba(${r},${g},${b},0.8)`;
        if (horiz) {
          ctx.fillRect(x+t0*w,y,(t1-t0)*w,h);
          if ((t1-t0)*w>18) { ctx.save(); ctx.beginPath(); ctx.rect(x+t0*w+1,y,(t1-t0)*w-2,h); ctx.clip(); ctx.fillStyle="rgba(0,0,0,0.75)"; ctx.font="bold 9px Outfit"; ctx.textAlign="center"; ctx.fillText(p.name,x+(t0+t1)/2*w,y+h/2+3.5); ctx.restore(); }
        } else {
          ctx.fillRect(x,y+t0*h,w,(t1-t0)*h);
          if ((t1-t0)*h>18) { ctx.save(); ctx.beginPath(); ctx.rect(x,y+t0*h+1,w,(t1-t0)*h-2); ctx.clip(); ctx.translate(x+w/2,y+(t0+t1)/2*h); ctx.rotate(-Math.PI/2); ctx.fillStyle="rgba(0,0,0,0.75)"; ctx.font="bold 9px Outfit"; ctx.textAlign="center"; ctx.fillText(p.name,0,3.5); ctx.restore(); }
        }
      });
      ctx.fillStyle="rgba(255,255,255,0.2)"; ctx.font="8px monospace"; ctx.textAlign="center";
      if (horiz) ctx.fillText(count,x+w/2,y+h/2+3);
      else { ctx.save(); ctx.translate(x+w/2,y+h/2); ctx.rotate(-Math.PI/2); ctx.fillText(count,0,3); ctx.restore(); }
    }

    drawEdgeBand(0,c1,   rX+thick,rY,        rW-2*thick,thick, true,  false);
    drawEdgeBand(c1,c2,  rX+rW-thick,rY+thick,thick,rH-2*thick, false, false);
    drawEdgeBand(c2,c3,  rX+thick,rY+rH-thick,rW-2*thick,thick, true,  true);
    drawEdgeBand(c3,total,rX,rY+thick,        thick,rH-2*thick, false, true);

    const GOLD="#c9a84c";
    [[rX,rY],[rX+rW-thick,rY],[rX+rW-thick,rY+rH-thick],[rX,rY+rH-thick]].forEach(([cx,cy]) => {
      ctx.fillStyle="#0a0d14"; ctx.fillRect(cx,cy,thick,thick);
      ctx.beginPath(); ctx.arc(cx+thick/2,cy+thick/2,4,0,Math.PI*2); ctx.fillStyle=GOLD; ctx.fill();
    });
    ctx.fillStyle=GOLD; ctx.font="bold 9px monospace";
    [[rX+thick/2,rY-4,"0","center"],[rX+rW-thick/2,rY-4,`${c1}`,"center"],
     [rX+rW-thick/2,rY+rH+12,`${c2}`,"center"],[rX+thick/2,rY+rH+12,`${c3}`,"center"]
    ].forEach(([lx,ly,txt,align]) => { ctx.textAlign=align; ctx.fillText(txt,lx,ly); });
  }

  function dlInitCanvas() {
    const canvas = document.getElementById("dl-ds-canvas");
    if (!canvas || canvas._dlInited) return;
    canvas._dlInited = true;

    canvas.addEventListener("mousedown", e => {
      const hit = _dlHitTest(e.offsetX, canvas);
      if (!hit) return;
      if (hit.type === "corner") {
        _dlCornerDrag = { index:hit.index, startLed:_dlLedFromX(e.offsetX,canvas), origLed:_dlData.corners[hit.index] };
        canvas.style.cursor = "ew-resize"; e.preventDefault(); return;
      }
      const led = _dlLedFromX(e.offsetX, canvas);
      _dlDrag = { ...hit, startLed:led, origStart:hit.player.start, origEnd:hit.player.end };
      canvas.style.cursor = hit.type === "move" ? "grabbing" : "ew-resize"; e.preventDefault();
    });

    canvas.addEventListener("mousemove", e => {
      if (_dlCornerDrag) {
        const total=_dlData.total_leds||60, corners=_dlData.corners, idx=_dlCornerDrag.index;
        const ledNow=_dlLedFromX(e.offsetX,canvas), delta=ledNow-_dlCornerDrag.startLed;
        const minLed=idx===0?1:corners[idx-1]+1, maxLed=idx===2?total-1:corners[idx+1]-1;
        corners[idx]=Math.max(minLed,Math.min(maxLed,_dlCornerDrag.origLed+delta));
        dlDrawStrip(); dlDrawScreen();
        if (!_dlPreviewTick) { _dlPreviewTick=true; setTimeout(() => { _dlPreviewTick=false; fetch("/dl/api/dungeon-screen/corners-preview",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({corners:_dlData.corners})}); }, 60); }
        return;
      }
      if (!_dlDrag) {
        const hit=_dlHitTest(e.offsetX,canvas), prev=_dlHover; _dlHover=hit;
        if (!hit) canvas.style.cursor="default";
        else if (hit.type==="corner") canvas.style.cursor="ew-resize";
        else if (hit.type==="move")   canvas.style.cursor="grab";
        else                          canvas.style.cursor="ew-resize";
        const pk=prev?.player?.id??prev?.index, hk=hit?.player?.id??hit?.index;
        if (pk!==hk||prev?.type!==hit?.type) dlDrawStrip();
        return;
      }
      const total=_dlData.total_leds||60, ledNow=_dlLedFromX(e.offsetX,canvas), delta=ledNow-_dlDrag.startLed, p=_dlDrag.player, size=_dlDrag.origEnd-_dlDrag.origStart;
      if (_dlDrag.type==="move") { const ns=Math.max(0,Math.min(total-size,_dlDrag.origStart+delta)); p.start=ns; p.end=ns+size; }
      else if (_dlDrag.type==="resize-left") p.start=Math.max(0,Math.min(_dlDrag.origEnd-1,_dlDrag.origStart+delta));
      else p.end=Math.max(_dlDrag.origStart+1,Math.min(total,_dlDrag.origEnd+delta));
      dlDrawStrip(); dlDrawScreen(); dlRenderPlayers();
      if (!_dlPreviewTick) { _dlPreviewTick=true; setTimeout(() => { _dlPreviewTick=false; fetch("/dl/api/dungeon-screen/preview",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({start:p.start,end:p.end,color:p.color})}); }, 60); }
    });

    const onUp = async () => {
      if (_dlCornerDrag) {
        const saved=[..._dlData.corners]; _dlCornerDrag=null; _dlPreviewTick=false;
        canvas.style.cursor="default";
        fetch("/dl/api/dungeon-screen/restore",{method:"POST"});  // re-apply layer state after preview
        dlDrawStrip(); dlDrawScreen();
        const body={..._dlData}; delete body.active_player; delete body.current_ambient; delete body.roll_active;
        await fetch("/dl/api/dungeon-screen",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
        toast(`Corners: LED ${saved.join(", ")}`); return;
      }
      if (!_dlDrag) return;
      const p={..._dlDrag.player}; _dlDrag=null; _dlPreviewTick=false;
      canvas.style.cursor=_dlHover?(_dlHover.type==="move"?"grab":"ew-resize"):"default";
      await fetch(`/dl/api/dungeon-screen/players/${p.id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({start:p.start,end:p.end})});
      fetch("/dl/api/dungeon-screen/restore",{method:"POST"});  // re-apply layer state after preview
      dlDrawScreen(); toast(`${p.name}: LEDs ${p.start}–${p.end-1}`);
    };

    canvas.addEventListener("mouseup", onUp);
    canvas.addEventListener("mouseleave", () => {
      _dlHover=null;
      if (_dlDrag||_dlCornerDrag) onUp(); else dlDrawStrip();
    });
  }

  // ─── DL Players ──────────────────────────────────────────────
  function dlRenderPlayers() {
    const players=_dlData.players||[], activeId=_dlData.active_player;
    const list=document.getElementById("dl-ds-player-list");
    if (!players.length) { list.innerHTML=`<div style="color:var(--text-muted);font-size:.85em;">No seats configured.</div>`; }
    else {
      list.innerHTML=players.map(p => {
        const hex=dlRgbToHex(p.color||[255,215,0]);
        const isActive=activeId===p.id, isSel=_dlSelected===p.id;
        return `<div class="dl-seat${isActive?" seat-active":""}${isSel?" seat-selected":""}" onclick="dlDsSelect('${p.id}')">
          <div class="dl-seat-bar" style="background:${hex}"></div>
          <div class="dl-seat-info"><div class="name">${p.name}${isActive?" ⬅":""}</div>${p.character?`<div class="char">${p.character}</div>`:""}<div class="leds">LEDs ${p.start}–${p.end-1} · ${p.end-p.start} LEDs</div></div>
          <div class="dl-seat-actions" onclick="event.stopPropagation()">
            <button class="btn small" style="background:var(--green-dim);border-color:rgba(52,208,104,.3);color:var(--green);" onclick="dlDsSignal('${p.id}')">▶</button>
            <button class="btn small danger" onclick="dlDsDelete('${p.id}')">✕</button>
          </div>
        </div>`;
      }).join("");
    }
    const combat=document.getElementById("dl-ds-combat");
    combat.innerHTML=players.map(p => {
      const hex=dlRgbToHex(p.color||[255,215,0]), isActive=activeId===p.id;
      return `<button class="btn${isActive?" primary":""}" onclick="dlDsSignal('${p.id}')" style="border-color:${hex};${isActive?`background:${hex}22;`:""}">${p.name}</button>`;
    }).join("")+(players.length?`<button class="btn danger" onclick="dlDsClear()">✕ Clear</button>`:"");
    const clearBtn=document.getElementById("dl-ds-clear-btn");
    if (clearBtn) clearBtn.style.display=activeId?"block":"none";
  }

  async function dlDsSignal(pid) {
    await fetch(`/dl/api/dungeon-screen/signal/${pid}`,{method:"POST"});
    _dlData.active_player=pid; dlRenderPlayers(); dlDrawStrip(); dlDrawScreen();
    const p=(_dlData.players||[]).find(x=>x.id===pid);
    toast(`Signaling: ${p?p.name:pid}`);
  }

  async function dlDsClear() {
    await fetch("/dl/api/dungeon-screen/clear",{method:"POST"});
    _dlData.active_player=null; dlRenderPlayers(); dlDrawStrip(); dlDrawScreen();
    toast("Signal cleared.");
  }

  async function dlDsAddPlayer() {
    const name=document.getElementById("dl-add-name").value.trim();
    const char=document.getElementById("dl-add-char").value.trim();
    const start=parseInt(document.getElementById("dl-add-start").value)||0;
    const end=parseInt(document.getElementById("dl-add-end").value)||5;
    const color=dlHexToRgb(document.getElementById("dl-add-color").value);
    const auto=document.getElementById("dl-add-auto").checked;
    if (!name) { toast("Enter a player name."); return; }
    const players=await fetch("/dl/api/dungeon-screen/players",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name,character:char,start,end,color,auto_signal:auto})}).then(r=>r.json());
    _dlData.players=players;
    document.getElementById("dl-add-name").value="";
    document.getElementById("dl-add-char").value="";
    dlRenderPlayers(); dlDrawStrip(); dlDrawScreen(); toast("Seat added.");
  }

  function dlDsSelect(pid) {
    if (_dlSelected===pid) { dlDsDeselect(); return; }
    _dlSelected=pid;
    const p=(_dlData.players||[]).find(x=>x.id===pid); if (!p) return;
    document.getElementById("dl-edit-name").value  = p.name||"";
    document.getElementById("dl-edit-char").value  = p.character||"";
    document.getElementById("dl-edit-color").value = dlRgbToHex(p.color||[255,215,0]);
    document.getElementById("dl-edit-auto").checked= p.auto_signal!==false;
    document.getElementById("dl-ds-edit-panel").style.display="block";
    dlRenderPlayers();
  }

  function dlDsDeselect() {
    _dlSelected=null;
    document.getElementById("dl-ds-edit-panel").style.display="none";
    dlRenderPlayers();
  }

  async function dlDsSaveEdit() {
    if (!_dlSelected) return;
    const body={
      name:       document.getElementById("dl-edit-name").value.trim(),
      character:  document.getElementById("dl-edit-char").value.trim(),
      color:      dlHexToRgb(document.getElementById("dl-edit-color").value),
      auto_signal:document.getElementById("dl-edit-auto").checked,
    };
    const updated=await fetch(`/dl/api/dungeon-screen/players/${_dlSelected}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}).then(r=>r.json());
    const idx=(_dlData.players||[]).findIndex(p=>p.id===_dlSelected);
    if (idx!==-1) _dlData.players[idx]={..._dlData.players[idx],...updated};
    dlRenderPlayers(); dlDrawStrip(); dlDrawScreen(); toast(`${updated.name} updated.`);
  }

  async function dlDsDelete(pid) {
    const players=await fetch(`/dl/api/dungeon-screen/players/${pid}`,{method:"DELETE"}).then(r=>r.json());
    _dlData.players=players;
    if (_dlData.active_player===pid) _dlData.active_player=null;
    if (_dlSelected===pid) dlDsDeselect();
    dlRenderPlayers(); dlDrawStrip(); dlDrawScreen(); toast("Seat removed.");
  }

  window.addEventListener("resize", () => { if (_activeModule==="dl") { dlDrawStrip(); dlDrawScreen(); } });

  // Initialize DL badge on load
  fetch("/dl/api/config").then(r=>r.json()).then(cfg => dlUpdateBadge(cfg.enabled)).catch(()=>{});

  // ── Task 11: Device picker JS + CRUD ──────────────────────────────────────

  async function devLoadAll() {
    _devList = await fetch("/dl/api/devices").then(r => r.json()).catch(() => []);
    devRenderPicker();
    if (_devList.length > 0) {
      await devSelectDevice(_devSelected && _devList.find(d => d.id === _devSelected) ? _devSelected : _devList[0].id);
    } else {
      _devSelected = null;
      document.getElementById("dev-settings").style.display = "none";
      document.getElementById("dev-subtabs-container").style.display = "none";
      document.getElementById("dev-empty").style.display = "";
      document.getElementById("dev-delete-btn").style.display = "none";
    }
  }

  function devRenderPicker() {
    const picker = document.getElementById("dev-picker");
    picker.innerHTML = _devList.length === 0
      ? `<option value="">-- kein Gerät --</option>`
      : _devList.map(d => `<option value="${d.id}"${d.id === _devSelected ? " selected" : ""}>${d.name}</option>`).join("");
  }

  async function devSelectDevice(id) {
    _devSelected = id;
    const dev = _devList.find(d => d.id === id);
    if (!dev) return;
    document.getElementById("dev-picker").value = id;
    document.getElementById("dev-empty").style.display = "none";
    document.getElementById("dev-settings").style.display = "";
    document.getElementById("dev-subtabs-container").style.display = "";
    document.getElementById("dev-delete-btn").style.display = "";
    // Populate header fields
    _devType = dev.type || "wled";
    document.getElementById("dev-type").value = _devType;
    document.getElementById("dev-ip-wrap").style.display     = _devType === "ha" ? "none" : "";
    document.getElementById("dev-entity-wrap").style.display = _devType === "ha" ? "" : "none";
    document.getElementById("dev-ip").value = dev.ip || "";
    document.getElementById("dev-entity-id").value = dev.entity_id || "";
    document.getElementById("dev-enabled").checked = dev.enabled !== false;
    document.getElementById("dev-bri").value = dev.brightness ?? 180;
    document.getElementById("devBriLbl").textContent = dev.brightness ?? 180;
    // Load sub-tabs
    await Promise.all([devLoadDashboard(), devLoadEvents(), devLoadAmbient()]);
  }

  function devShowAddForm() {
    document.getElementById("dev-add-form").style.display = "";
    document.getElementById("dev-add-name").focus();
  }

  function devHideAddForm() {
    document.getElementById("dev-add-form").style.display = "none";
    document.getElementById("dev-add-name").value = "";
    document.getElementById("dev-add-ip").value = "";
  }

  function devTypeChanged() {
    _devType = document.getElementById("dev-type").value;
    document.getElementById("dev-ip-wrap").style.display     = _devType === "ha" ? "none" : "";
    document.getElementById("dev-entity-wrap").style.display = _devType === "ha" ? "" : "none";
    devSaveHeader();
    devLoadDashboard(); devLoadEvents(); devLoadAmbient();
  }

  async function devAddDevice() {
    const name = document.getElementById("dev-add-name").value.trim();
    const ip   = document.getElementById("dev-add-ip").value.trim();
    if (!name) { toast("Bitte einen Namen eingeben."); return; }
    const r = await fetch("/dl/api/devices", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({name, ip})
    });
    if (!r.ok) { toast("Fehler beim Erstellen."); return; }
    const dev = await r.json();
    _devList.push(dev);
    devHideAddForm();
    devRenderPicker();
    await devSelectDevice(dev.id);
    toast(`Gerät "${dev.name}" hinzugefügt.`);
  }

  async function devDeleteDevice() {
    if (!_devSelected) return;
    const dev = _devList.find(d => d.id === _devSelected);
    if (!dev || !confirm(`Gerät "${dev.name}" wirklich löschen?`)) return;
    const r = await fetch(`/dl/api/devices/${_devSelected}`, {method: "DELETE"});
    if (!r.ok) { toast("Fehler beim Löschen."); return; }
    _devList = _devList.filter(d => d.id !== _devSelected);
    _devSelected = null;
    devRenderPicker();
    toast(`Gerät gelöscht.`);
    await devLoadAll();
  }

  async function devSaveHeader() {
    if (!_devSelected) return;
    const ip       = document.getElementById("dev-ip").value.trim();
    const enabled  = document.getElementById("dev-enabled").checked;
    const brightness = parseInt(document.getElementById("dev-bri").value);
    const entity_id = document.getElementById("dev-entity-id").value.trim();
    await fetch(`/dl/api/devices/${_devSelected}`, {
      method: "PUT", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ip, type: _devType, entity_id, enabled, brightness})
    });
    const dev = _devList.find(d => d.id === _devSelected);
    if (dev) { dev.ip = ip; dev.type = _devType; dev.entity_id = entity_id; dev.enabled = enabled; dev.brightness = brightness; }
  }

  function switchDevTab(tab) {
    ["dashboard","events","ambient"].forEach(t => {
      const view = document.getElementById(`view-dev-${t}`);
      const btn  = document.getElementById(`tab-dev-${t}`);
      if (view) view.style.display = t === tab ? "" : "none";
      if (btn)  btn.classList.toggle("active", t === tab);
    });
  }

  // ── Task 12: Dashboard sub-tab JS ─────────────────────────────────────────

  async function devLoadDashboard() {
    if (!_devSelected) return;
    const data = await fetch(`/dl/api/devices/${_devSelected}/mode`).then(r => r.json()).catch(() => null);
    if (data) _devManualMode = data.manual;
    devUpdateModeUI(_devManualMode);
    // Show correct effect input for device type
    const isHa   = _devType === "ha";
    const fxSel  = document.getElementById("dev-custom-fx");
    const haFxIn = document.getElementById("dev-custom-ha-fx");
    if (fxSel)  fxSel.style.display  = isHa ? "none" : "";
    if (haFxIn) haFxIn.style.display = isHa ? "" : "none";
    if (fxSel && !fxSel.options.length && !isHa) {
      fxSel.innerHTML = DL_EFFECTS.map(([id, name]) => `<option value="${id}">${name}</option>`).join("");
    }
    if (_devManualMode) devRenderDevPresets();
  }

  function devUpdateModeUI(manual) {
    const toggle = document.getElementById("dev-mode-toggle");
    const knob   = document.getElementById("dev-mode-knob");
    const label  = document.getElementById("dev-mode-label");
    const desc   = document.getElementById("dev-mode-desc");
    const autoC  = document.getElementById("dev-auto-content");
    const manC   = document.getElementById("dev-manual-content");
    if (!toggle) return;
    if (manual) {
      toggle.style.background = "#3a1a1a";
      toggle.style.borderColor = "#7a2a2a";
      knob.style.background = "#e55";
      knob.style.left = "4px";
      label.textContent = "Manual";
      desc.textContent = "Automatische Signale pausiert";
      autoC.style.display = "none";
      manC.style.display = "";
      devRenderDevPresets();
    } else {
      toggle.style.background = "#1a3a1a";
      toggle.style.borderColor = "#2a7a2a";
      knob.style.background = "#4c4";
      knob.style.left = "26px";
      label.textContent = "Automatic";
      desc.textContent = "Events laufen automatisch";
      autoC.style.display = "";
      manC.style.display = "none";
    }
  }

  async function devToggleMode() {
    if (!_devSelected) return;
    const r = await fetch(`/dl/api/devices/${_devSelected}/mode`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({manual: !_devManualMode})
    });
    if (!r.ok) return;
    const data = await r.json();
    _devManualMode = data.manual;
    devUpdateModeUI(_devManualMode);
  }

  async function devSyncAmbient() {
    if (!_devSelected) return;
    const btn = document.getElementById("dev-sync-btn");
    btn.disabled = true;
    const r = await fetch(`/dl/api/devices/${_devSelected}/sync-ambient`, {method: "POST"});
    btn.disabled = false;
    if (r.ok) {
      const data = await r.json();
      const msg = data.synced_mode ? `Ambient "${data.synced_mode}" übernommen ✓` : "Ambient-Farben übernommen ✓";
      toast(msg);
      await devLoadAmbient();
    } else {
      toast("Sync fehlgeschlagen.");
    }
  }

  function devRenderDevPresets() {
    const container = document.getElementById("dev-preset-buttons");
    if (!container) return;
    const modes = _devAmbientModes;
    container.innerHTML = Object.keys(modes).map(key =>
      `<button class="btn small${_devActivePreset === key ? ' primary' : ''}"
               onclick="devApplyPreset('${key}')">${key}</button>`
    ).join("") +
    `<button class="btn small" onclick="devManualApply({on:false})">⬛ Off</button>`;
  }

  async function devApplyPreset(key) {
    const m = _devAmbientModes[key];
    if (!m) return;
    _devActivePreset = key;
    devRenderDevPresets();
    // Pre-fill custom editor
    document.getElementById("dev-custom-color").value = dlRgbToHex(m.color || [255, 255, 255]);
    document.getElementById("dev-custom-fx").value = m.fx ?? 0;
    document.getElementById("dev-custom-ha-fx").value = m.ha_effect || "";
    document.getElementById("dev-custom-bri").value = m.bri ?? 180;
    document.getElementById("devCustomBriLbl").textContent = m.bri ?? 180;
    document.getElementById("dev-custom-sx").value = m.sx ?? 128;
    document.getElementById("devCustomSxLbl").textContent = m.sx ?? 128;
    clearTimeout(_devCustomTimer);
    await devManualApply({on: true, color: m.color, fx: m.fx, bri: m.bri, sx: m.sx, ha_effect: m.ha_effect || ""});
  }

  function devCustomChanged() {
    _devActivePreset = null;
    devRenderDevPresets();
    clearTimeout(_devCustomTimer);
    _devCustomTimer = setTimeout(() => {
      const isHa      = _devType === "ha";
      const color     = dlHexToRgb(document.getElementById("dev-custom-color").value);
      const fx        = isHa ? 0 : parseInt(document.getElementById("dev-custom-fx").value);
      const bri       = parseInt(document.getElementById("dev-custom-bri").value);
      const sx        = parseInt(document.getElementById("dev-custom-sx").value);
      const ha_effect = isHa ? (document.getElementById("dev-custom-ha-fx").value || "") : "";
      devManualApply({on: true, color, fx, bri, sx, ha_effect});
    }, 150);
  }

  async function devManualApply(params) {
    if (!_devSelected) return;
    await fetch(`/dl/api/devices/${_devSelected}/manual-apply`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(params)
    });
  }

  // ── Task 13: Events sub-tab JS ────────────────────────────────────────────

  async function devLoadEvents() {
    if (!_devSelected) return;
    _devEvents = await fetch(`/dl/api/devices/${_devSelected}/events`).then(r => r.json()).catch(() => ({}));
    devRenderEvents(_devEvents);
  }

  function devRenderEvents(events) {
    const grid = document.getElementById("dev-event-grid");
    if (!grid) return;
    const effectOpts = DL_EFFECTS.map(([id, name]) => `<option value="${id}">${name}</option>`).join("");
    const isHa = _devType === "ha";
    grid.innerHTML = Object.entries(events).map(([key, ev]) => `
      <div class="dl-event-card" id="dev-ecard-${key}">
        <div class="dl-ev-header">
          <span class="dl-ev-icon">${DL_ICONS[key] || "🎲"}</span>
          <span class="dl-ev-name">${ev.label || key}</span>
          <label class="dl-toggle"><input type="checkbox" id="dev-ev-en-${key}" ${ev.enabled ? "checked" : ""}><div class="dl-toggle-track"></div></label>
        </div>
        <div class="dl-ev-row"><label>Color</label><input type="color" id="dev-ev-col-${key}" value="${dlRgbToHex(ev.color || [255,255,255])}">
          <div style="flex:1"></div><label style="width:auto;margin:0;">Effect</label>
          ${isHa
            ? `<input type="text" id="dev-ev-fx-${key}" placeholder="z.B. colorloop" value="${ev.ha_effect || ''}" style="width:115px;">`
            : `<select id="dev-ev-fx-${key}" style="width:115px;">${effectOpts}</select>`
          }</div>
        <div class="dl-ev-row"><label>Brightness</label>
          <input type="range" id="dev-ev-bri-${key}" min="0" max="255" value="${ev.brightness ?? 200}"
                 oninput="document.getElementById('dev-bv-${key}').textContent=this.value">
          <span class="dl-slider-val" id="dev-bv-${key}">${ev.brightness ?? 200}</span></div>
        <div class="dl-ev-row"><label>Speed</label>
          <input type="range" id="dev-ev-spd-${key}" min="0" max="255" value="${ev.speed ?? 128}"
                 oninput="document.getElementById('dev-sv-${key}').textContent=this.value">
          <span class="dl-slider-val" id="dev-sv-${key}">${ev.speed ?? 128}</span></div>
        <div class="dl-ev-row"><label>Duration</label>
          <input type="number" id="dev-ev-dur-${key}" value="${ev.duration ?? 2000}" min="500" max="10000" step="100" style="width:80px;">
          <span style="font-size:.75em;color:var(--text-muted);">ms</span></div>
      </div>`).join("");
    if (!isHa) {
      Object.entries(events).forEach(([key, ev]) => {
        const sel = document.getElementById(`dev-ev-fx-${key}`);
        if (sel) sel.value = ev.effect ?? 0;
      });
    }
  }

  function devCollectEvents() {
    const isHa = _devType === "ha";
    return Object.fromEntries(Object.entries(_devEvents).map(([key, ev]) => [key, {
      label:      ev.label,
      enabled:    document.getElementById(`dev-ev-en-${key}`)?.checked ?? ev.enabled,
      color:      dlHexToRgb(document.getElementById(`dev-ev-col-${key}`)?.value || "#ffffff"),
      effect:     isHa ? (ev.effect ?? 0) : parseInt(document.getElementById(`dev-ev-fx-${key}`)?.value ?? ev.effect),
      ha_effect:  isHa ? (document.getElementById(`dev-ev-fx-${key}`)?.value || "") : (ev.ha_effect || ""),
      brightness: parseInt(document.getElementById(`dev-ev-bri-${key}`)?.value ?? ev.brightness),
      speed:      parseInt(document.getElementById(`dev-ev-spd-${key}`)?.value ?? ev.speed),
      duration:   parseInt(document.getElementById(`dev-ev-dur-${key}`)?.value ?? ev.duration),
    }]));
  }

  async function devSaveAllEvents() {
    if (!_devSelected) return;
    const events = devCollectEvents();
    // PUT each event individually
    await Promise.all(Object.entries(events).map(([key, ev]) =>
      fetch(`/dl/api/devices/${_devSelected}/events/${key}`, {
        method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(ev)
      })
    ));
    toast("Events gespeichert!");
  }

  // ── Task 14: Ambient sub-tab JS ───────────────────────────────────────────

  async function devLoadAmbient() {
    if (!_devSelected) return;
    const data = await fetch(`/dl/api/devices/${_devSelected}/ambient`).then(r => r.json()).catch(() => null);
    if (!data) return;
    _devAmbientModes    = data.modes || {};
    _devAmbientSelected = data.current || null;
    const isHa = _devType === "ha";
    const fxWrap      = document.getElementById("dev-ambient-fx-wrap");
    const haFxWrap    = document.getElementById("dev-ambient-ha-fx-wrap");
    const addFxWrap   = document.getElementById("dev-add-amb-fx-wrap");
    const addHaFxWrap = document.getElementById("dev-add-amb-ha-fx-wrap");
    if (fxWrap)      fxWrap.style.display      = isHa ? "none" : "";
    if (haFxWrap)    haFxWrap.style.display     = isHa ? "" : "none";
    if (addFxWrap)   addFxWrap.style.display    = isHa ? "none" : "";
    if (addHaFxWrap) addHaFxWrap.style.display  = isHa ? "" : "none";
    devRenderAmbientButtons();
    // Populate add-mode effect dropdown
    const fxSel = document.getElementById("dev-add-amb-fx");
    if (fxSel && !fxSel.options.length) {
      fxSel.innerHTML = DL_EFFECTS.map(([id, name]) => `<option value="${id}">${name}</option>`).join("");
    }
    const editorFx = document.getElementById("dev-ambient-fx");
    if (editorFx && !editorFx.options.length) {
      editorFx.innerHTML = DL_EFFECTS.map(([id, name]) => `<option value="${id}">${name}</option>`).join("");
    }
  }

  function devRenderAmbientButtons() {
    const container = document.getElementById("dev-ambient-btns");
    if (!container) return;
    container.innerHTML = Object.keys(_devAmbientModes).map(key => {
      const active = key === _devAmbientSelected;
      return `<button class="btn small${active ? ' primary' : ''}" onclick="devActivateAmbient('${key}')">${key}
        <span onclick="event.stopPropagation();devDeleteAmbientMode('${key}')"
              style="margin-left:6px;opacity:.5;font-size:.85em;cursor:pointer;">✕</span>
      </button>`;
    }).join("") +
    `<button class="btn small" onclick="devClearAmbient()">⬛ Off</button>`;
  }

  async function devActivateAmbient(key) {
    if (!_devSelected) return;
    const r = await fetch(`/dl/api/devices/${_devSelected}/ambient/${key}`, {method: "POST"});
    if (!r.ok) { toast("Fehler beim Aktivieren."); return; }
    _devAmbientSelected = key;
    devRenderAmbientButtons();
    // Show inline editor
    const m = _devAmbientModes[key];
    document.getElementById("dev-ambient-editor-label").textContent = key;
    document.getElementById("dev-ambient-color").value = dlRgbToHex(m.color || [255, 255, 255]);
    document.getElementById("dev-ambient-fx").value = m.fx ?? 0;
    document.getElementById("dev-ambient-ha-fx").value = m.ha_effect || "";
    document.getElementById("dev-ambient-bri").value = m.bri ?? 150;
    document.getElementById("dev-ambient-sx").value = m.sx ?? 100;
    document.getElementById("dev-ambient-editor").style.display = "";
  }

  async function devClearAmbient() {
    _devAmbientSelected = null;
    devRenderAmbientButtons();
    document.getElementById("dev-ambient-editor").style.display = "none";
    await devManualApply({on: false});
  }

  function devAmbientPatch() {
    if (!_devAmbientSelected) return;
    clearTimeout(_devAmbientPatchTimer);
    _devAmbientPatchTimer = setTimeout(async () => {
      const isHa     = _devType === "ha";
      const color    = dlHexToRgb(document.getElementById("dev-ambient-color").value);
      const fx       = isHa ? 0 : parseInt(document.getElementById("dev-ambient-fx").value);
      const bri      = parseInt(document.getElementById("dev-ambient-bri").value);
      const sx       = parseInt(document.getElementById("dev-ambient-sx").value);
      const ha_effect = isHa ? (document.getElementById("dev-ambient-ha-fx").value || "") : "";
      _devAmbientModes[_devAmbientSelected] = {...(_devAmbientModes[_devAmbientSelected] || {}), color, fx, bri, sx, ha_effect};
      await fetch(`/dl/api/devices/${_devSelected}/ambient/${_devAmbientSelected}`, {
        method: "PUT", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({color, fx, bri, sx, ha_effect})
      });
    }, 400);
  }

  async function devDeleteAmbientMode(key) {
    if (!_devSelected) return;
    if (!confirm(`Ambient-Modus "${key}" löschen?`)) return;
    const r = await fetch(`/dl/api/devices/${_devSelected}/ambient/${key}`, {method: "DELETE"});
    if (!r.ok) { toast("Fehler beim Löschen."); return; }
    delete _devAmbientModes[key];
    if (_devAmbientSelected === key) {
      _devAmbientSelected = null;
      document.getElementById("dev-ambient-editor").style.display = "none";
    }
    devRenderAmbientButtons();
    toast(`Modus "${key}" gelöscht.`);
  }

  async function devAddAmbientMode() {
    if (!_devSelected) return;
    const name = document.getElementById("dev-add-amb-name").value.trim().toLowerCase().replace(/[^a-z0-9_]/g, "");
    if (!name) { toast("Bitte einen Namen eingeben."); return; }
    if (_devAmbientModes[name]) { toast(`Modus "${name}" existiert bereits.`); return; }
    const isHa      = _devType === "ha";
    const color     = dlHexToRgb(document.getElementById("dev-add-amb-color").value);
    const fx        = isHa ? 0 : parseInt(document.getElementById("dev-add-amb-fx").value);
    const bri       = parseInt(document.getElementById("dev-add-amb-bri").value);
    const sx        = parseInt(document.getElementById("dev-add-amb-sx").value);
    const ha_effect = isHa ? (document.getElementById("dev-add-amb-ha-fx").value || "") : "";
    const r = await fetch(`/dl/api/devices/${_devSelected}/ambient/${name}`, {
      method: "PUT", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({color, fx, bri, sx, ha_effect})
    });
    if (!r.ok) { toast("Fehler beim Erstellen."); return; }
    _devAmbientModes[name] = {color, fx, bri, sx, ha_effect};
    devRenderAmbientButtons();
    document.getElementById("dev-add-amb-name").value = "";
    toast(`Modus "${name}" hinzugefügt.`);
  }
