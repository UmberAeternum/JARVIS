"""The Portal's single-file WebXR client: three.js room with a chat panel, a
kanban wall, and a desk for the user's own GLB models.

- immersive-vr on headsets (Quest Browser), immersive-ar attempt on phones,
  plain 2D fallback in desktop browsers.
- Text entry uses the DOM Overlay (supported by Quest Browser).
- Interaction: controller ray or hand pinch (both fire select) - select a
  kanban card to cycle it across the board.
- Plain string constant: JS template literals pass through untouched.
"""

PAGE_XR = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>J.A.R.V.I.S. — Portal</title>
<style>
  :root { --cyan:#66F0FF; --amber:#FFB454; --dim:#7FA8B8; }
  body { margin:0; background:#050A12; color:var(--cyan);
         font-family:Consolas,'Segoe UI',monospace; overflow:hidden; }
  #overlay { position:fixed; inset:0; display:none; pointer-events:none; }
  #overlay > * { pointer-events:auto; }
  #bar { position:absolute; bottom:0; left:0; right:0; display:flex; gap:8px;
         padding:10px; background:rgba(5,10,18,0.85); }
  #input { flex:1; background:#0E2233; border:1px solid #66F0FF44; color:var(--cyan);
           padding:10px; border-radius:8px; font-family:inherit; outline:none; }
  #send, #enter { background:#0E2233; color:var(--amber); border:1px solid #FFB45466;
                  border-radius:8px; padding:10px 14px; cursor:pointer; font-family:inherit; }
  #hud { position:absolute; top:0; left:0; right:0; padding:8px 12px; display:flex;
         justify-content:space-between; font-size:12px; color:var(--dim); }
  #notice { position:absolute; inset:0; display:flex; align-items:center;
            justify-content:center; text-align:center; padding:30px; font-size:14px;
            color:var(--dim); pointer-events:none; }
</style>
<script type="importmap">
{ "imports": { "three": "https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.module.js",
               "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.169.0/examples/jsm/" } }
</script>
</head>
<body>
  <div id="hud"><span>J.A.R.V.I.S. PORTAL</span><span id="status">2D FALLBACK</span></div>
  <div id="notice">Loading the room...</div>
  <div id="overlay">
    <div id="bar">
      <input id="input" placeholder="Ask J.A.R.V.I.S.">
      <button id="send">SEND</button>
      <button id="enter">ENTER VR</button>
    </div>
  </div>
<script type="module">
"use strict";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

const TOKEN = new URLSearchParams(location.search).get("t") || "";
const auth = () => ({ "X-Jarvis-Token": TOKEN, "Content-Type": "application/json" });
const notice = document.getElementById("notice");
const statusLine = document.getElementById("status");
const overlay = document.getElementById("overlay");
document.getElementById("enter").style.display = "none";
overlay.style.display = "block";

/* ---------------- state ---------------- */
let board = {tasks: []};
const history = [];
let thinking = false;

async function api(path, body) {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: auth(),
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error("HTTP " + response.status);
  return response.json();
}

/* ---------------- three.js room ---------------- */
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x050a12);
const camera = new THREE.PerspectiveCamera(60, innerWidth / innerHeight, 0.05, 40);
camera.position.set(0, 1.5, 2.2);
const renderer = new THREE.WebGLRenderer({antialias: true});
renderer.setSize(innerWidth, innerHeight);
renderer.xr.enabled = true;
document.body.appendChild(renderer.domElement);
scene.add(new THREE.HemisphereLight(0x88bbcc, 0x0a0f14, 1.4));
const key = new THREE.DirectionalLight(0x66f0ff, 1.2); key.position.set(1, 3, 1); scene.add(key);

// grid floor
const floor = new THREE.Mesh(
  new THREE.PlaneGeometry(12, 12),
  new THREE.MeshBasicMaterial({color: 0x0a1622})
);
floor.rotation.x = -Math.PI / 2; floor.position.y = 0; scene.add(floor);
const grid = new THREE.GridHelper(12, 24, 0x1a4a5c, 0x0e2a38);
scene.add(grid);

function makePanel(width, height) {
  const canvas = document.createElement("canvas");
  canvas.width = width * 300; canvas.height = height * 300;
  const texture = new THREE.CanvasTexture(canvas);
  const mesh = new THREE.Mesh(
    new THREE.PlaneGeometry(width, height),
    new THREE.MeshBasicMaterial({map: texture, transparent: true})
  );
  return {canvas, texture, mesh};
}

