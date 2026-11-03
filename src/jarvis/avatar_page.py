"""The Avatar's single-file web client: procedural HUD face, optional BYO
VRM 3D model, browser-TTS lip sync, and the chat panel.

Kept as a Python string constant so the package needs no data-file wiring;
the server serves it at `/`. Plain string (not an f-string) so the JavaScript
template literals pass through untouched.
"""

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>J.A.R.V.I.S. — Avatar</title>
<style>
  :root { --bg:#050A12; --cyan:#66F0FF; --amber:#FFB454; --dim:#7FA8B8; --panel:#0E2233; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--cyan);
         font-family:'Segoe UI',Consolas,monospace; height:100vh; display:flex; overflow:hidden; }
  #stage { flex:1; position:relative; }
  canvas#face { width:100%; height:100%; display:block; }
  #threed { position:absolute; inset:0; display:none; }
  #side { width:380px; border-left:1px solid #123246; display:flex; flex-direction:column; background:#04080F; }
  #transcript { flex:1; overflow-y:auto; padding:14px; display:flex; flex-direction:column; gap:10px; }
  .msg { padding:10px 12px; border-radius:10px; font-size:14px; max-width:100%;
         border:1px solid; white-space:pre-wrap; }
  .user { align-self:flex-end; color:var(--amber); border-color:#FFB45466; background:#FFB45414; }
  .jarvis { align-self:flex-start; color:var(--cyan); border-color:#66F0FF55; background:#0E223388; }
  .err { align-self:flex-start; color:#FF6B6B; border-color:#FF6B6B66; }
  #inputrow { display:flex; gap:8px; padding:12px; border-top:1px solid #123246; }
  #input { flex:1; background:var(--panel); border:1px solid #66F0FF44; color:var(--cyan);
           padding:10px; border-radius:8px; font-family:inherit; outline:none; }
  #send { background:var(--panel); color:var(--amber); border:1px solid #FFB45466;
          border-radius:8px; padding:10px 16px; cursor:pointer; font-family:inherit;
          letter-spacing:2px; }
  #send:disabled { opacity:.4; cursor:default; }
  #topbar { padding:10px 14px; border-bottom:1px solid #123246; display:flex;
            justify-content:space-between; align-items:center; }
  #modebtn { background:none; border:1px solid #66F0FF44; color:var(--dim); padding:6px 10px;
             border-radius:6px; cursor:pointer; font-family:inherit; font-size:12px; }
  #modebtn:hover { color:var(--cyan); }
  h1 { font-size:14px; letter-spacing:4px; font-weight:400; margin:0; }
  .thinking { color:var(--amber); font-size:12px; }
</style>
</head>
<body>
  <div id="stage">
    <canvas id="face"></canvas>
    <div id="threed"></div>
    <div id="topbar">
      <h1>J.A.R.V.I.S. — AVATAR LINK</h1>
      <button id="modebtn">MODE: HUD FACE</button>
    </div>
  </div>
  <div id="side">
    <div id="transcript"></div>
    <div id="inputrow">
      <input id="input" placeholder="Type a request, Sir" autocomplete="off">
      <button id="send">SEND</button>
    </div>
  </div>
<script>
"use strict";
const transcript = document.getElementById("transcript");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const modeBtn = document.getElementById("modebtn");
const faceCanvas = document.getElementById("face");
const threedDiv = document.getElementById("threed");

let thinking = false;
let speaking = false;
let mouthOpen = 0;
let mode = "hud";           // "hud" | "3d"
let vrmReady = false;

function bubble(cls, text) {
  const div = document.createElement("div");
  div.className = "msg " + cls;
  div.textContent = text;
  transcript.appendChild(div);
  transcript.scrollTop = transcript.scrollHeight;
  return div;
}
function thinkingBubble() { return bubble("thinking", "J.A.R.V.I.S. is thinking..."); }

