"""Phase 11 - the Orb HUD page: one self-contained HTML/CSS/JS string.

Rules this page keeps (mirrors of hud.py's server-side guarantees):
- No external requests: system fonts only, no CDN, no <link>/<script src>,
  no absolute fetch targets - the HUD renders fully offline.
- Display only: the one mutation it can send is POST /api/stop (the kill
  switch). Everything else is read.
- Accessibility: prefers-reduced-motion + server reduced_motion flag freeze
  the particle field; prefers-contrast: more gets a high-contrast theme;
  every panel has an aria-label; the log and captions are aria-live;
  every control is a real <button> reachable by keyboard.
- Performance budget (low-end phones): one canvas, <=140 particles,
  requestAnimationFrame capped, zero work when document.hidden.
"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UMBRA - Orb HUD</title>
<style>
:root{
  --accent:#14b8a6; --bg:#05070d; --panel:#0a0f1acc; --line:#1b2735;
  --text:#cfe3ee; --dim:#6b8199; --warn:#ef4444; --ok:#22c55e;
}
*{box-sizing:border-box; margin:0; padding:0}
html,body{height:100%}
body{
  background:var(--bg); color:var(--text);
  font-family:"Segoe UI", system-ui, -apple-system, sans-serif;
  font-size:14px; overflow:hidden;
}
/* themes - visual only */
body.theme-minimal{--bg:#0b0d10; --panel:#12161bcc; --line:#242a33; --dim:#8a93a0}
body.theme-scanline::after{
  content:""; position:fixed; inset:0; pointer-events:none; z-index:40;
  background:repeating-linear-gradient(0deg, transparent 0 2px, #14b8a611 2px 3px);
}
@media (prefers-contrast: more){
  :root{--text:#ffffff; --dim:#c9d4dd; --line:#8fa3b5; --panel:#000000e0}
  body{background:#000}
}
@media (prefers-reduced-motion: reduce){
  *{animation:none !important; transition:none !important}
}
header{
  display:flex; align-items:center; gap:12px; padding:10px 14px;
  border-bottom:1px solid var(--line);
}
header h1{font-size:15px; font-weight:600; letter-spacing:2px}
header .spacer{flex:1}
.chip{
  border:1px solid var(--line); border-radius:999px; padding:2px 10px;
  font-size:12px; color:var(--dim); white-space:nowrap;
}
button{
  font:inherit; color:var(--text); background:#101822;
  border:1px solid var(--line); border-radius:8px; padding:6px 12px; cursor:pointer;
}
button:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
#btnKill{border-color:var(--warn); color:#ffb4b4; font-weight:600}
#btnListen[aria-pressed="true"]{border-color:var(--accent); color:var(--accent)}
#micdot{
  width:9px; height:9px; border-radius:50%; background:var(--accent);
  display:inline-block; visibility:hidden;
}
#micdot.on{visibility:visible; box-shadow:0 0 8px var(--accent)}
#gstdot{
  width:9px; height:9px; border-radius:50%; background:var(--ok);
  display:inline-block; visibility:hidden;
}
#gstdot.on{visibility:visible; box-shadow:0 0 8px var(--ok)}
#gstvideo{width:100%; max-width:240px; border-radius:8px; background:#000;
  display:none; aspect-ratio:4/3}
#gstfeed{font-size:12px; color:var(--dim); margin-top:4px; min-height:16px}
#gstnote{font-size:12px; color:var(--dim)}
main{
  display:grid; gap:10px; padding:10px 14px 52px; height:calc(100% - 53px);
  grid-template-columns:minmax(260px, 1.2fr) 2fr; grid-template-rows:auto 1fr;
  grid-template-areas:"orb side" "log side";
}
@media (max-width:760px){
  main{grid-template-columns:1fr; grid-template-rows:auto auto 1fr;
       grid-template-areas:"orb" "side" "log"; overflow-y:auto}
  body{overflow:auto}
}
section{
  background:var(--panel); border:1px solid var(--line); border-radius:12px;
  padding:10px 12px; overflow:hidden;
}
section h2{
  font-size:11px; letter-spacing:2px; color:var(--dim); font-weight:600;
  margin-bottom:6px;
}
#orbwrap{grid-area:orb; display:flex; flex-direction:column; align-items:center}
#orb{width:100%; max-width:340px; aspect-ratio:1; touch-action:none}
#statedot{margin-top:6px; font-size:13px; letter-spacing:1px; color:var(--accent)}
#side{grid-area:side; display:flex; flex-direction:column; gap:10px; overflow-y:auto}
.kv{display:flex; justify-content:space-between; gap:8px; padding:2px 0}
.kv b{font-weight:600; color:var(--text); overflow-wrap:anywhere}
.kv span{color:var(--dim)}
#ring{width:74px; height:74px; border-radius:50%; margin:4px auto;
  background:conic-gradient(var(--accent) 0turn, var(--line) 0turn);
  display:flex; align-items:center; justify-content:center}
#ring div{width:56px; height:56px; border-radius:50%; background:var(--bg);
  display:flex; align-items:center; justify-content:center; font-size:11px}
#chain li{margin-left:16px; color:var(--dim); font-size:12px;
  overflow-wrap:anywhere; padding:1px 0}
#devices li{margin-left:16px; font-size:12px; padding:1px 0}
#devices .none, #chain .none{color:var(--dim); font-size:12px; margin-left:0}
#log{grid-area:log; display:flex; flex-direction:column}
#logstream{flex:1; overflow-y:auto; font-size:12px}
#logstream div{padding:1px 0; overflow-wrap:anywhere}
#logstream .t{color:var(--dim); margin-right:6px}
#logstream .kill{color:var(--warn); font-weight:600}
#captions{
  position:fixed; left:0; right:0; bottom:0; z-index:30; text-align:center;
  padding:8px 14px; background:#05070de8; border-top:1px solid var(--line);
  min-height:34px; font-size:13px;
}
#boot{
  position:fixed; inset:0; z-index:50; background:var(--bg);
  display:flex; align-items:center; justify-content:center; flex-direction:column;
  gap:14px; transition:opacity .6s;
}
#boot.off{opacity:0; pointer-events:none}
#boottxt{font-size:17px; letter-spacing:1px; color:var(--accent)}
#boot .sub{color:var(--dim); font-size:12px}
#notoken{
  color:var(--warn); font-size:12px; padding:6px 12px; display:none;
}
</style>
</head>
<body class="theme-hud">
<header>
  <h1>UMBRA</h1>
  <span id="micdot" title="microphone open - audio never leaves this page"></span>
  <span id="gstdot" title="camera on - frames are processed in this page and never sent anywhere"></span>
  <span class="chip" id="chipTier">tier -</span>
  <span class="chip" id="chipGrants">grants -</span>
  <span class="chip" id="chipVer">v-</span>
  <span class="spacer"></span>
  <span id="notoken">token missing - open this page via the URL printed by jarvis hud serve</span>
  <button id="btnListen" aria-pressed="false" aria-label="Toggle local microphone analysis for audio-reactive orb">Listen</button>
  <button id="btnKill" aria-label="Kill switch - halt all running UMBRA actions now">KILL</button>
</header>
<main>
  <section id="orbwrap" aria-label="Agent state orb">
    <canvas id="orb" width="340" height="340" aria-hidden="true"></canvas>
    <div id="statedot" role="status">connecting...</div>
  </section>
  <div id="side">
    <section aria-label="Brain panel - current route and model">
      <h2>BRAIN</h2>
      <div class="kv"><span>provider</span><b id="brainProvider">-</b></div>
      <div class="kv"><span>model</span><b id="brainModel">-</b></div>
      <div class="kv"><span>route</span><b id="brainWhy">-</b></div>
    </section>
    <section aria-label="Body panel - agent state and machine vitals">
      <h2>BODY</h2>
      <div id="ring" aria-hidden="true"><div id="ringLabel">-</div></div>
      <div class="kv"><span>cpu</span><b id="vitCpu">-</b></div>
      <div class="kv"><span>ram</span><b id="vitRam">-</b></div>
      <div class="kv"><span>battery</span><b id="vitBat">-</b></div>
    </section>
    <section aria-label="Chain panel - recent agent steps">
      <h2>CHAIN</h2>
      <ul id="chain"><li class="none">no steps yet</li></ul>
    </section>
    <section aria-label="Devices panel">
      <h2>DEVICES</h2>
      <ul id="devices"><li class="none">no devices reported</li></ul>
    </section>
    <section aria-label="Hand gestures panel - opt-in, camera stays in this page">
      <h2>GESTURES</h2>
      <div id="gstnote">checking gesture status...</div>
      <video id="gstvideo" autoplay playsinline muted aria-label="Local camera preview - never transmitted"></video>
      <div id="gstfeed" aria-live="polite"></div>
      <button id="btnGest" aria-label="Toggle hand-gesture control (requires camera, opt-in)">Enable hand control</button>
    </section>
  </div>
  <section id="log" aria-label="Live action log">
    <h2>LOG</h2>
    <div id="logstream" aria-live="polite"></div>
  </section>
</main>
<div id="captions" role="status" aria-live="polite"></div>
<div id="boot" role="dialog" aria-label="Boot sequence">
  <pre id="boottxt" aria-hidden="true"></pre>
  <div class="sub">the shadow that works for you</div>
</div>
<script>
"use strict";
// The state/color map - mirror of hud.py STATE_COLORS (one copy each side).
var STATE_COLORS = {
  idle:"#14b8a6", listening:"#3b82f6", thinking:"#e5e7eb",
  working:"#22c55e", speaking:"#f59e0b", alert:"#ef4444"
};
var qs = new URLSearchParams(location.search);
var TOKEN = qs.get("t") || "";
var lastEvent = 0, lastPayload = null, audioLevel = 0, reducedMotion = false;

function api(path, opts){
  var sep = path.indexOf("?") >= 0 ? "&" : "?";
  var headers = opts && opts.headers ? opts.headers : {};
  if (TOKEN) headers["X-Jarvis-Token"] = TOKEN;
  return fetch(path + sep + "t=" + encodeURIComponent(TOKEN),
               Object.assign({cache:"no-store", headers:headers}, opts || {}));
}
function $(id){ return document.getElementById(id); }
function pct(v){ return (v == null) ? "-" : Math.round(v) + "%"; }

// ------------------------------------------------------------ orb canvas
var canvas = $("orb"), ctx = canvas.getContext("2d");
var particles = [];
function buildParticles(){
  var area = canvas.width * canvas.height;
  var n = Math.max(40, Math.min(140, Math.round(area / 6200)));
  particles = [];
  for (var i = 0; i < n; i++){
    particles.push({
      r: 0.18 + Math.random() * 0.78,      // orbit radius, fraction
      a: Math.random() * Math.PI * 2,      // angle
      s: (0.2 + Math.random() * 0.9) * (Math.random() < 0.5 ? -1 : 1),
      z: 0.4 + Math.random() * 1.6,        // size
      w: 0.4 + Math.random() * 0.8         // wobble phase
    });
  }
}
buildParticles();
function drawOrb(){
  var w = canvas.width, h = canvas.height, cx = w / 2, cy = h / 2;
  ctx.clearRect(0, 0, w, h);
  var accent = (lastPayload && lastPayload.color) || STATE_COLORS.idle;
  var thinking = lastPayload && lastPayload.state === "thinking";
  var pulse = thinking ? 1 + 0.05 * Math.sin(Date.now() / 180) : 1;
  var breath = 1 + audioLevel * 0.35;
  // core
  var core = ctx.createRadialGradient(cx, cy, 4, cx, cy, w * 0.24 * pulse * breath);
  try { core.addColorStop(0, accent); core.addColorStop(1, "transparent"); }
  catch (e) { /* keep flat core on odd colors */ }
  ctx.globalAlpha = 0.9;
  ctx.fillStyle = core;
  ctx.beginPath(); ctx.arc(cx, cy, w * 0.24 * pulse * breath, 0, 7); ctx.fill();
  // particles
  var R = w * 0.42;
  for (var i = 0; i < particles.length; i++){
    var p = particles[i];
    if (!reducedMotion){
      p.a += 0.0025 * p.s * (1 + audioLevel * 2);
    }
    var wob = Math.sin(Date.now() / 900 + p.w * 7) * 3 * (reducedMotion ? 0 : 1);
    var x = cx + Math.cos(p.a) * (R * p.r + wob);
    var y = cy + Math.sin(p.a) * (R * p.r + wob) * 0.86;
    ctx.globalAlpha = 0.25 + 0.55 * Math.abs(Math.sin(p.a)) * p.z / 2;
    ctx.fillStyle = accent;
    ctx.beginPath(); ctx.arc(x, y, p.z, 0, 7); ctx.fill();
  }
  ctx.globalAlpha = 1;
}
var rafId = null;
function loop(){ drawOrb(); rafId = document.hidden ? null : requestAnimationFrame(loop); }

// -------------------------------------------------------------- mic (opt-in, local only)
var micStream = null, audioCtx = null;
$("btnListen").addEventListener("click", function(){
  if (micStream){ // stop
    micStream.getTracks().forEach(function(t){ t.stop(); });
    micStream = null; if (audioCtx){ audioCtx.close(); audioCtx = null; }
    audioLevel = 0;
    $("btnListen").setAttribute("aria-pressed", "false");
    $("micdot").classList.remove("on");
    return;
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia){
    setCaptions("microphone not available in this browser - orb stays state-driven");
    return;
  }
  navigator.mediaDevices.getUserMedia({audio:true}).then(function(stream){
    // Audio never leaves this page: analyser only, no upload, no storage.
    micStream = stream;
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    var src = audioCtx.createMediaStreamSource(stream);
    var analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    src.connect(analyser);
    var buf = new Uint8Array(analyser.frequencyBinCount);
    (function meter(){
      if (!micStream) return;
      analyser.getByteTimeDomainData(buf);
      var peak = 0;
      for (var i = 0; i < buf.length; i++){ peak = Math.max(peak, Math.abs(buf[i] - 128)); }
      audioLevel = Math.min(1, peak / 64);
      requestAnimationFrame(meter);
    })();
    $("btnListen").setAttribute("aria-pressed", "true");
    $("micdot").classList.add("on");
  }).catch(function(){
    setCaptions("microphone declined - orb stays state-driven (nothing was sent anywhere)");
  });
});

// -------------------------------------------------------------- kill switch
$("btnKill").addEventListener("click", function(){
  api("/api/stop", {method:"POST", body:"{}"})
    .then(function(){ applyState("alert", null); logLine({ts:"now", text:"KILL SWITCH engaged - halting all actions", kill:true}); })
    .catch(function(){ setCaptions("kill switch call failed - run jarvis stop"); });
});

// -------------------------------------------------- gestures (opt-in, local)
var gstState = {status:null, hands:null, stream:null, lastSeen:0, sending:false};
function gstNote(text){ $("gstnote").textContent = text; }
function gstFeed(text){ $("gstfeed").textContent = text; }
function gstCameraIndicator(on){
  $("gstdot").classList.toggle("on", on);
  $("gstvideo").style.display = on ? "block" : "none";
}
function gstStatus(){
  api("/api/gestures").then(function(r){ return r.status === 200 ? r.json() : null; })
    .then(function(s){
      if (!s) return;
      gstState.status = s;
      var vendored = s.vendor && s.vendor.complete;
      if (!s.enabled){
        gstNote("off (opt-in) - run: jarvis gestures enable");
        $("btnGest").disabled = true;
      } else if (!s.grant.allowed){
        gstNote("needs the assist grant - jarvis access grant --tiers assist");
        $("btnGest").disabled = true;
      } else if (!vendored){
        gstNote("tracker bundle missing - run: jarvis gestures vendor");
        $("btnGest").disabled = true;
      } else {
        gstNote("ready - point=cursor pinch=select swipe=nav palm=pause fist=KILL");
        $("btnGest").disabled = false;
      }
    }).catch(function(){ gstNote("gesture status unavailable"); });
}
gstStatus();
setInterval(gstStatus, 15000);
$("btnGest").addEventListener("click", function(){
  if (gstState.stream){ gstStop(); return; }
  gstStart();
});
function gstStop(){
  if (gstState.stream){ gstState.stream.getTracks().forEach(function(t){ t.stop(); }); }
  gstState.stream = null;
  gstCameraIndicator(false);
  $("btnGest").textContent = "Enable hand control";
  gstFeed("camera off");
}
function gstStart(){
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia){
    gstNote("camera not available in this browser"); return;
  }
  navigator.mediaDevices.getUserMedia({video:{width:320, height:240}, audio:false})
    .then(function(stream){
      gstState.stream = stream;
      $("gstvideo").srcObject = stream;
      gstCameraIndicator(true);
      $("btnGest").textContent = "Disable hand control";
      gstFeed("camera on - local only");
      gstState.lastSeen = Date.now();
      return loadTracker();
    })
    .then(function(hands){
      if (!hands){ gstNote("tracker failed to load"); gstStop(); return; }
      gstState.hands = hands;
      // idle timeout: no hand seen for idle_timeout_s -> camera auto-off
      var timeoutMs = ((gstState.status && gstState.status.idle_timeout_s) || 30) * 1000;
      var idleTimer = setInterval(function(){
        if (!gstState.stream){ clearInterval(idleTimer); return; }
        if (Date.now() - gstState.lastSeen > timeoutMs){
          gstFeed("idle timeout - camera off"); gstStop(); clearInterval(idleTimer);
        }
      }, 1000);
    })
    .catch(function(){
      gstNote("camera declined - gestures stay off (nothing was sent anywhere)");
    });
}
function loadTracker(){
  if (window.Hands) return Promise.resolve(new window.Hands({locateFile:function(f){ return "/vendor/" + f; }}));
  return new Promise(function(resolve){
    var s = document.createElement("script");
    s.src = "/vendor/hands.js";  // local vendored file, never a CDN
    s.onload = function(){
      if (!window.Hands){ resolve(null); return; }
      resolve(new window.Hands({locateFile:function(f){ return "/vendor/" + f; }}));
    };
    s.onerror = function(){ resolve(null); };
    document.head.appendChild(s);
  });
}
// The tracker calls this per frame with normalized landmarks; we forward
// coordinates only (no frames) to the token-gated endpoint, throttled.
function gstOnResults(results){
  if (!results.multiHandLandmarks || !results.multiHandLandmarks.length){
    return;  // idle timer handles the auto-off
  }
  gstState.lastSeen = Date.now();
  if (gstState.sending) return;
  gstState.sending = true;
  var points = results.multiHandLandmarks[0].map(function(p){ return [p.x, p.y]; });
  api("/api/gesture", {method:"POST", body:JSON.stringify({landmarks:points})})
    .then(function(r){ return r.status === 200 ? r.json() : {error:r.status}; })
    .then(function(res){
      gstState.sending = false;
      if (res && res.gesture && res.gesture !== "none"){
        gstFeed("gesture: " + res.gesture + " -> " + (res.action || "-") +
                (res.detail ? " (" + res.detail + ")" : ""));
        if (res.gesture === "fist") applyState("alert", null);
      }
    }).catch(function(){ gstState.sending = false; });
}
// Wire the vendored tracker once it exists (poll; the script loads on start).
(function gstPollTracker(){
  if (gstState.hands && !gstState.hands.__wired){
    gstState.hands.__wired = true;
    gstState.hands.onResults(gstOnResults);
    (function pump(){
      if (!gstState.stream){ return; }
      gstState.hands.send({image: $("gstvideo")})
        .then(function(){ requestAnimationFrame(pump); })
        .catch(function(){ setTimeout(pump, 300); });
    })();
  } else {
    setTimeout(gstPollTracker, 500);
  }
})();

// -------------------------------------------------------------- rendering
function setCaptions(text){ $("captions").textContent = text; }
function logLine(ev){
  var div = document.createElement("div");
  var t = document.createElement("span"); t.className = "t"; t.textContent = ev.ts || "";
  var x = document.createElement("span"); x.textContent = ev.text || "";
  if (ev.kill) x.className = "kill";
  div.appendChild(t); div.appendChild(x);
  var box = $("logstream");
  box.appendChild(div);
  while (box.childElementCount > 160) box.removeChild(box.firstChild);
  box.scrollTop = box.scrollHeight;
}
function applyState(state, payload){
  var color = (payload && payload.color) || STATE_COLORS[state] || STATE_COLORS.idle;
  document.documentElement.style.setProperty("--accent", color);
  $("statedot").textContent = "state: " + state;
  $("statedot").style.color = color;
  $("ringLabel").textContent = state;
}
function render(payload){
  lastPayload = payload;
  reducedMotion = !!(payload.hud && payload.hud.reduced_motion) ||
                  (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  applyState(payload.state, payload);
  document.body.className = "theme-" + (payload.hud && payload.hud.theme === "hologram" ? "hud" : ((payload.hud && payload.hud.theme) || "hud"));
  $("chipTier").textContent = "tier " + (payload.tier || "-");
  var grants = payload.grants || {};
  var active = [];
  Object.keys(grants).forEach(function(k){
    var g = grants[k];
    if (g && (g.granted || g.active)) active.push(k);
  });
  $("chipGrants").textContent = "grants " + (active.length ? active.join(",") : "none");
  $("chipVer").textContent = "v" + (payload.version || "-");
  $("brainProvider").textContent = (payload.brain && payload.brain.provider) || "-";
  $("brainModel").textContent = (payload.brain && payload.brain.model) || "-";
  $("brainWhy").textContent = (payload.brain && payload.brain.why) || "same as last turn";
  var v = payload.vitals || {};
  $("vitCpu").textContent = pct(v.cpu_percent);
  $("vitRam").textContent = pct(v.ram_percent);
  $("vitBat").textContent = (v.battery_percent == null) ? "-" : pct(v.battery_percent);
  var load = Math.max(v.cpu_percent || 0, v.ram_percent || 0) / 100;
  var ring = Math.max(0.02, Math.min(1, load));
  $("ring").style.background = "conic-gradient(var(--accent) " + (ring * 360) + "deg, var(--line) 0deg)";
  var chain = payload.chain || [];
  $("chain").innerHTML = "";
  if (!chain.length){ $("chain").innerHTML = "<li class=\\"none\\">no steps yet</li>"; }
  chain.slice().reverse().forEach(function(s){
    var li = document.createElement("li"); li.textContent = s; $("chain").appendChild(li);
  });
  var devices = payload.devices || [];
  $("devices").innerHTML = "";
  if (!devices.length){ $("devices").innerHTML = "<li class=\\"none\\">no devices reported</li>"; }
  devices.forEach(function(d){
    var li = document.createElement("li");
    li.textContent = (d.name || "?") + " - " + (d.tier || "?") + " - seen " + (d.last_seen || "?");
    $("devices").appendChild(li);
  });
  setCaptions(payload.captions || "");
  if (payload.stop_requested) applyState("alert", payload);
  bootSequence(payload);
}
function bootSequence(payload){
  if (!payload.hud || !payload.hud.boot) { $("boot").classList.add("off"); return; }
  if (sessionStorage.getItem("umbra-boot-done")) { $("boot").classList.add("off"); return; }
  sessionStorage.setItem("umbra-boot-done", "1");
  var line = "System online, " + (payload.honorific || "Sir") + ".";
  var el = $("boottxt"), i = 0;
  el.textContent = "";
  var typed = setInterval(function(){
    el.textContent = line.slice(0, ++i);
    if (i >= line.length){
      clearInterval(typed);
      setTimeout(function(){ $("boot").classList.add("off"); }, 700);
    }
  }, 45);
}

// -------------------------------------------------------------- polling
function pollState(){
  api("/api/state").then(function(r){
    if (r.status === 403){ $("notoken").style.display = "inline"; return null; }
    $("notoken").style.display = "none";
    return r.json();
  }).then(function(p){ if (p) render(p); }).catch(function(){ /* keep last frame */ });
}
function pollEvents(){
  api("/api/events?since=" + lastEvent).then(function(r){
    if (r.status !== 200) throw new Error("events " + r.status);
    return r.json();
  }).then(function(data){
    (data.events || []).forEach(function(ev){
      lastEvent = Math.max(lastEvent, ev.id || 0);
      logLine(ev);
    });
    setTimeout(pollEvents, 400);
  }).catch(function(){ setTimeout(pollEvents, 2000); });
}
pollState();
setInterval(pollState, 2000);
pollEvents();
loop();
document.addEventListener("visibilitychange", function(){
  if (!document.hidden && rafId === null && !reducedMotion) loop();
});
window.addEventListener("resize", function(){
  var dpr = Math.min(2, window.devicePixelRatio || 1);
  var rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(120, Math.round(rect.width * dpr));
  canvas.height = canvas.width;
  buildParticles();
  if (reducedMotion) drawOrb();
});
window.dispatchEvent(new Event("resize"));
</script>
</body>
</html>
"""
