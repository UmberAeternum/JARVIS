"""The Bridge's single-file client: a phone-first control panel for the full
desktop agent — transcript, tool log, and the APPROVE/DENY confirmation
banner. Plain string constant; JS template literals pass through untouched.
"""

PAGE_BRIDGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>J.A.R.V.I.S. — Bridge</title>
<meta name="theme-color" content="#050A12">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="JARVIS">
<link rel="manifest" href="manifest.json">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='12' fill='%23050A12'/%3E%3Ccircle cx='32' cy='32' r='14' fill='none' stroke='%2366F0FF' stroke-width='4'/%3E%3Ccircle cx='32' cy='32' r='5' fill='%23FFB454'/%3E%3C/svg%3E">
<style>
  :root { --bg:#050A12; --cyan:#66F0FF; --amber:#FFB454; --dim:#7FA8B8; --panel:#0E2233; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--cyan);
         font-family:Consolas,'Segoe UI',monospace; height:100vh;
         display:flex; flex-direction:column; }
  #topbar { padding:10px 14px; border-bottom:1px solid #123246; display:flex;
            justify-content:space-between; align-items:center; }
  h1 { font-size:14px; letter-spacing:3px; font-weight:400; margin:0; }
  #state { font-size:11px; color:var(--dim); }
  #transcript { flex:1; overflow-y:auto; padding:12px; display:flex;
                flex-direction:column; gap:8px; }
  .msg { padding:9px 11px; border-radius:10px; font-size:13px; max-width:100%;
         border:1px solid; white-space:pre-wrap; }
  .user { align-self:flex-end; color:var(--amber); border-color:#FFB45466; background:#FFB45414; }
  .reply { align-self:flex-start; color:var(--cyan); border-color:#66F0FF55; background:#0E223388; }
  .streaming { opacity:.85; }
  .status { align-self:center; color:var(--dim); font-size:11px; border:none; background:none; }
  .err { align-self:flex-start; color:#FF6B6B; border-color:#FF6B6B66; }
  #confirm { display:none; margin:10px 12px 0; padding:12px;
             border:1px solid var(--amber); border-radius:10px; background:#FFB45414; }
  #confirm .desc { color:var(--amber); font-size:13px; margin-bottom:10px; }
  #confirm .row { display:flex; gap:10px; }
  #confirm button { flex:1; padding:10px; border-radius:8px; font-family:inherit;
                    font-size:13px; letter-spacing:1px; cursor:pointer; }
  #approve { background:#FFB45422; color:var(--amber); border:1px solid var(--amber); }
  #deny { background:#FF6B6B22; color:#FF6B6B; border:1px solid #FF6B6B; }
  #inputrow { display:flex; gap:8px; padding:12px; border-top:1px solid #123246; }
  #input { flex:1; background:var(--panel); border:1px solid #66F0FF44; color:var(--cyan);
           padding:10px; border-radius:8px; font-family:inherit; outline:none; }
  #send { background:var(--panel); color:var(--amber); border:1px solid #FFB45466;
          border-radius:8px; padding:10px 16px; cursor:pointer; font-family:inherit; }
  #send:disabled { opacity:.4; cursor:default; }
  #brief { background:var(--panel); color:var(--cyan); border:1px solid #66F0FF66;
           border-radius:8px; padding:10px 14px; cursor:pointer; font-family:inherit;
           letter-spacing:1px; }
  #brief:disabled { opacity:.4; cursor:default; }
</style>
</head>
<body>
  <div id="topbar"><h1>J.A.R.V.I.S. — BRIDGE</h1><span id="state">connecting...</span></div>
  <div id="transcript"></div>
  <div id="confirm">
    <div class="desc" id="confirmDesc"></div>
    <div class="row">
      <button id="deny">DENY</button>
      <button id="approve">APPROVE</button>
    </div>
  </div>
  <div id="inputrow">
    <input id="input" placeholder="Command the desktop, Sir" autocomplete="off">
    <button id="send">SEND</button>
    <button id="brief" title="The morning briefing">BRIEF</button>
  </div>
<script>
"use strict";
const transcript = document.getElementById("transcript");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const stateLine = document.getElementById("state");
const confirmBox = document.getElementById("confirm");
const confirmDesc = document.getElementById("confirmDesc");