async function chat(text) {
  if (thinking) return;
  thinking = true; sendBtn.disabled = true;
  bubble("user", text);
  const wait = thinkingBubble();
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text: text}),
    });
    const data = await response.json();
    wait.remove();
    const reply = data.reply || data.error || "(no response)";
    bubble(reply.startsWith("ERROR") ? "err" : "jarvis", reply);
    speak(reply);
  } catch (exc) {
    wait.remove();
    bubble("err", "LINK DOWN: " + exc.message);
  } finally {
    thinking = false; sendBtn.disabled = false;
  }
}
sendBtn.addEventListener("click", () => { const t = input.value; input.value = ""; chat(t); });
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter") { const t = input.value; input.value = ""; chat(t); }
});

/* ---- speech: the browser speaks, boundary events drive the mouth ---- */
function speak(text) {
  if (!("speechSynthesis" in window)) { speaking = true; setTimeout(() => { speaking = false; }, Math.min(6000, text.length * 55)); return; }
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 1.02; utterance.pitch = 0.9;
  utterance.onstart = () => { speaking = true; };
  utterance.onboundary = () => { mouthOpen = 1; };
  utterance.onend = () => { speaking = false; mouthOpen = 0; };
  utterance.onerror = () => { speaking = false; mouthOpen = 0; };
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
}

/* ---- procedural HUD face ---- */
const faceCtx = faceCanvas.getContext("2d");
let blinkTimer = 0;
let lastFrame = performance.now();

function resizeFace() {
  faceCanvas.width = faceCanvas.clientWidth * window.devicePixelRatio;
  faceCanvas.height = faceCanvas.clientHeight * window.devicePixelRatio;
}
window.addEventListener("resize", resizeFace);
resizeFace();

function drawFace(now) {
  const dt = Math.min(50, now - lastFrame); lastFrame = now;
  const ctx = faceCtx;
  const w = faceCanvas.width, h = faceCanvas.height;
  ctx.clearRect(0, 0, w, h);
  const cx = w / 2, cy = h / 2, r = Math.min(w, h) * 0.30;
  const t = now / 1000;

  // breathing outer rings
  const breathe = 1 + 0.03 * Math.sin(t * 1.6);
  ctx.strokeStyle = "rgba(102,240,255,0.16)";
  ctx.lineWidth = 2 * window.devicePixelRatio;
  ctx.beginPath(); ctx.arc(cx, cy, r * 1.05 * breathe, 0, Math.PI * 2); ctx.stroke();
  ctx.strokeStyle = "rgba(102,240,255,0.30)";
  ctx.beginPath(); ctx.arc(cx, cy, r * 0.86, 0, Math.PI * 2); ctx.stroke();

  // rotating tick ring
  ctx.save(); ctx.translate(cx, cy); ctx.rotate(t * 0.4);
  ctx.strokeStyle = "rgba(102,240,255,0.45)";
  for (let i = 0; i < 12; i++) {
    const a = (i / 12) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(Math.cos(a) * r * 0.92, Math.sin(a) * r * 0.92);
    ctx.lineTo(Math.cos(a) * r * 1.02, Math.sin(a) * r * 1.02);
    ctx.stroke();
  }
  ctx.restore();

  // speaking waveform ring
  if (speaking) {
    ctx.strokeStyle = "rgba(255,180,84,0.8)";
    for (let i = 0; i < 24; i++) {
      const a = (i / 24) * Math.PI * 2 + t * 2;
      const wobble = r * (0.70 + 0.10 * Math.abs(Math.sin(t * 9 + i * 1.7)));
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(a) * r * 0.62, cy + Math.sin(a) * r * 0.62);
      ctx.lineTo(cx + Math.cos(a) * wobble, cy + Math.sin(a) * wobble);
      ctx.stroke();
    }
  }

  // eyes: two glowing arcs that blink
  blinkTimer -= dt;
  let blink = 1;
  if (blinkTimer <= 0) blinkTimer = 2800 + Math.random() * 2600;
  if (blinkTimer < 140) blink = Math.max(0.08, blinkTimer / 140);
  const eyeY = cy - r * 0.10;
  ctx.fillStyle = "rgba(102,240,255,0.9)";
  [[-0.30, 0], [0.30, 0]].forEach(([ex]) => {
    const exPix = cx + ex * r;
    const eh = r * 0.10 * blink;
    ctx.beginPath();
    ctx.ellipse(exPix, eyeY, r * 0.11, Math.max(1.5, eh), 0, 0, Math.PI * 2);
    ctx.fill();
  });

  // mouth: opens while speaking, driven by boundary pulses
  mouthOpen = Math.max(0, mouthOpen - dt / 180);
  const mouth = speaking ? (0.10 + 0.24 * mouthOpen) : 0.015 + 0.01 * Math.sin(t * 1.1);
  ctx.strokeStyle = "rgba(102,240,255,0.85)";
  ctx.lineWidth = 3 * window.devicePixelRatio;
  ctx.beginPath();
  ctx.ellipse(cx, cy + r * 0.28, r * 0.16, Math.max(2, r * mouth), 0, 0, Math.PI * 2);
  ctx.stroke();

  // reactor
  ctx.fillStyle = "rgba(255,180,84,0.9)";
  ctx.beginPath();
  ctx.arc(cx, cy + r * 0.62, r * 0.06 * (1 + 0.15 * Math.sin(t * 3)), 0, Math.PI * 2);
  ctx.fill();
}
let faceRAF = null;
function faceLoop(now) { drawFace(now); faceRAF = requestAnimationFrame(faceLoop); }
faceRAF = requestAnimationFrame(faceLoop);

