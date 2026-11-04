"""Single-file dashboard client served by jarvis.dashboard at 127.0.0.1.

Pure HTML/CSS/JS in one string - no build step, no external assets, matching
the HUD visual language of the avatar and portal clients.
"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UMBRA - Mission Control</title>
<style>
  :root {
    --bg: #04070c; --panel: rgba(10, 18, 28, 0.72); --cyan: #00e5ff;
    --amber: #ffb300; --dim: #5a7a8a; --text: #b8d8e4; --bad: #ff6b6b;
    --ok: #4ade80;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: radial-gradient(ellipse at 50% -20%, rgba(0, 229, 255, 0.08), transparent 60%), var(--bg);
    color: var(--text);
    font-family: Consolas, "Cascadia Mono", Menlo, monospace;
    min-height: 100vh;
  }
  header {
    display: flex; align-items: center; gap: 12px;
    padding: 12px 18px; border-bottom: 1px solid rgba(0, 229, 255, 0.22);
  }
  .logo { color: var(--cyan); letter-spacing: 0.35em; font-weight: bold; }
  .logo span { color: var(--dim); font-weight: normal; font-size: 12px; }
  .chip {
    border: 1px solid var(--amber); color: var(--amber);
    padding: 2px 10px; border-radius: 10px; font-size: 11px; letter-spacing: 0.15em;
  }
  nav { display: flex; gap: 4px; padding: 8px 18px; border-bottom: 1px solid rgba(0, 229, 255, 0.12); overflow-x: auto; }
  nav button {
    background: none; border: 1px solid transparent; color: var(--dim);
    padding: 6px 14px; cursor: pointer; font: inherit; letter-spacing: 0.12em;
  }
  nav button.active { color: var(--cyan); border-color: rgba(0, 229, 255, 0.4); background: rgba(0, 229, 255, 0.06); }
  main { padding: 18px; max-width: 980px; margin: 0 auto; }
  section { display: none; }
  section.active { display: block; }
  .card {
    border: 1px solid rgba(0, 229, 255, 0.18); background: var(--panel);
    border-radius: 8px; padding: 14px; margin-bottom: 14px;
  }
  .card h3 { color: var(--amber); font-size: 12px; letter-spacing: 0.25em; margin-bottom: 10px; }
  #chatlog { height: 46vh; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
  .msg {
    max-width: 85%; padding: 8px 12px; border-radius: 8px;
    white-space: pre-wrap; word-break: break-word; font-size: 14px;
  }
  .msg.user { align-self: flex-end; border: 1px solid rgba(0, 229, 255, 0.4); background: rgba(0, 229, 255, 0.08); }
  .msg.bot { align-self: flex-start; border: 1px solid rgba(90, 122, 138, 0.4); background: rgba(90, 122, 138, 0.08); }
  .msg.err { color: var(--bad); border-color: rgba(255, 107, 107, 0.4); }
  input, select, textarea {
    background: #0a121c; border: 1px solid rgba(0, 229, 255, 0.3);
    color: var(--text); padding: 8px 10px; font: inherit; border-radius: 4px; width: 100%;
  }
  .row { display: flex; gap: 8px; margin-top: 10px; }
  button.act {
    background: rgba(0, 229, 255, 0.1); color: var(--cyan);
    border: 1px solid rgba(0, 229, 255, 0.5); padding: 8px 16px;
    cursor: pointer; font: inherit; border-radius: 4px; letter-spacing: 0.1em; white-space: nowrap;
  }
  button.act:hover { background: rgba(0, 229, 255, 0.2); }
  button.mini {
    background: none; color: var(--dim); border: 1px solid rgba(90, 122, 138, 0.4);
    border-radius: 4px; cursor: pointer; font: inherit; font-size: 11px; padding: 2px 8px;
  }
  button.mini:hover { color: var(--cyan); border-color: var(--cyan); }
  .pre { white-space: pre-wrap; font-size: 13px; line-height: 1.55; color: #9fd6e4; }
  .item {
    display: flex; justify-content: space-between; gap: 8px; align-items: center;
    border-bottom: 1px dashed rgba(90, 122, 138, 0.25); padding: 7px 2px; font-size: 13px;
  }
  .cols { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
  .colcard { border: 1px solid rgba(0, 229, 255, 0.18); border-radius: 8px; padding: 10px; min-height: 160px; }
  .colcard h4 { color: var(--cyan); letter-spacing: 0.2em; font-size: 12px; margin-bottom: 8px; }
  .task {
    background: rgba(10, 18, 28, 0.9); border: 1px solid rgba(90, 122, 138, 0.3);
    border-radius: 6px; padding: 7px 9px; margin-bottom: 7px; font-size: 13px;
    display: flex; justify-content: space-between; gap: 6px; align-items: center;
  }
  .muted { color: var(--dim); font-size: 12px; }
  .toast {
    position: fixed; bottom: 18px; right: 18px; padding: 10px 16px;
    border: 1px solid var(--cyan); background: rgba(10, 18, 28, 0.95); color: var(--cyan);
    border-radius: 6px; font-size: 13px; display: none; max-width: 380px;
  }
  .toast.show { display: block; }
  .toast.bad { border-color: var(--bad); color: var(--bad); }
  .kicker { color: var(--dim); font-size: 11px; letter-spacing: 0.2em; margin: 10px 0 4px; }
</style>
</head>
<body>
<header>
  <div class="logo">UMBRA <span>// MISSION CONTROL</span></div>
  <div style="margin-left:auto; display:flex; gap:10px; align-items:center;">
    <span id="tier" class="chip">...</span>
    <span id="ver" class="muted"></span>
  </div>
</header>
<nav id="tabs">
  <button data-tab="chat" class="active">CHAT</button>
  <button data-tab="health">THE ORACLE</button>
  <button data-tab="memory">MEMORY</button>
  <button data-tab="board">BOARD</button>
  <button data-tab="watch">WATCHTOWER</button>
  <button data-tab="settings">SETTINGS</button>
</nav>
<main>
  <section id="tab-chat" class="active">
    <div class="card">
      <h3>CONSOLE</h3>
      <div id="chatlog"></div>
      <div class="row">
        <input id="chatinput" placeholder="Speak, Sir... (Enter to send)" autocomplete="off">
        <button class="act" onclick="sendChat()">SEND</button>
      </div>
    </div>
    <div class="card">
      <h3>PAST SESSIONS</h3>
      <div id="sessions" class="muted">loading...</div>
    </div>
  </section>

  <section id="tab-health">
    <div class="card">
      <h3>THE ORACLE - RISK SCREENING</h3>
      <div id="healthpre" class="pre">loading...</div>
    </div>
  </section>

  <section id="tab-memory">
    <div class="card">
      <h3>SECOND BRAIN</h3>
      <div class="row"><input id="meminput" placeholder="Commit a fact to memory..." autocomplete="off"><button class="act" onclick="saveMemory()">SAVE</button></div>
      <div id="memlist" style="margin-top:10px">loading...</div>
    </div>
  </section>

  <section id="tab-board">
    <div class="card">
      <h3>KANBAN</h3>
      <div class="row"><input id="boardinput" placeholder="New task..." autocomplete="off"><button class="act" onclick="addTask()">ADD</button></div>
      <div class="cols" id="boardcols" style="margin-top:12px">
        <div class="colcard"><h4>TO DO</h4><div id="col-todo"></div></div>
        <div class="colcard"><h4>DOING</h4><div id="col-doing"></div></div>
        <div class="colcard"><h4>DONE</h4><div id="col-done"></div></div>
      </div>
    </div>
  </section>

  <section id="tab-watch">
    <div class="card">
      <h3>WATCHTOWER RULES</h3>
      <div id="watchlist">loading...</div>
      <div class="kicker">NEW RULE</div>
      <div class="row">
        <select id="watchkind" onchange="watchFields()">
          <option value="vitals">vitals</option>
          <option value="folder">folder</option>
          <option value="health">health</option>
        </select>
      </div>
      <div id="watchvitals" class="row" style="display:none">
        <select id="watchsignal" style="width:auto">
          <option value="cpu">cpu %</option>
          <option value="ram">ram %</option>
          <option value="disk_used">disk used %</option>
          <option value="battery">battery %</option>
        </select>
        <select id="watchop" style="width:auto"><option>&gt;</option><option>&lt;</option></select>
        <input id="watchvalue" placeholder="value" style="width:120px">
      </div>
      <div id="watchfolder" class="row" style="display:none"><input id="watchpath" placeholder="folder path to watch"></div>
      <div class="row"><button class="act" onclick="addWatch()">ADD RULE</button></div>
      <div class="muted" style="margin-top:8px">Rules are evaluated by the sentinel daemon each cycle.</div>
    </div>
  </section>

  <section id="tab-settings">
    <div class="card">
      <h3>BRAIN</h3>
      <div class="muted" style="margin-bottom:8px">OpenAI-compatible endpoint. Leave the key blank to keep the stored one.</div>
      <div class="row"><input id="setprovider" placeholder="provider (zai, openai, zhipu, gemini, ollama, custom)"></div>
      <div class="row"><input id="setbaseurl" placeholder="base url"></div>
      <div class="row"><input id="setmodel" placeholder="model"></div>
      <div class="row"><input id="setkey" type="password" placeholder="api key (blank keeps current)"></div>
      <div class="row"><button class="act" onclick="saveSettings()">SAVE BRAIN</button></div>
      <div id="setmsg" class="muted"></div>
    </div>
    <div class="card">
      <h3>PRO LICENSE</h3>
      <div class="row"><input id="lickey" placeholder="UMBRA-... key"></div>
      <div class="row"><button class="act" onclick="activateLicense()">ACTIVATE</button></div>
      <div id="licmsg" class="muted"></div>
    </div>
  </section>
</main>
<div id="toast"></div>
<script>
"use strict";
var $ = function (id) { return document.getElementById(id); };
function esc(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}
function toast(msg, bad) {
  var t = $("toast");
  t.textContent = msg;
  t.className = "toast show" + (bad ? " bad" : "");
  setTimeout(function () { t.className = "toast"; }, 2800);
}
function api(path, body) {
  var opt = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  };
  return fetch(path, opt).then(function (r) {
    return r.text().then(function (t) {
      var data;
      try { data = JSON.parse(t); } catch (e) { data = { raw: t }; }
      return { ok: r.ok, data: data };
    });
  });
}

/* tabs */
var TAB_LOADERS = {
  chat: loadSessions, health: loadHealth, memory: loadMemory,
  board: loadBoard, watch: loadWatch, settings: loadSettings
};
document.querySelectorAll("nav button").forEach(function (btn) {
  btn.addEventListener("click", function () {
    document.querySelectorAll("nav button").forEach(function (b) { b.classList.remove("active"); });
    btn.classList.add("active");
    document.querySelectorAll("main section").forEach(function (s) { s.classList.remove("active"); });
    $("tab-" + btn.dataset.tab).classList.add("active");
    TAB_LOADERS[btn.dataset.tab]();
  });
});

/* chat */
function addMsg(role, text) {
  var div = document.createElement("div");
  div.className = "msg " + (role === "user" ? "user" : text.indexOf("ERROR:") === 0 ? "bot err" : "bot");
  div.textContent = text;
  $("chatlog").appendChild(div);
  $("chatlog").scrollTop = $("chatlog").scrollHeight;
}
function sendChat() {
  var input = $("chatinput");
  var text = input.value.trim();
  if (!text) return;
  input.value = "";
  addMsg("user", text);
  api("/api/chat", { text: text }).then(function (res) {
    addMsg("bot", res.data.reply || "ERROR: empty reply");
  }).catch(function (e) { addMsg("bot", "ERROR: " + e); });
}
$("chatinput").addEventListener("keydown", function (e) { if (e.key === "Enter") sendChat(); });

function loadSessions() {
  api("/api/history").then(function (res) {
    var rows = (res.data.sessions || []).map(function (s) {
      return '<div class="item"><span>#' + esc(s.id) + " " + esc(s.title || "(untitled)") +
        '</span><span class="muted">' + esc(s.turns) + " turns - " + esc(String(s.started_at || "").slice(0, 16)) + "</span></div>";
    });
    $("sessions").innerHTML = rows.length ? rows.join("") : "No sessions yet.";
  });
}

/* oracle */
function loadHealth() {
  $("healthpre").textContent = "loading...";
  api("/api/health").then(function (res) { $("healthpre").textContent = res.data.raw || res.data; });
}

/* memory */
function loadMemory() {
  api("/api/memory").then(function (res) {
    var rows = (res.data.memories || []).map(function (m) {
      return '<div class="item"><span>' + esc(m.content) +
        '</span><span><button class="mini" onclick="forgetMemory(' + esc(m.id) + ')">FORGET</button></span></div>';
    });
    $("memlist").innerHTML = rows.length ? rows.join("") : "Memory is empty.";
  });
}
function saveMemory() {
  var note = $("meminput").value.trim();
  if (!note) return;
  $("meminput").value = "";
  api("/api/memory/save", { note: note }).then(function (res) {
    toast(res.ok ? "Committed to memory." : "Save failed.");
    loadMemory();
  });
}
function forgetMemory(id) {
  api("/api/memory/forget", { id: id }).then(function () { loadMemory(); });
}

/* board */
function loadBoard() {
  api("/api/kanban").then(function (res) {
    var tasks = res.data.tasks || [];
    ["todo", "doing", "done"].forEach(function (col) {
      var inCol = tasks.filter(function (t) { return t.column === col; });
      $("col-" + col).innerHTML = inCol.length ? inCol.map(function (t) {
        return '<div class="task"><span>' + esc(t.text) + '</span>' +
          '<button class="mini" onclick="cycleTask(' + esc(t.id) + ')">&#9654;</button></div>';
      }).join("") : '<div class="muted">-</div>';
    });
  });
}
function addTask() {
  var text = $("boardinput").value.trim();
  if (!text) return;
  $("boardinput").value = "";
  api("/api/kanban", { action: "add", text: text }).then(loadBoard);
}
function cycleTask(id) {
  api("/api/kanban", { action: "cycle", id: id }).then(loadBoard);
}

/* watchtower */
function describeRule(r) {
  if (r.kind === "vitals") return "vitals: " + r.signal + " " + r.op + " " + r.value;
  if (r.kind === "folder") return "folder: " + r.path;
  if (r.kind === "health") return "health: band shift";
  return JSON.stringify(r);
}
function loadWatch() {
  api("/api/watch").then(function (res) {
    var rows = (res.data.rules || []).map(function (r) {
      return '<div class="item"><span>' + esc(describeRule(r)) +
        '</span><span><button class="mini" onclick="removeWatch(' + esc(r.id) + ')">REMOVE</button></span></div>';
    });
    $("watchlist").innerHTML = rows.length ? rows.join("") : "No rules armed.";
  });
}
function watchFields() {
  var kind = $("watchkind").value;
  $("watchvitals").style.display = kind === "vitals" ? "flex" : "none";
  $("watchfolder").style.display = kind === "folder" ? "flex" : "none";
}
function addWatch() {
  var kind = $("watchkind").value;
  var rule;
  if (kind === "vitals") {
    rule = { kind: "vitals", signal: $("watchsignal").value, op: $("watchop").value, value: parseFloat($("watchvalue").value) };
    if (isNaN(rule.value)) { toast("Enter a numeric value.", true); return; }
  } else if (kind === "folder") {
    rule = { kind: "folder", path: $("watchpath").value.trim() };
    if (!rule.path) { toast("Enter a folder path.", true); return; }
  } else {
    rule = { kind: "health" };
  }
  api("/api/watch", { action: "add", rule: rule }).then(function (res) {
    toast(res.ok ? "Rule armed." : "Add failed.");
    loadWatch();
  });
}
function removeWatch(id) {
  api("/api/watch", { action: "remove", id: id }).then(loadWatch);
}

/* settings */
function loadSettings() {
  api("/api/settings").then(function (res) {
    var d = res.data;
    $("setprovider").value = d.provider || "";
    $("setbaseurl").value = d.baseUrl || "";
    $("setmodel").value = d.model || "";
    $("setkey").value = "";
    $("setmsg").textContent = d.hasKey ? "A key is stored." : "No key stored yet.";
  });
}
function saveSettings() {
  var payload = {
    provider: $("setprovider").value.trim(),
    baseUrl: $("setbaseurl").value.trim(),
    model: $("setmodel").value.trim(),
    apiKey: $("setkey").value.trim()
  };
  api("/api/settings", payload).then(function (res) {
    $("setmsg").textContent = res.ok ? "Saved - brain reloaded." : "Save failed.";
    if (res.ok) refreshState();
  });
}
function activateLicense() {
  var key = $("lickey").value.trim();
  if (!key) return;
  api("/api/license/activate", { key: key }).then(function (res) {
    $("licmsg").textContent = res.data.message || "";
    $("licmsg").className = res.ok ? "muted ok" : "muted bad";
    if (res.ok) { $("lickey").value = ""; refreshState(); }
  });
}

function refreshState() {
  api("/api/state").then(function (res) {
    var d = res.data;
    $("ver").textContent = "v" + d.version;
    $("tier").textContent = (d.tier === "pro" ? "PRO" : "LITE") + (d.hasKey ? "" : " - NO KEY");
  });
}

/* boot */
addMsg("bot", "UMBRA mission control online, Sir. Bound to this machine only.");
refreshState();
loadSessions();
</script>
</body>
</html>
"""