const TOKEN = new URLSearchParams(location.search).get("t") || "";
let since = 0;
let thinking = false;
let pendingConfirm = null;
let streamingEl = null;
function finishStreaming() { if (streamingEl) { streamingEl.remove(); streamingEl = null; } }

function bubble(cls, text) {
  const div = document.createElement("div");
  div.className = "msg " + cls;
  div.textContent = text;
  transcript.appendChild(div);
  transcript.scrollTop = transcript.scrollHeight;
}

function showConfirm(id, description) {
  pendingConfirm = id;
  confirmDesc.textContent = description;
  confirmBox.style.display = "block";
}
function answerConfirm(approved) {
  if (pendingConfirm === null) return;
  fetch("/api/confirm", {
    method: "POST", headers: auth(), body: JSON.stringify({confirm_id: pendingConfirm, approved})
  });
  confirmBox.style.display = "none";
  pendingConfirm = null;
}
document.getElementById("approve").addEventListener("click", () => answerConfirm(true));
document.getElementById("deny").addEventListener("click", () => answerConfirm(false));

function auth() { return {"X-Jarvis-Token": TOKEN, "Content-Type": "application/json"}; }

async function sendCommand(text) {
  if (!text.trim() || thinking) return;
  thinking = true; sendBtn.disabled = true;
  bubble("user", text);
  try {
    const response = await fetch("/api/command", {
      method: "POST", headers: auth(), body: JSON.stringify({text: text})
    });
    const data = await response.json();
    if (data.error) bubble("err", data.error);
  } catch (exc) { bubble("err", "LINK DOWN: " + exc.message); }
}
sendBtn.addEventListener("click", () => { const t = input.value; input.value = ""; sendCommand(t); });
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { const t = input.value; input.value = ""; sendCommand(t); }
});

/* Phase 7 - the morning briefing, one tap away */
const briefBtn = document.getElementById("brief");
briefBtn.addEventListener("click", async () => {
  briefBtn.disabled = true;
  try {
    const response = await fetch("/api/briefing", {headers: auth()});
    const data = await response.json();
    if (data.briefing) { bubble("reply", data.briefing); }
    else { bubble("err", "BRIEFING UNAVAILABLE"); }
  } catch (exc) { bubble("err", "LINK DOWN: " + exc.message); }
  briefBtn.disabled = false;
});

async function pollLoop() {
  while (true) {
    try {
      const response = await fetch("/api/events?since=" + since, {headers: auth()});
      const data = await response.json();
      stateLine.textContent = data.last > since ? ("live - event " + data.last) : "listening...";
      for (const event of data.events) {
        since = Math.max(since, event.id);
        if (event.type === "user") { finishStreaming(); bubble("user", event.text); }
        else if (event.type === "partial") {
          if (!streamingEl) {
            streamingEl = document.createElement("div");
            streamingEl.className = "msg reply streaming";
            transcript.appendChild(streamingEl);
          }
          streamingEl.textContent = event.text + " ▌";
          transcript.scrollTop = transcript.scrollHeight;
        }
        else if (event.type === "reply") {
          thinking = false; sendBtn.disabled = false;
          finishStreaming();
          bubble("reply", event.text);
        }
        else if (event.type === "status") bubble("status", event.text);
        else if (event.type === "confirm_request") showConfirm(event.confirm_id, event.description);
      }
    } catch (exc) { stateLine.textContent = "reconnecting..."; }
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
}
bubble("status", "Bridge panel ready - events stream below, Sir.");
pollLoop();
</script>
</body>
</html>
"""

# Phase 7 - the phone companion: the Bridge installs as a PWA. Served by
# serve.py at /manifest.json without the session token (it contains no
# secrets - a name, colors, and display rules).
PWA_MANIFEST = """{
  "name": "J.A.R.V.I.S. Bridge",
  "short_name": "JARVIS",
  "description": "The full desktop agent, reachable from anywhere on the LAN.",
  "start_url": "./",
  "scope": "./",
  "display": "standalone",
  "background_color": "#050A12",
  "theme_color": "#050A12",
  "icons": [
    {
      "src": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='12' fill='%23050A12'/%3E%3Ccircle cx='32' cy='32' r='14' fill='none' stroke='%2366F0FF' stroke-width='4'/%3E%3Ccircle cx='32' cy='32' r='5' fill='%23FFB454'/%3E%3C/svg%3E",
      "sizes": "any",
      "type": "image/svg+xml",
      "purpose": "any"
    }
  ]
}
"""
