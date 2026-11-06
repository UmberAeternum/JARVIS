"""Single-file dashboard client served by jarvis.dashboard at 127.0.0.1.

Pure HTML/CSS/JS in one string - no build step, no external assets, matching
the HUD visual language of the avatar and portal clients.
"""

PAGE = r"""<!doctype html>
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
  #tiercards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
  .tiercard { border: 1px solid rgba(0, 229, 255, 0.18); border-radius: 8px; padding: 10px; text-align: center; }
  .tiercard.on { border-color: rgba(74, 222, 128, 0.45); }
  .tiercard h4 { color: var(--cyan); letter-spacing: 0.2em; font-size: 11px; margin-bottom: 6px; }
  .tiercard .state { font-size: 13px; font-weight: bold; }
  button.act.danger { border-color: rgba(255, 107, 107, 0.6); color: var(--bad); }
  button.act.danger:hover { background: rgba(255, 107, 107, 0.15); }
  .muted { color: var(--dim); font-size: 12px; }
  .toast {
    position: fixed; bottom: 18px; right: 18px; padding: 10px 16px;
    border: 1px solid var(--cyan); background: rgba(10, 18, 28, 0.95); color: var(--cyan);
    border-radius: 6px; font-size: 13px; display: none; max-width: 380px;
  }
  .toast.show { display: block; }
  .toast.bad { border-color: var(--bad); color: var(--bad); }
  .kicker { color: var(--dim); font-size: 11px; letter-spacing: 0.2em; margin: 10px 0 4px; }
  .statusline { color: var(--dim); font-size: 11px; padding: 1px 4px; align-self: flex-start; }
  .msg.streaming { opacity: 0.85; }
  .mini.on { color: var(--ok); border-color: rgba(74, 222, 128, 0.5); }
  .confirm {
    align-self: stretch; border: 1px solid var(--amber); border-radius: 8px;
    background: rgba(255, 179, 0, 0.07); padding: 10px 12px; margin: 4px 0;
  }
  .confirm .ctext { color: var(--amber); font-size: 13px; white-space: pre-wrap; word-break: break-word; }
  .confirm .cbtns { display: flex; gap: 8px; margin-top: 8px; }
  .confirm .yes { border-color: rgba(74, 222, 128, 0.6); color: var(--ok); }
  .confirm .no { border-color: rgba(255, 107, 107, 0.6); color: var(--bad); }
  #scanlines { position: fixed; inset: 0; pointer-events: none; opacity: .05; display: none;
    background: repeating-linear-gradient(0deg, transparent 0 2px, #00e5ff 2px 3px); }
  body.minimal #scanlines { display: none !important; }
  #boot { position: fixed; inset: 0; background: var(--bg); z-index: 50; display: flex;
    align-items: center; justify-content: center; color: var(--cyan); font-size: 14px;
    letter-spacing: .25em; }
  #vitals { display: flex; gap: 16px; align-items: center; padding: 8px 18px;
    border-bottom: 1px solid rgba(0, 229, 255, .08); font-size: 11px; color: var(--dim); }
  .ring { width: 54px; height: 54px; border-radius: 50%; display: flex; align-items: center;
    justify-content: center; color: var(--cyan); font-size: 11px; }
  .ring small { color: var(--dim); font-size: 9px; letter-spacing: .1em; }
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
  <button data-tab="trust">TRUST</button>
  <button data-tab="settings">SETTINGS</button>
</nav>
<div id="scanlines"></div>
<div id="boot">SYSTEMS ONLINE</div>
<div id="vitals" style="max-width:980px; margin:0 auto; border:1px solid rgba(0,229,255,.18); border-radius:8px;"></div>
<main>
  <section id="tab-chat" class="active">
    <div class="card">
      <h3>CONSOLE - FULL AGENT</h3>
      <div class="muted" style="margin-bottom:8px">All tools live. Dangerous actions ask here, as APPROVE/DENY. Every turn is logged to your local conversation store. SPEAK uses your browser's own voice - on-device only.</div>
      <div id="chatlog"></div>
      <div class="row">
        <input id="chatinput" placeholder="Command the agent, Sir... (Enter to send)" autocomplete="off">
        <button class="act" onclick="sendChat()">SEND</button>
        <button id="speakbtn" class="mini" onclick="toggleSpeak()">SPEAK: OFF</button>
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

  <section id="tab-trust">
    <div class="card">
      <h3>ACCESS TIERS</h3>
      <div class="muted" style="margin-bottom:8px">What the agent may reach right now. Grants expire on their own - and die instantly when you say so. New grants require the typed phrase in the CLI; this page can only take them away.</div>
      <div id="tiercards">loading...</div>
      <div class="row" style="align-items:center">
        <button class="act danger" onclick="revokeAll()">REVOKE ALL</button>
        <span id="integrity" class="chip">LEDGER: ...</span>
      </div>
    </div>
    <div class="card">
      <h3>PRIVACY METER</h3>
      <div id="privacy" class="pre">loading...</div>
    </div>
    <div class="card">
      <h3>ACTION LOG</h3>
      <div class="muted" style="margin-bottom:8px">The tamper-evident ledger - last 20 entries, newest first, refreshed live.</div>
      <div id="trustlog" class="pre">loading...</div>
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
  board: loadBoard, watch: loadWatch, trust: loadTrust, settings: loadSettings
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

/* chat - full agent with events + approvals (Mark XXI) */
function addMsg(role, text) {
  var div = document.createElement("div");
  div.className = "msg " + (role === "user" ? "user" : text.indexOf("ERROR:") === 0 ? "bot err" : "bot");
  div.textContent = text;
  $("chatlog").appendChild(div);
  $("chatlog").scrollTop = $("chatlog").scrollHeight;
}
function addStatus(text) {
  var div = document.createElement("div");
  div.className = "statusline";
  div.textContent = ">> " + text;
  $("chatlog").appendChild(div);
  $("chatlog").scrollTop = $("chatlog").scrollHeight;
}
function showConfirm(id, description) {
  if (document.getElementById("confirm-" + id)) return;
  var banner = document.createElement("div");
  banner.className = "confirm";
  banner.id = "confirm-" + id;
  var label = document.createElement("div");
  label.className = "ctext";
  label.textContent = description;
  var btns = document.createElement("div");
  btns.className = "cbtns";
  var yes = document.createElement("button");
  yes.className = "act yes";
  yes.textContent = "APPROVE";
  yes.onclick = function () { answerConfirm(id, true); };
  var no = document.createElement("button");
  no.className = "act no";
  no.textContent = "DENY";
  no.onclick = function () { answerConfirm(id, false); };
  btns.appendChild(yes);
  btns.appendChild(no);
  banner.appendChild(label);
  banner.appendChild(btns);
  $("chatlog").appendChild(banner);
  $("chatlog").scrollTop = $("chatlog").scrollHeight;
}
function answerConfirm(id, approved) {
  var banner = document.getElementById("confirm-" + id);
  if (banner) banner.remove();
  api("/api/confirm", { confirm_id: id, approved: approved });
}
/* Mark XXIX - HUD: status ring, typed replies, sound cues, theme, boot */
var hud = { theme: "hologram", sound: true, typed: true, boot: true };
var audioCtx = null;
function cue(kind) {
  if (!hud.sound) return;
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    var osc = audioCtx.createOscillator(), gain = audioCtx.createGain();
    osc.frequency.value = kind === "confirm" ? 880 : kind === "reply" ? 660 : 440;
    gain.gain.value = 0.04;
    osc.connect(gain); gain.connect(audioCtx.destination);
    osc.start(); osc.stop(audioCtx.currentTime + (kind === "confirm" ? 0.12 : 0.07));
  } catch (e) { /* audio is cosmetic */ }
}
function ringHtml(label, pct, suffix) {
  var p = Math.max(0, Math.min(100, pct));
  return '<div class="ring" style="background:conic-gradient(var(--cyan) ' + p + '%, rgba(0,229,255,.12) 0);">' +
    '<div style="width:44px;height:44px;border-radius:50%;background:var(--bg);display:flex;' +
    'flex-direction:column;align-items:center;justify-content:center;">' + Math.round(p) + suffix +
    '<small>' + label + '</small></div></div>';
}
function refreshVitals() {
  api("/api/vitals").then(function (res) {
    if (!res.ok) return;
    var v = res.data.vitals || {};
    var parts = [];
    if (typeof v.cpu === "number") parts.push(ringHtml("CPU", v.cpu, "%"));
    if (typeof v.ram === "number") parts.push(ringHtml("RAM", v.ram, "%"));
    if (typeof v.battery === "number") parts.push(ringHtml("PWR", v.battery, "%"));
    parts.push('<div class="ring" style="border:1px solid rgba(255,179,0,.5); color:var(--amber);">' +
      '<div style="text-align:center;"><div style="font-size:12px;">' + (res.data.tier || "").toUpperCase() +
      '</div><small>TIER</small></div></div>');
    $("vitals").innerHTML = parts.join("");
  }).catch(function () { /* cosmetic */ });
}
function typedReply(text) {
  var div = document.createElement("div");
  div.className = "msg bot";
  $("chatlog").appendChild(div);
  var i = 0;
  var timer = setInterval(function () {
    i = Math.min(text.length, i + 4);
    div.textContent = text.slice(0, i) + (i < text.length ? " ▌" : "");
    $("chatlog").scrollTop = $("chatlog").scrollHeight;
    if (i >= text.length) clearInterval(timer);
  }, 14);
  $("chatlog").scrollTop = $("chatlog").scrollHeight;
}
function applyHud() {
  document.body.classList.toggle("minimal", hud.theme === "minimal");
  $("scanlines").style.display = hud.theme === "hologram" ? "block" : "none";
}

/* Mark XXIII - the living reply: streaming bubble + on-device speech */
var streamingEl = null;
function finishStreaming() {
  if (streamingEl) { streamingEl.remove(); streamingEl = null; }
}
var speakOn = false;
try { speakOn = localStorage.getItem("umbra-speak") === "1"; } catch (e) {}
function toggleSpeak() {
  speakOn = !speakOn;
  try { localStorage.setItem("umbra-speak", speakOn ? "1" : "0"); } catch (e) {}
  var b = $("speakbtn");
  b.textContent = speakOn ? "SPEAK: ON" : "SPEAK: OFF";
  b.className = "mini" + (speakOn ? " on" : "");
  if (!speakOn && window.speechSynthesis) speechSynthesis.cancel();
}
function stripMarkdown(text) {
  var out = String(text);
  out = out.replace(/```[\s\S]*?```/g, " code block omitted. ");
  out = out.replace(/`([^`]*)`/g, "$1");
  out = out.replace(/!?\[([^\]]*)\]\(([^)]*)\)/g, "$1");
  out = out.replace(/(\*\*|__)(.*?)\1/g, "$2");
  out = out.replace(/(\*|_)([^*_]+)\1/g, "$2");
  out = out.replace(/^#{1,6}\s+/gm, "");
  return out;
}
function speak(text) {
  if (!window.speechSynthesis) return;
  var utterance = new SpeechSynthesisUtterance(stripMarkdown(text).slice(0, 600));
  speechSynthesis.speak(utterance);
}
function applyEvent(ev) {
  if (ev.type === "user") { finishStreaming(); addMsg("user", ev.text); }
  else if (ev.type === "partial") {
    if (!streamingEl) {
      streamingEl = document.createElement("div");
      streamingEl.className = "msg bot streaming";
      $("chatlog").appendChild(streamingEl);
    }
    streamingEl.textContent = ev.text + " ▌";
    $("chatlog").scrollTop = $("chatlog").scrollHeight;
  }
  else if (ev.type === "reply") {
    finishStreaming();
    if (hud.typed && ev.text.indexOf("ERROR:") !== 0) { typedReply(ev.text); }
    else { addMsg("bot", ev.text); }
    cue("reply");
    if (speakOn && ev.text.indexOf("ERROR:") !== 0) speak(ev.text);
  }
  else if (ev.type === "status") addStatus(ev.text);
  else if (ev.type === "confirm_request") showConfirm(ev.confirm_id, ev.description);
}
var lastEvent = 0;
function pollEvents() {
  api("/api/events?since=" + lastEvent).then(function (res) {
    var events = res.data.events || [];
    for (var i = 0; i < events.length; i++) applyEvent(events[i]);
    if (events.length) lastEvent = events[events.length - 1].id;
    setTimeout(pollEvents, 400);
  }).catch(function () { setTimeout(pollEvents, 1500); });
}
function sendChat() {
  var input = $("chatinput");
  var text = input.value.trim();
  if (!text) return;
  input.value = "";
  api("/api/chat", { text: text }).then(function (res) {
    if (!res.ok) toast(res.data.error || "turn refused", true);
  }).catch(function (e) { toast("ERROR: " + e, true); });
}
$("chatinput").addEventListener("keydown", function (e) { if (e.key === "Enter") sendChat(); });

function loadSessions() {
  api("/api/history").then(function (res) {
    var rows = (res.data.sessions || []).map(function (s) {
      return '<div class="item"><span>#' + esc(s.id) + " " + esc(s.title || "(untitled)") +
        '</span><span class="muted">' + esc(s.turns) + " turns - " + esc(String(s.started_at || "").slice(0, 16)) +
        ' <button class="mini" onclick="resumeSession(' + esc(s.id) + ')">RESUME</button></span></div>';
    });
    $("sessions").innerHTML = rows.length ? rows.join("") : "No sessions yet.";
  });
}
function resumeSession(id) {
  api("/api/resume", { id: id }).then(function (res) {
    if (res.ok) {
      addStatus("resumed session #" + id + " - " + res.data.messages + " messages back in context, Sir");
      toast("Session #" + id + " loaded into the console.");
    } else {
      toast(res.data.error || "resume failed", true);
    }
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

/* trust (Phase 7) - grants, revoke, ledger, privacy */
var trustTimer = null;
function loadTrust() {
  refreshAccess();
  refreshPrivacy();
  if (!trustTimer) trustTimer = setInterval(function () {
    var active = document.querySelector("main section.active");
    if (active && active.id === "tab-trust") { refreshAccess(); refreshPrivacy(); }
  }, 5000);
}
function countdown(expiresTs) {
  var left = Math.max(0, Math.round(expiresTs - Date.now() / 1000));
  var h = Math.floor(left / 3600), m = Math.floor((left % 3600) / 60), s = left % 60;
  return "expires in " + (h ? h + "h " : "") + (m ? m + "m " : "") + s + "s";
}
function refreshAccess() {
  api("/api/access").then(function (res) {
    if (!res.ok) return;
    var names = { observe: "OBSERVE", assist: "ASSIST", act: "ACT", install: "INSTALL" };
    var cards = [];
    Object.keys(names).forEach(function (tier) {
      var info = (res.data.tiers || {})[tier] || {};
      var state = info.granted
        ? '<div class="state" style="color:var(--ok)">GRANTED</div>' +
          '<div class="muted">' + esc(countdown(info.expires_ts || 0)) + '</div>'
        : '<div class="state" style="color:var(--dim)">NOT GRANTED</div>' +
          '<div class="muted">denied by default</div>';
      cards.push('<div class="tiercard' + (info.granted ? " on" : "") + '"><h4>' + names[tier] +
        '</h4>' + state + '</div>');
    });
    $("tiercards").innerHTML = cards.join("");
    var ok = res.data.integrity === "OK";
    var chip = $("integrity");
    chip.textContent = "LEDGER: " + (ok ? "OK" : "TAMPERED");
    chip.style.borderColor = ok ? "var(--ok)" : "var(--bad)";
    chip.style.color = ok ? "var(--ok)" : "var(--bad)";
    var rows = (res.data.log_tail || []).map(function (e) {
      return esc(e.ts || "?") + "  " + esc(e.action) + "  [" + esc(e.actor) + "]  " +
        esc(e.detail) + (e.integrity === "ok" ? "" : "  <<TAMPERED>>");
    });
    $("trustlog").textContent = rows.length ? rows.join("\n") : "The ledger is empty.";
  });
}
function refreshPrivacy() {
  api("/api/privacy").then(function (res) {
    if (!res.ok) return;
    var d = res.data;
    var total = (d.local_calls || 0) + (d.cloud_calls || 0);
    var pct = total ? Math.round((d.local_calls || 0) / total * 100) : 100;
    $("privacy").textContent =
      "local calls: " + (d.local_calls || 0) + " of " + total + " (" + pct + "% stayed on device)\n" +
      "cloud calls: " + (d.cloud_calls || 0) + "\n" +
      "spend today: $" + Number(d.spent_today || 0).toFixed(4);
  });
}
function revokeAll() {
  api("/api/access/revoke", {}).then(function (res) {
    toast(res.ok ? "All tier grants revoked, Sir." : "Revoke failed.", !res.ok);
    refreshAccess();
  });
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
    if (d.hud) {
      hud = d.hud;
      applyHud();
      var boot = $("boot");
      if (boot) {
        if (hud.boot) { setTimeout(function () { if (boot.parentNode) boot.parentNode.removeChild(boot); }, 1600); }
        else if (boot.parentNode) { boot.parentNode.removeChild(boot); }
      }
    }
  });
}

/* boot */
(function initSpeak() {
  var b = $("speakbtn");
  if (speakOn) { b.textContent = "SPEAK: ON"; b.className = "mini on"; }
})();
refreshState();
refreshVitals();
setInterval(refreshVitals, 10000);
loadSessions();
pollEvents();
</script>
</body>
</html>
"""