/* ---- optional 3D mode: BYO avatar.vrm ---- */
modeBtn.addEventListener("click", async () => {
  if (mode === "hud") {
    try {
      const check = await fetch("/avatar.vrm");
      if (!check.ok) { bubble("err", "No avatar.vrm found in the JARVIS config directory - place your own VRM model there and retry."); return; }
      await enable3D();
      mode = "3d"; faceCanvas.style.display = "none"; threedDiv.style.display = "block";
      modeBtn.textContent = "MODE: 3D AVATAR";
    } catch (exc) { bubble("err", "3D mode failed: " + exc.message); }
  } else {
    mode = "hud"; threedDiv.style.display = "none"; faceCanvas.style.display = "block";
    modeBtn.textContent = "MODE: HUD FACE";
  }
});

async function enable3D() {
  if (vrmReady) return;
  const THREE = await import("https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.module.js");
  const { VRMLoaderPlugin, VRMUtils } = await import("https://cdn.jsdelivr.net/npm/@pixiv/three-vrm@3/lib/three-vrm.module.min.js");
  const renderer = new THREE.WebGLRenderer({antialias: true, alpha: true});
  renderer.setSize(threedDiv.clientWidth, threedDiv.clientHeight);
  renderer.setPixelRatio(window.devicePixelRatio);
  threedDiv.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, threedDiv.clientWidth / threedDiv.clientHeight, 0.1, 20);
  camera.position.set(0, 1.35, -1.6);
  camera.lookAt(0, 1.25, 0);
  scene.add(new THREE.DirectionalLight(0x66F0FF, Math.PI));
  scene.add(new THREE.AmbientLight(0x334455, Math.PI));

  const gltf = await new Promise((resolve, reject) => {
    new THREE.GLTFLoader().load("/avatar.vrm", resolve, undefined, reject);
  });
  const vrm = gltf.userData.vrm;
  VRMUtils.removeUnnecessaryJoints(gltf.scene);
  scene.add(gltf.scene);
  vrm.scene.rotation.y = Math.PI; // face the camera

  let last = performance.now();
  function loop(now) {
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    const sway = Math.sin(now / 1400) * 0.03;
    vrm.scene.rotation.z = sway;
    if (vrm.expressionManager) {
      vrm.expressionManager.setValue("aa", speaking ? (0.35 + 0.45 * mouthOpen) : 0.02);
      vrm.expressionManager.setValue("blink", speaking ? 0 : (Math.sin(now / 900) > 0.985 ? 1 : 0));
    }
    vrm.update(dt);
    renderer.render(scene, camera);
    if (mode === "3d") requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  vrmReady = true;
  window.addEventListener("resize", () => {
    camera.aspect = threedDiv.clientWidth / threedDiv.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(threedDiv.clientWidth, threedDiv.clientHeight);
  });
}
</script>
</body>
</html>
"""