// chat panel (left)
const chatPanel = makePanel(1.5, 1.1);
chatPanel.mesh.position.set(-1.55, 1.55, -1.4);
chatPanel.mesh.rotation.y = 0.35;
scene.add(chatPanel.mesh);
let chatLines = ["LINK ONLINE"];

function drawChat() {
  const c = chatPanel.canvas, ctx = c.getContext("2d");
  ctx.fillStyle = "#050a12"; ctx.fillRect(0, 0, c.width, c.height);
  ctx.strokeStyle = "#66F0FF88"; ctx.lineWidth = 4;
  ctx.strokeRect(6, 6, c.width - 12, c.height - 12);
  ctx.fillStyle = "#66F0FF"; ctx.font = "42px Consolas";
  ctx.fillText("J.A.R.V.I.S.", 40, 90);
  ctx.fillStyle = "#7FA8B8"; ctx.font = "30px Consolas";
  chatLines.slice(-9).forEach((line, i) => ctx.fillText(line.slice(0, 58), 40, 170 + i * 62));
  chatPanel.texture.needsUpdate = true;
}
drawChat();

// kanban wall (center) with per-column canvases? one canvas, cards tracked
const kanban = makePanel(2.6, 1.5);
kanban.mesh.position.set(0, 1.75, -2.4);
scene.add(kanban.mesh);
let cardRects = [];   // {id, x, y, w, h} in canvas px, for ray->card mapping

function drawBoard() {
  const c = kanban.canvas, ctx = c.getContext("2d");
  ctx.fillStyle = "#050a12"; ctx.fillRect(0, 0, c.width, c.height);
  ctx.strokeStyle = "#FFB45466"; ctx.lineWidth = 4;
  ctx.strokeRect(6, 6, c.width - 12, c.height - 12);
  ctx.fillStyle = "#FFB454"; ctx.font = "48px Consolas";
  ctx.fillText("K A N B A N", 60, 100);
  const columns = ["todo", "doing", "done"];
  const names = {todo: "TO DO", doing: "DOING", done: "DONE"};
  cardRects = [];
  columns.forEach((col, ci) => {
    const x = 40 + ci * ((c.width - 80) / 3);
    const w = (c.width - 80) / 3 - 24;
    ctx.strokeStyle = "#66F0FF55"; ctx.strokeRect(x, 150, w, c.height - 210);
    ctx.fillStyle = "#7FA8B8"; ctx.font = "34px Consolas";
    ctx.fillText(names[col], x + 16, 200);
    let y = 250;
    board.tasks.filter(t => t.column === col).forEach(task => {
      ctx.fillStyle = "#0E2233"; ctx.fillRect(x, y, w, 120);
      ctx.strokeStyle = "#66F0FF88"; ctx.strokeRect(x, y, w, 120);
      ctx.fillStyle = "#66F0FF"; ctx.font = "30px Consolas";
      const words = task.text.split(" "); let line = "", yy = y + 44;
      for (const word of words) {
        if ((line + word).length > 22) { ctx.fillText(line, x + 14, yy); yy += 38; line = word + " "; }
        else line += word + " ";
      }
      ctx.fillText(line.trim(), x + 14, yy);
      cardRects.push({id: task.id, x: x, y: y, w: w, h: 120});
      y += 150;
    });
  });
  kanban.texture.needsUpdate = true;
}
drawBoard();

// desk (below) for BYO GLB models
const desk = new THREE.Mesh(
  new THREE.BoxGeometry(2.2, 0.06, 1.0),
  new THREE.MeshBasicMaterial({color: 0x0e2a38})
);
desk.position.set(0, 0.72, -0.9); scene.add(desk);
const loader = new GLTFLoader();
let modelIndex = 0;
async function loadModels() {
  try {
    const data = await api("/api/models");
    for (const name of data.models.slice(0, 4)) {
      loader.load("/model/" + encodeURIComponent(name) + "?t=" + TOKEN, (gltf) => {
        const box = new THREE.Box3().setFromObject(gltf.scene);
        const size = box.getSize(new THREE.Vector3());
        const scale = 0.45 / Math.max(size.x, size.y, size.z, 0.01);
        gltf.scene.scale.setScalar(scale);
        gltf.scene.position.set(-0.75 + modelIndex * 0.5, 0.75, -0.9);
        modelIndex += 1;
        scene.add(gltf.scene);
      }, undefined, () => {});
    }
  } catch (exc) { /* desk stays empty */ }
}
loadModels();

/* ---------------- interaction ---------------- */
const raycaster = new THREE.Raycaster();
const pointers = new Map();

function onSelect(event) {
  const controller = event.target;
  const uv = pickKanban(controller);
  if (uv) {
    api("/api/board", {action: "cycle", id: uv.id})
      .then((b) => { board = b; drawBoard(); })
      .catch((exc) => console.warn(exc));
  }
}
function pickKanban(controller) {
  raycaster.setFromCamera ? null : null;
  const tempMatrix = new THREE.Matrix4();
  tempMatrix.identity().extractRotation(controller.matrixWorld);
  raycaster.ray.origin.setFromMatrixPosition(controller.matrixWorld);
  raycaster.ray.direction.set(0, 0, -1).applyMatrix4(controller.matrixWorld);
  const hits = raycaster.intersectObject(kanban.mesh);
  if (!hits.length) return null;
  const uv = hits[0].uv;
  if (!uv) return null;
  const px = uv.x * kanban.canvas.width;
  const py = (1 - uv.y) * kanban.canvas.height;
  for (const rect of cardRects) {
    if (px >= rect.x && px <= rect.x + rect.w && py >= rect.y && py <= rect.y + rect.h) {
      return {id: rect.id};
    }
  }
  return null;
}

function setupController(index) {
  const controller = renderer.xr.getController(index);
  controller.addEventListener("selectstart", onSelect);
  scene.add(controller);
  const ray = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, 0, -1)]),
    new THREE.LineBasicMaterial({color: 0x66f0ff})
  );
  ray.scale.z = 2.5; controller.add(ray);
}
setupController(0); setupController(1);

/* ---------------- chat ---------------- */
async function sendChat(text) {
  if (!text.trim() || thinking) return;
  thinking = true;
  chatLines.push("YOU: " + text);
  chatLines.push("..."); drawChat();
  try {
    const data = await api("/api/chat", {text: text});
    chatLines.pop();
    const reply = data.reply || data.error || "(no response)";
    chatLines.push("J: " + reply);
    drawBoard();
    if ("speechSynthesis" in window) {
      const utterance = new SpeechSynthesisUtterance(reply);
      speechSynthesis.cancel(); speechSynthesis.speak(utterance);
    }
  } catch (exc) {
    chatLines.pop(); chatLines.push("LINK DOWN: " + exc.message);
  } finally {
    thinking = false; drawChat();
  }
  drawChat();
}
document.getElementById("send").addEventListener("click", () => {
  const field = document.getElementById("input");
  const text = field.value; field.value = ""; sendChat(text);
});
document.getElementById("input").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    const field = document.getElementById("input");
    const text = field.value; field.value = ""; sendChat(text);
  }
});

/* ---------------- board + models refresh ---------------- */
async function refreshBoard() {
  try { board = await api("/api/board"); drawBoard(); } catch (exc) { /* offline */ }
}
refreshBoard();
setInterval(refreshBoard, 10000);

/* ---------------- XR session ---------------- */
const enterButton = document.getElementById("enter");
if (navigator.xr) {
  navigator.xr.isSessionSupported("immersive-vr").then((supported) => {
    if (supported) { enterButton.style.display = "block"; notice.textContent = "Room ready. ENTER VR, Sir."; statusLine.textContent = "WEBXR READY"; }
    else { notice.textContent = "WebXR immersive-vr not available here - 2D fallback active. On a headset, open this URL in its browser."; }
  }).catch(() => { notice.textContent = "WebXR check failed - 2D fallback active."; });
} else {
  notice.textContent = "WebXR not available in this browser - 2D fallback active.";
}
enterButton.addEventListener("click", async () => {
  try {
    const session = await navigator.xr.requestSession("immersive-vr", {
      optionalFeatures: ["local-floor", "bounded-floor", "hand-tracking", "dom-overlay"],
      domOverlay: {root: overlay},
    });
    renderer.xr.setReferenceSpaceType("local-floor");
    await renderer.xr.setSession(session);
    notice.textContent = "";
  } catch (exc) {
    notice.textContent = "XR session refused: " + exc.message;
  }
});

/* ---------------- render loop (2D fallback + XR) ---------------- */
renderer.setAnimationLoop(() => { renderer.render(scene, camera); });
window.addEventListener("resize", () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});
notice.textContent = "Room ready - 2D fallback. ENTER VR on a headset.";
</script>
</body>
</html>
"""
