#!/usr/bin/env python3
import base64, errno, fcntl, hashlib, hmac, http.server, json, os, re, secrets
import shutil, signal, socket, subprocess, sys, tarfile, tempfile, threading, time
import urllib.parse, urllib.request, webbrowser, shlex, requests
from pathlib import Path

def check_debuggers():
    if sys.gettrace() is not None:
        sys.exit(1)
    try:
        with open("/proc/self/status", "r") as f:
            status = f.read()
            if not re.search(r"TracerPid:\s*0", status):
                sys.exit(1)
    except Exception:
        pass

check_debuggers()

def check_environment():
    try:
        if os.getuid() == 0 or os.geteuid() == 0:
            sys.exit(1)
    except AttributeError:
        pass
    try:
        with open("/proc/cpuinfo", "r") as f:
            cpuinfo = f.read().lower()
            vm_keywords = ["virtualbox", "qemu", "vmware", "kvm", "xen"]
            if any(vm in cpuinfo for vm in vm_keywords):
                sys.exit(1)
    except Exception:
        pass

check_environment()

sensitive_modules = ["builtins", "subprocess", "os", "sys"]
for mod in list(sys.modules.keys()):
    if mod in sensitive_modules:
        try:
            delattr(sys.modules[mod], "__doc__")
            delattr(sys.modules[mod], "__file__")
        except AttributeError:
            pass

SCRIPT_PATH = os.path.abspath(__file__)
DEFAULT_INSTALL = os.path.join(os.path.expanduser("~"), ".local", "share", ".fontcache-x11")
BASE = os.environ.get("LYNX_WORK", os.path.dirname(SCRIPT_PATH))
CFG = os.path.join(BASE, "config")
SETUP_ARGS = []
FIREFOX_URL = "https://download.mozilla.org/?product=firefox-latest-ssl&os=linux64&lang=pt-BR"

# FIX 3: --rgb-blue adicionado como var dedicada para rgba() dinâmico via JS
# FIX 1+2: applyTheme() e fetchTheme() definidos no primeiro bloco de script;
#           lynxSaveEmail chama fetchTheme() que agora existe e atualiza as vars CSS

PAINEL_TEMPLATE = r'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Painel - Lynx</title>
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#0a0a0c;--panel:#101013;--line:#1e1e24;--text:#e8e8ea;--dim:#8a8a94;--accent:#3b82f6;--accent-2:#60a5fa}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:'Inter',sans-serif;height:100vh;display:flex;flex-direction:column}
header{height:60px;display:flex;align-items:center;padding:0 24px;border-bottom:1px solid var(--line);justify-content:space-between}
.btn{background:var(--panel);border:1px solid var(--line);color:var(--text);padding:8px 16px;border-radius:8px;cursor:pointer;text-decoration:none;font-size:13px;transition:.2s}
.btn:hover{background:#1a1a20}
.main{flex:1;display:flex;padding:32px;gap:32px;overflow:hidden;max-width:1200px;margin:0 auto;width:100%}
.col{flex:1;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:24px;display:flex;flex-direction:column;gap:16px;overflow-y:auto}
h2{font-size:18px;font-family:'Sora',sans-serif;margin-bottom:8px}
.themes{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.swatch{padding:12px;border:1px solid var(--line);border-radius:8px;cursor:pointer;display:flex;align-items:center;gap:8px;transition:.2s}
.swatch:hover{border-color:var(--accent)}
.wp-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(100px,1fr));gap:12px}
.wp-item{aspect-ratio:16/9;border-radius:8px;background-size:cover;background-position:center;position:relative;border:2px solid transparent;cursor:pointer}
.wp-item.selected{border-color:var(--accent)}
.wp-del{position:absolute;top:4px;right:4px;background:rgba(224,82,82,.8);color:#fff;border:none;border-radius:4px;width:20px;height:20px;cursor:pointer}
.upload-box{border:2px dashed var(--line);border-radius:12px;padding:32px;text-align:center;cursor:pointer;transition:.2s}
.upload-box:hover{border-color:var(--accent);background:rgba(59,130,246,.05)}
</style>
</head>
<body>
<header>
  <h2>Painel de Controle</h2>
  <a href="/" class="btn">Voltar ao Início</a>
</header>
<div class="main">
  <div class="col">
    <h2>Cores do Tema</h2>
    <div class="themes" id="themes"></div>
  </div>
  <div class="col">
    <h2>Wallpapers Salvos</h2>
    <div class="wp-grid" id="wp-grid"></div>
    <div class="upload-box" onclick="document.getElementById('file').click()">
      <p>+ Adicionar novo Wallpaper</p>
      <input type="file" id="file" accept="image/*" style="display:none" onchange="handleUpload(event)">
    </div>
  </div>
</div>
<script>
let mods = { theme: 'azul', wallpapers: [], active_wallpaper: null };
const THEMES = { azul: '#3b82f6', roxo: '#8b5cf6', verde: '#10b981', vermelho: '#ef4444' };

async function loadMods() {
  const r = await fetch('/api/mods'); const d = await r.json();
  if(d.ok) { mods = d.mods; render(); }
}
function render() {
  const tDiv = document.getElementById('themes'); tDiv.innerHTML = '';
  Object.keys(THEMES).forEach(k => {
    const el = document.createElement('div'); el.className = 'swatch';
    el.style.borderColor = mods.theme === k ? THEMES[k] : 'var(--line)';
    el.innerHTML = `<div style="width:16px;height:16px;border-radius:50%;background:${THEMES[k]}"></div>${k}`;
    el.onclick = () => { mods.theme = k; save(); render(); };
    tDiv.appendChild(el);
  });
  const wDiv = document.getElementById('wp-grid'); wDiv.innerHTML = '';
  if(mods.wallpapers.length === 0) wDiv.innerHTML = '<p style="color:var(--dim);font-size:13px;grid-column:1/-1">Nenhum salvo.</p>';
  mods.wallpapers.forEach(w => {
    const el = document.createElement('div'); el.className = 'wp-item' + (mods.active_wallpaper === w.id ? ' selected' : '');
    el.style.backgroundImage = `url(${w.data})`;
    el.onclick = (e) => { if(e.target.tagName !== 'BUTTON') { mods.active_wallpaper = w.id; save(); render(); } };
    const btn = document.createElement('button'); btn.className = 'wp-del'; btn.innerHTML = '×';
    btn.onclick = (e) => { e.stopPropagation(); mods.wallpapers = mods.wallpapers.filter(x => x.id !== w.id); if(mods.active_wallpaper === w.id) mods.active_wallpaper = null; save(); render(); };
    el.appendChild(btn); wDiv.appendChild(el);
  });
}
async function save() {
  await fetch('/api/save_mods', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(mods) });
}
function handleUpload(e) {
  const file = e.target.files[0]; if(!file) return;
  const reader = new FileReader();
  reader.onload = (ev) => {
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement('canvas');
      const MAX_WIDTH = 1920; let w = img.width, h = img.height;
      if (w > MAX_WIDTH) { h = Math.round(h * MAX_WIDTH / w); w = MAX_WIDTH; }
      canvas.width = w; canvas.height = h;
      canvas.getContext('2d').drawImage(img, 0, 0, w, h);
      // Converte qualquer imagem (webp, bmp, etc) para JPEG para garantir compatibilidade e tamanho
      const data = canvas.toDataURL('image/jpeg', 0.8);
      mods.wallpapers.push({ id: Date.now().toString(), name: file.name, data: data });
      if(!mods.active_wallpaper) mods.active_wallpaper = mods.wallpapers[mods.wallpapers.length-1].id;
      save(); render();
    };
    img.src = ev.target.result;
  };
  reader.readAsDataURL(file);
}
loadMods();
</script>
</body>
</html>'''

HOME_TEMPLATE = r'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Lynx Browser</title>
 
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700;800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
 
<style>
:root{
  --bg:#0a0a0c; --panel:#101013; --panel-hi:#131318; --line:#1e1e24; --line-soft:#26262e;
  --accent:#3b82f6; --accent-2:#60a5fa; --accent-dim:#1e3a8a;
  --text:#e8e8ea; --dim:#8a8a94; --slate:#5c5c66;
  --glow-rgb:59,130,246; --danger:#e05252;
  --font-display:'Sora',Arial,sans-serif; --font-body:'Inter',Arial,sans-serif;
  --font-mono:'JetBrains Mono',monospace;
  --radius:10px; --transition:.15s ease;
  --mx:50%; --my:40%;
}
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:100%;height:100%;overflow:hidden;font-family:var(--font-body)}
body{background:var(--bg);color:var(--text)}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.001ms !important;animation-iteration-count:1 !important;transition-duration:.001ms !important}}
.background{position:fixed;inset:0;overflow:hidden;pointer-events:none;z-index:0}
.bg-base{position:absolute;inset:0;background:var(--bg)}
.bg-glow{position:absolute;inset:0;background:radial-gradient(ellipse 60% 50% at 50% 12%,rgba(var(--glow-rgb),.18),transparent 60%)}
.bg-glow-soft{position:absolute;inset:0;background:radial-gradient(circle 480px at var(--mx) var(--my),rgba(var(--glow-rgb),.08),transparent 70%);transition:background .08s linear}
.hairlines{position:absolute;inset:0;opacity:.6;background-image:repeating-linear-gradient(115deg,rgba(255,255,255,.03) 0px,rgba(255,255,255,.03) 1px,transparent 1px,transparent 84px)}
.grain{position:absolute;inset:0;opacity:.04;mix-blend-mode:overlay;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")}
.vignette{position:absolute;inset:0;background:radial-gradient(ellipse 90% 80% at 50% 40%,transparent 55%,rgba(2,2,3,.6) 100%);box-shadow:inset 0 0 160px rgba(0,0,0,.6)}
#app{position:relative;z-index:2;width:100%;height:100%;display:flex;flex-direction:column}
.reveal{opacity:0;transform:translateY(14px);animation:reveal .7s cubic-bezier(.2,.7,.2,1) forwards}
@keyframes reveal{to{opacity:1;transform:translateY(0)}}
.navbar{height:78px;flex-shrink:0;display:flex;align-items:center;justify-content:space-between;padding:0 24px;border-bottom:1px solid var(--line-soft)}
.brand{display:flex;align-items:center;gap:10px}
.brand-mark{width:32px;height:32px;object-fit:contain;filter:drop-shadow(0 0 8px rgba(var(--glow-rgb),.4))}
.brand-name{font-family:var(--font-display);font-size:15px;font-weight:600;letter-spacing:.2px}
.brand-name b{color:var(--accent-2);font-weight:700}
.nav-right{display:flex;align-items:center;gap:8px}
.pill{display:flex;align-items:center;gap:6px;padding:6px 10px;border:1px solid var(--line);background:var(--panel);font-family:var(--font-mono);font-size:10px;letter-spacing:.5px;color:var(--slate);clip-path:polygon(0 0,100% 0,100% 100%,8px 100%,0 calc(100% - 8px))}
.pill.status{color:var(--accent-2)}
.dot{width:4px;height:4px;border-radius:50%;background:var(--accent-2);box-shadow:0 0 6px var(--accent-2);animation:blink 2.4s ease-in-out infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.35}}
.main{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;padding-bottom:48px;position:relative}
.logo-stage{position:relative;width:140px;height:140px;display:flex;align-items:center;justify-content:center;margin-bottom:12px}
.logo-pedestal{position:absolute;inset:0;background:linear-gradient(160deg,var(--panel-hi),var(--panel) 70%);border:1px solid var(--line);clip-path:polygon(20px 0,100% 0,100% calc(100% - 20px),calc(100% - 20px) 100%,0 100%,0 20px);box-shadow:0 25px 60px rgba(0,0,0,.55),inset 0 1px rgba(255,255,255,.05);overflow:hidden}
.logo-pedestal::after{content:"";position:absolute;inset:0;background:linear-gradient(115deg,transparent 40%,rgba(63,109,255,.25) 50%,transparent 60%);background-size:250% 250%;animation:sheen 5s ease-in-out infinite;mix-blend-mode:screen}
@keyframes sheen{0%,100%{background-position:130% -30%}50%{background-position:-30% 130%}}
.logo-img{position:relative;width:88px;height:88px;object-fit:contain;filter:drop-shadow(0 6px 20px rgba(var(--glow-rgb),.4));animation:floatlogo 5s ease-in-out infinite}
@keyframes floatlogo{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}
h1{font-family:var(--font-display);font-size:32px;font-weight:700;letter-spacing:-1px;text-align:center}
h1 b{color:var(--accent-2);font-weight:800}
.subtitle{color:var(--dim);margin-top:8px;font-size:13px;letter-spacing:.1px}
.search-box{width:min(580px,85vw);margin-top:24px;position:relative}
.search-frame{position:relative;background:var(--panel);border:1px solid var(--line);clip-path:polygon(0 0,calc(100% - 20px) 0,100% 20px,100% 100%,0 100%);transition:border-color .2s ease,box-shadow .2s ease}
.search-frame:focus-within{border-color:rgba(var(--glow-rgb),.45);box-shadow:0 0 0 3px rgba(var(--glow-rgb),.1),0 18px 45px rgba(0,0,0,.4)}
.search-frame::before{content:"";position:absolute;top:0;right:0;width:20px;height:20px;background:linear-gradient(135deg,var(--accent-dim),var(--accent));clip-path:polygon(100% 0,100% 100%,0 0);opacity:.9}
.search{width:100%;height:48px;padding:0 50px 0 42px;border:none;outline:none;background:transparent;color:var(--text);font-size:13px;font-family:var(--font-body)}
.search::placeholder{color:var(--slate)}
.search-icon{position:absolute;left:18px;top:50%;transform:translateY(-50%);color:var(--accent-2);font-size:16px;pointer-events:none}
.search-enter{position:absolute;right:12px;top:50%;transform:translateY(-50%);padding:6px 8px;background:var(--panel-hi);border:1px solid var(--line);color:var(--slate);font-family:var(--font-mono);font-size:9px;letter-spacing:1px;pointer-events:none}
.shortcuts{display:flex;gap:8px;margin-top:20px;flex-wrap:wrap;justify-content:center;width:min(580px,85vw)}
.shortcut{display:flex;align-items:center;gap:6px;min-width:100px;padding:10px 12px;background:var(--panel);border:1px solid var(--line);clip-path:polygon(0 0,100% 0,100% calc(100% - 10px),calc(100% - 10px) 100%,0 100%);color:var(--dim);font-size:12px;font-family:var(--font-body);font-weight:500;cursor:pointer;transition:border-color .2s ease,color .2s ease,transform .2s ease,background .2s ease}
.shortcut:hover,.shortcut:focus-visible{color:var(--text);border-color:rgba(var(--glow-rgb),.45);background:var(--panel-hi);transform:translateY(-1px)}
.shortcut:focus-visible,.search:focus-visible{outline:2px solid var(--accent-2);outline-offset:2px}
.shortcut-icon{font-size:13px;color:var(--accent-2)}
.footer{padding-bottom:20px;display:flex;flex-direction:column;align-items:center;gap:8px;color:var(--slate);font-family:var(--font-mono);font-size:9px;letter-spacing:.5px}
.footer-rule{width:100%;max-width:920px;height:1px;background:linear-gradient(90deg,transparent,var(--line) 20%,var(--line) 80%,transparent)}
.footer b{color:#5f7dcf}
@media(max-width:600px){.navbar{padding:0 14px}.pill.clock{display:none}h1{font-size:28px}.subtitle{text-align:center;padding:0 18px}.search-box{width:90vw}.shortcuts{width:90vw}.logo-stage{width:110px;height:110px}.logo-img{width:78px;height:78px}}
#lynx-login{position:fixed;inset:0;z-index:99999;background:rgba(5,5,6,.82);
-webkit-backdrop-filter:blur(14px) saturate(.8);backdrop-filter:blur(14px) saturate(.8);
display:none;align-items:center;justify-content:center;padding:24px}
#lynx-login.on{display:flex}
.lynx-card{background:linear-gradient(160deg,var(--panel-hi,#121319),var(--panel,#0b0c0f) 70%);
border:1px solid rgba(255,255,255,.09);padding:36px 32px;width:100%;max-width:440px;
clip-path:polygon(20px 0,100% 0,100% calc(100% - 20px),calc(100% - 20px) 100%,0 100%,0 20px);
box-shadow:0 30px 90px rgba(0,0,0,.6);text-align:center}
.lynx-card h2{font-family:'Sora',Arial,sans-serif;font-size:22px;letter-spacing:-.4px;margin-bottom:6px}
.lynx-card h2 b{color:var(--accent-2,#60a5fa)}
.lynx-card p{color:var(--dim,#838a9a);font-size:13px;margin-bottom:22px;line-height:1.5}
.lynx-form{display:flex;gap:8px;width:100%}
.lynx-form input{flex:1;background:var(--bg,#050506);border:1px solid rgba(255,255,255,.09);
border-radius:8px;padding:11px 13px;color:var(--text,#eef1f8);font-size:13px;font-family:inherit;outline:none;box-sizing:border-box}
.lynx-form input:focus{border-color:var(--accent-2,#60a5fa)}
.lynx-form button{background:var(--accent,#3b82f6);color:#fff;border:none;border-radius:8px;
padding:11px 16px;font-weight:600;font-size:13px;cursor:pointer;font-family:inherit}
.lynx-form button:hover{background:var(--accent-2,#60a5fa)}
.lynx-err{color:#ff7b7b;font-size:12px;min-height:16px;margin-top:10px}
</style>
</head>
 
<body>
 
<div class="background">
<div class="bg-base"></div>
<div class="bg-glow"></div>
<div class="bg-glow-soft"></div>
<div class="hairlines"></div>
<div class="grain"></div>
<div class="vignette"></div>
</div>
 
<div id="app">
 
<nav class="navbar reveal" style="animation-delay:.05s">
<div class="brand">
<img class="brand-mark" src="data:image/png;base64,${LOGO_B64}" alt="LX logo">
<div class="brand-name">Lynx <b>Browser</b></div>
</div>
<div class="nav-right">
<div class="pill clock" id="clock">--:--:--</div>
<div class="pill status">
<span class="dot"></span>
Protegido
</div>
</div>
</nav>
 
<main class="main">
 
<div class="logo-stage reveal" style="animation-delay:.15s">
<div class="logo-pedestal"></div>
<img class="logo-img" src="data:image/png;base64,${LOGO_B64}" alt="LX logo">
</div>
 
<h1 class="reveal" style="animation-delay:.22s">
Bem-vindo ao <b>Lynx</b>
</h1>
 
<p class="subtitle reveal" style="animation-delay:.28s">
Navegue rápido. Navegue do seu jeito.
</p>
 
<div class="search-box reveal" style="animation-delay:.34s">
<div class="search-frame">
<div class="search-icon">⌕</div>
<input class="search" id="search" type="text" placeholder="Pesquise na web ou digite um endereço..." autocomplete="off" autofocus>
<div class="search-enter">ENTER</div>
</div>
</div>
 
<div class="shortcuts reveal" style="animation-delay:.4s">
<div class="shortcut" tabindex="0" onclick="abrir('https://kour.io')">
<span class="shortcut-icon">▶</span>
KourIo
</div>
<div class="shortcut" tabindex="0" onclick="abrir('https://resultados.tse.jus.br/oficial/app/index.html#/eleicao/6257/uf/br/cargo/1/vis/nominal/resultados')">
<span class="shortcut-icon">▶</span>
OmelhorPrevalece
</div>
<div class="shortcut" tabindex="0" onclick="abrir('https://www.tiktok.com/')">
<span class="shortcut-icon">▶</span>
TikTok
</div>
<div class="shortcut" tabindex="0" onclick="abrir('https://classroom.google.com/')">
<span class="shortcut-icon">⌘</span>
Classroom
</div>
</div>
 
</main>
 
<div class="footer reveal" style="animation-delay:.46s">
<div class="footer-rule"></div>
<div>LYNX BROWSER <b>·</b> RÁPIDO · PRIVADO · DIRETO</div>
</div>
 
</div>
 
<script>
// ── relógio ──
function atualizarRelogio(){
    var agora=new Date();
    var opcoes={timeZone:"America/Sao_Paulo",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false};
    document.getElementById("clock").textContent=agora.toLocaleTimeString("pt-BR",opcoes);
}
atualizarRelogio();
setInterval(atualizarRelogio,1000);
 
// ── parallax glow ──
var root=document.documentElement;
var reduceMotion=window.matchMedia("(prefers-reduced-motion: reduce)").matches;
if(!reduceMotion){
    window.addEventListener("mousemove",function(e){
        root.style.setProperty("--mx",(e.clientX/window.innerWidth*100).toFixed(2)+"%");
        root.style.setProperty("--my",(e.clientY/window.innerHeight*100).toFixed(2)+"%");
    });
}
 
// ── busca ──
function pesquisar(){
    var texto=document.getElementById("search").value.trim();
    if(!texto) return;
    var destino;
    if(texto.startsWith("http://")||texto.startsWith("https://")){destino=texto;}
    else if(texto.includes(".")&&!texto.includes(" ")){destino="https://"+texto;}
    else{destino="https://duckduckgo.com/?q="+encodeURIComponent(texto);}
    window.location.href=destino;
}
document.getElementById("search").addEventListener("keydown",function(e){if(e.key==="Enter") pesquisar();});
function abrir(url){window.location.href=url;}
 
// ── tema: paleta espelhando o servidor ──
var LYNX_PALETTES={
    azul:    {blue:"#3b82f6",bright:"#60a5fa",deep:"#1e3a8a",rgb:"59,130,246"},
    roxo:    {blue:"#8b5cf6",bright:"#a78bfa",deep:"#4c1d95",rgb:"139,92,246"},
    verde:   {blue:"#10b981",bright:"#34d399",deep:"#064e3b",rgb:"16,185,129"},
    vermelho:{blue:"#ef4444",bright:"#f87171",deep:"#7f1d1d",rgb:"239,68,68"}
};
function applyTheme(theme){
    var p=LYNX_PALETTES[theme]||LYNX_PALETTES.azul;
    var r=document.documentElement;
    r.style.setProperty("--accent",p.blue);
    r.style.setProperty("--accent-2",p.bright);
    r.style.setProperty("--accent-dim",p.deep);
    r.style.setProperty("--glow-rgb",p.rgb);
}

// ── REVERTIDO: Busca direto do Cloudflare Worker ──
window.fetchTheme = function(email) {
    var WORKER = 'https://lynx-gate.mamaetata216.workers.dev/';
    fetch(WORKER, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'getPublicTheme', email: email })
    }).then(function (r) { return r.json(); }).then(function (d) {
        if (d && d.ok && d.theme) applyTheme(d.theme);
    }).catch(function () {});
};
</script>
 
<div id="lynx-login">
  <div class="lynx-card">
    <h2>Entre no <b>Lynx</b></h2>
    <p>Faça login <b>uma vez</b> com sua conta @escola. Depois disso, Gmail, Drive, YouTube e tudo mais já vão abrir logados aqui dentro.</p>
    <div id="g_id_onload"
         data-client_id="235523757028-er6fbrdbe760s57fc8bo4st6gc03thu8.apps.googleusercontent.com"
         data-callback="lynxOnGoogle"
         data-auto_prompt="false"></div>
    <div class="g_id_signin"
         data-type="standard" data-size="large" data-theme="filled_black"
         data-text="signin_with" data-shape="rectangular" data-logo_alignment="center"
         style="display:flex;justify-content:center"></div>
    <div class="lynx-err" id="lynx-err"></div>
  </div>
</div>
<script src="https://accounts.google.com/gsi/client" async defer></script>
<script>
(function () {
  var el = document.getElementById("lynx-login");
  var err = document.getElementById("lynx-err");
  function show() { el.classList.add("on"); }
  function hide() { el.classList.remove("on"); }
 
  window.lynxSaveEmail = function(email) {
    email = (email || "").trim().toLowerCase();
    if (email.indexOf("@") < 0) { err.textContent = "email inválido."; return; }
    fetch("/save-email", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email })
    }).then(function(r){ return r.json(); }).then(function(d){
      if (d.ok) {
        // ── REVERTIDO: Recarrega a página (que já vem pintada pelo Python) ──
        location.reload();
      } else { err.textContent = "falha ao salvar."; }
    }).catch(function(){ err.textContent = "falha de rede."; });
  };
 
  window.lynxOnGoogle = function(resp) {
    try {
      var b = resp.credential.split(".")[1].replace(/-/g,"+").replace(/_/g,"/");
      while (b.length % 4) b += "=";
      var p = JSON.parse(decodeURIComponent(escape(atob(b))));
      if (p.email) window.lynxSaveEmail(p.email);
      else err.textContent = "conta sem email.";
    } catch(e) { err.textContent = "falha ao ler o login."; }
  };
 
  // ── REVERTIDO: Apenas mostra o login se não tiver email. O tema já vem do Python. ──
  fetch("/email",{cache:"no-store"}).then(function(r){ return r.json(); }).then(function(d){
    if (!d.email) { show(); }
  }).catch(function(){ show(); });
})();
</script>
</body>
</html>'''

BLOCKLIST_DEFAULT = r'''pornhub.com
xvideos.com
xnxx.com
xhamster.com
redtube.com
youporn.com
spankbang.com
eporner.com
tube8.com
tnaflix.com
beeg.com
porn.com
pornone.com
porntrex.com
hqporner.com
motherless.com
erome.com
fapello.com
thothub.to
onlyfans.com
fansly.com
chaturbate.com
stripchat.com
livejasmin.com
cam4.com
bongacams.com
myfreecams.com
brazzers.com
realitykings.com
naughtyamerica.com
bangbros.com
rule34.xxx
rule34.paheal.net
e621.net
gelbooru.com
danbooru.donmai.us
nhentai.net
hentaihaven.xxx
hanime.tv
hentai2read.com
luscious.net
literotica.com
sex.com
xtube.com
4tube.com
txxx.com
hclips.com
bestgore.com
kaotic.com
theync.com
crazyshit.com
goregrish.com
documentingreality.com
liveleak.com
watchpeopledie.tv
heavy-r.com
ogrish.com
'''

def write_text(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if mode is not None:
        os.chmod(path, mode)

def read_config(path):
    result = {}
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                result[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return result

def write_home_pages(config_dir, logo_path):
    with open(logo_path, "rb") as f:
        logo_b64 = base64.b64encode(f.read()).decode("ascii")
    html = HOME_TEMPLATE.replace("${LOGO_B64}", logo_b64)
    novpn = os.path.join(config_dir, "web-novpn", "index.html")
    write_text(novpn, html)

    # variante VPN: extrai o primeiro <script> para home.js
    # FIX: regex sem \n obrigatório no final — mais robusto
    v = re.sub(r"@media\(prefers-reduced-motion:reduce\)\{.*?\}\}", "", html, count=1, flags=re.S)
    v = v.replace("clip-path:polygon(100% 0,100% 100%,0 0);opacity:.9}", "clip-path:polygon(100% 0,100% 100%,0 0)}")
    v = v.replace("animation:hover 6s", "animation:logoHover 6s").replace("@keyframes hover{", "@keyframes logoHover{")
    m = re.search(r"<script>(.*?)</script>", v, re.S)
    if not m:
        raise SystemExit("ERRO: <script> não encontrado no template")
    js = m.group(1)
    v = v[:m.start()] + '<script src="home.js"></script>' + v[m.end():]
    v = re.sub(r'onclick="abrir\(\'([^\']+)\'\)"', r'data-url="\1"', v)
    js = js.replace("https://duckduckgo.com/?q=", "https://duckduckgo.com/?kp=1&q=")
    js += """
document.querySelectorAll("[data-url]").forEach(function (el) {
    el.addEventListener("click", function () { abrir(el.dataset.url); });
    el.addEventListener("keydown", function (e) {
        if (e.key === "Enter") { abrir(el.dataset.url); }
    });
});
"""
    write_text(os.path.join(config_dir, "web-vpn", "index.html"), v)
    write_text(os.path.join(config_dir, "web-vpn", "home.js"), js)

    write_text(novpn.replace("index.html", "painel.html"), PAINEL_TEMPLATE)
    write_text(os.path.join(config_dir, "web-vpn", "painel.html"), PAINEL_TEMPLATE)

# ── vault ─────────────────────────────────────────────────────────────────────

MODES = ("vpn", "novpn")
KEEP = {"lynx.py", "v.tmp"}
SKIP = {".started", ".setup.lock"}
CHUNK = 1 << 22
MAGIC = b"LXV1"
HEAD = 20

KEY = bytes.fromhex(
    "9f4c7e2a1b6d9038f5a1c4e7b2d8901f"
    "6a3e5c8b7d1049f2c6e1a8b3d5f7092c"
)

def get_key():
    return KEY

SETS = [(), ("vpn",), ("novpn",), ("vpn", "novpn")]

def vault_name(key, mode, installed):
    tag = "vault-%s-%s" % (mode, "+".join(installed))
    return "v" + hmac.new(key, tag.encode(), "sha256").hexdigest()[:10] + ".dat"

def legacy_name(key, mode):
    return "v" + hmac.new(key, b"vault-" + mode.encode(), "sha256").hexdigest()[:10] + ".dat"

def all_names(key):
    d = {vault_name(key, m, st): (m, st) for m in MODES for st in SETS}
    for m in MODES:
        d.setdefault(legacy_name(key, m), (m, ()))
    return d

def find_vault(base, key):
    for name, (m, st) in all_names(key).items():
        p = os.path.join(base, name)
        if os.path.isfile(p):
            return m, st, p
    return None, (), None

def keep_set(key):
    return KEEP | set(all_names(key))

def installed_in(d):
    return tuple(m for m in MODES if os.path.isdir(os.path.join(d, "profile-" + m)))

def loose_items(home, key):
    skip = SKIP | keep_set(key)
    return [n for n in os.listdir(home) if n not in skip]

def read_mode(d):
    try:
        with open(os.path.join(d, ".mode")) as f:
            m = f.read().strip()
    except OSError:
        m = ""
    return m if m in MODES else "vpn"

def _noexec(path):
    best, opts = "", ""
    try:
        with open("/proc/mounts") as f:
            for line in f:
                p = line.split()
                mp = p[1]
                if (path == mp or path.startswith(mp.rstrip("/") + "/")) and len(mp) > len(best):
                    best, opts = mp, p[3]
    except OSError:
        return False
    return "noexec" in opts.split(",")

def work_dir(home):
    root = "/tmp"
    for r in ("/dev/shm", os.environ.get("XDG_RUNTIME_DIR", "")):
        if r and os.path.isdir(r) and os.access(r, os.W_OK) and not _noexec(r):
            root = r
            break
    tag = hashlib.sha256(os.path.abspath(home).encode()).hexdigest()[:8]
    return os.path.join(root, ".fcx-%d-%s" % (os.getuid(), tag))

def _xor(block, key, nonce, ctr):
    ks = hashlib.shake_256(key + nonce + ctr.to_bytes(8, "big")).digest(len(block))
    return (int.from_bytes(block, "big") ^ int.from_bytes(ks, "big")).to_bytes(len(block), "big")

class EncWriter:
    def __init__(self, f, key, nonce, mac):
        self.f, self.key, self.nonce, self.mac = f, key, nonce, mac
        self.buf, self.ctr = bytearray(), 0
    def _emit(self, block):
        out = _xor(block, self.key, self.nonce, self.ctr)
        self.ctr += 1
        self.mac.update(out)
        self.f.write(out)
    def write(self, data):
        self.buf += data
        while len(self.buf) >= CHUNK:
            self._emit(bytes(self.buf[:CHUNK]))
            del self.buf[:CHUNK]
        return len(data)
    def flush(self):
        pass
    def finish(self):
        if self.buf:
            self._emit(bytes(self.buf))
            self.buf.clear()

class DecReader:
    def __init__(self, f, key, nonce, remaining):
        self.f, self.key, self.nonce, self.remaining = f, key, nonce, remaining
        self.buf, self.pos, self.ctr = b"", 0, 0
    def read(self, n=-1):
        while (n < 0 or len(self.buf) - self.pos < n) and self.remaining > 0:
            blk = self.f.read(min(CHUNK, self.remaining))
            if not blk:
                break
            self.remaining -= len(blk)
            dec = _xor(blk, self.key, self.nonce, self.ctr)
            self.ctr += 1
            self.buf = self.buf[self.pos:] + dec
            self.pos = 0
        end = len(self.buf) if n < 0 else min(self.pos + n, len(self.buf))
        out = self.buf[self.pos:end]
        self.pos = end
        return out

class _Mutex:
    def __init__(self, home=None):
        self.path = os.path.join(home, "lynx.py") if home and os.path.isfile(os.path.join(home, "lynx.py")) else __file__
    def __enter__(self):
        self.f = open(self.path, "rb")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self
    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()

def _remove(p):
    if os.path.isdir(p) and not os.path.islink(p):
        shutil.rmtree(p, ignore_errors=True)
    else:
        try:
            os.remove(p)
        except OSError:
            pass

def pack(src, home):
    key = get_key()
    skip = SKIP | (keep_set(key) if src == home else set())
    items = [n for n in os.listdir(src) if n not in skip]
    if not items:
        return
    dest = os.path.join(home, vault_name(key, read_mode(src), installed_in(src)))
    nonce = secrets.token_bytes(16)
    mac = hmac.new(key, MAGIC + nonce, "sha256")
    tmp = os.path.join(home, "v.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(MAGIC + nonce)
        w = EncWriter(f, key, nonce, mac)
        with tarfile.open(fileobj=w, mode="w|gz", compresslevel=1) as tf:
            for n in items:
                tf.add(os.path.join(src, n), arcname=n)
        w.finish()
        f.write(mac.digest())
    os.replace(tmp, dest)
    for name in all_names(key):
        p = os.path.join(home, name)
        if p != dest and os.path.isfile(p):
            os.remove(p)
    if src == home:
        for n in items:
            _remove(os.path.join(src, n))
    else:
        shutil.rmtree(src, ignore_errors=True)

def unpack(src, dest, key, is_home):
    with open(src, "rb") as f:
        size = os.path.getsize(src)
        head = f.read(HEAD)
        if size < HEAD + 32 or head[:4] != MAGIC:
            raise RuntimeError("cofre invalido")
        nonce = head[4:]
        mac = hmac.new(key, head, "sha256")
        left = size - HEAD - 32
        while left > 0:
            b = f.read(min(CHUNK, left))
            left -= len(b)
            mac.update(b)
        if not hmac.compare_digest(mac.digest(), f.read(32)):
            raise RuntimeError("chave errada ou cofre corrompido")
        f.seek(HEAD)
        reader = DecReader(f, key, nonce, size - HEAD - 32)
        os.makedirs(dest, mode=0o700, exist_ok=True)
        kw = {"filter": "tar"} if hasattr(tarfile, "tar_filter") else {}
        try:
            with tarfile.open(fileobj=reader, mode="r|gz") as tf:
                tf.extractall(dest, **kw)
        except Exception:
            if is_home:
                keep = keep_set(key)
                for n in os.listdir(dest):
                    if n not in keep:
                        _remove(os.path.join(dest, n))
            else:
                shutil.rmtree(dest, ignore_errors=True)
            raise

def _running(work, me):
    marks = [work + "/browser/", work + "/profile-vpn/", work + "/profile-novpn/"]
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == me:
            continue
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as f:
                cmd = f.read().decode(errors="ignore")
        except OSError:
            continue
        if any(m in cmd for m in marks):
            return True
        if work in cmd and any(x in cmd for x in ("_setup", "_server", "_browser")):
            return True
    return False

def open_vault(home):
    with _Mutex(home):
        key = get_key()
        work = work_dir(home)
        if not os.path.isdir(work):
            _, _, src = find_vault(home, key)
            if not src and loose_items(home, key):
                pack(home, home)
                _, _, src = find_vault(home, key)
            if not src:
                return ""
            unpack(src, work, key, False)
        return work

def unlock(home):
    with _Mutex(home):
        key = get_key()
        _, _, src = find_vault(home, key)
        if not src:
            return
        unpack(src, home, key, True)
        os.remove(src)

def seal(home):
    with _Mutex(home):
        pack(home, home)

def lock(home):
    with _Mutex(home):
        work = work_dir(home)
        if not os.path.isdir(work) or _running(work, os.getpid()):
            return
        pack(work, home)
        shutil.rmtree(work, ignore_errors=True)

def guard(home):
    work = work_dir(home)
    me = os.getpid()
    for _ in range(150):
        if _running(work, me):
            break
        time.sleep(0.2)
    else:
        return
    while True:
        while _running(work, me):
            time.sleep(2)
        time.sleep(3)
        if not _running(work, me):
            break
    lock(home)

def status(home):
    key = get_key()
    m, st, p = find_vault(home, key)
    inst = set(st)
    work = work_dir(home)
    if os.path.isdir(work):
        inst |= set(installed_in(work))
        m = m or read_mode(work)
    if not p:
        inst |= set(installed_in(home))
        m = m or (read_mode(home) if inst else None)
    if not inst:
        return ""
    return "%s:%s" % (m or "vpn", ",".join(x for x in MODES if x in inst))

def workdir(home):
    return work_dir(home)

# ── estado do instalador ───────────────────────────────────────────────────────

state = {"stage": "starting", "overall": 0, "percent": 0, "done": 0,
         "total": 0, "speed": 0, "eta": None, "msg": "Preparando...", "installed": []}

PAGE = r"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>Lynx Browser - Instalando</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--black:#050506;--panel:#0b0c0f;--hi:#121319;--line:rgba(255,255,255,.09);
--blue:#1d4fea;--bright:#3f6dff;--ice:#eef1f8;--slate:#838a9a;--dim:#484e5c}
html,body{height:100%}
body{background:radial-gradient(ellipse 60% 50% at 50% 0%,rgba(29,79,234,.25),transparent 60%),var(--black);
color:var(--ice);font-family:Inter,Arial,sans-serif;display:flex;align-items:center;justify-content:center}
.card{width:min(560px,94vw);background:linear-gradient(160deg,var(--hi),var(--panel) 70%);
border:1px solid var(--line);padding:34px 30px;
clip-path:polygon(24px 0,100% 0,100% calc(100% - 24px),calc(100% - 24px) 100%,0 100%,0 24px)}
.head{display:flex;align-items:center;gap:14px;margin-bottom:24px}
.head img{width:52px;height:52px;object-fit:contain;filter:drop-shadow(0 0 14px rgba(29,79,234,.6))}
h1{font-size:22px;letter-spacing:-.5px}h1 b{color:var(--bright)}
.sub{color:var(--slate);font-size:13px;margin-top:3px}
.bar{height:10px;background:#15171e;border:1px solid var(--line);overflow:hidden}
.fill{height:100%;width:0;background:linear-gradient(90deg,#081b66,var(--blue),var(--bright));
transition:width .35s ease;box-shadow:0 0 14px rgba(63,109,255,.6)}
.pct{display:flex;justify-content:space-between;margin:12px 0 22px;font-family:monospace;font-size:12px;color:var(--slate)}
.pct b{font-size:30px;color:var(--ice);font-family:Arial,sans-serif;letter-spacing:-1px}
.steps{list-style:none;display:grid;gap:10px;margin-bottom:22px}
.steps li{display:flex;align-items:center;gap:10px;font-size:13px;color:var(--dim)}
.steps li i{width:8px;height:8px;border-radius:50%;background:var(--dim)}
.steps li.on{color:var(--ice)}.steps li.on i{background:var(--bright);box-shadow:0 0 8px var(--bright);animation:b 1.4s infinite}
.steps li.ok{color:var(--slate)}.steps li.ok i{background:#3ddc84}
@keyframes b{50%{opacity:.3}}
.info{font-family:monospace;font-size:11px;color:var(--slate);border-top:1px solid var(--line);padding-top:14px;min-height:30px}
.err{color:#ff7b7b}
#choose{display:none}
.opts{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.opt{text-align:left;cursor:pointer;background:var(--panel);border:1px solid var(--line);color:var(--ice);
padding:16px 14px;font-family:inherit;transition:border-color .2s,transform .2s,background .2s;
clip-path:polygon(0 0,100% 0,100% calc(100% - 14px),calc(100% - 14px) 100%,0 100%)}
.opt:hover,.opt:focus-visible{border-color:rgba(63,109,255,.6);background:var(--hi);transform:translateY(-2px);outline:none}
.opt h2{font-size:15px;margin-bottom:10px;letter-spacing:.3px}.opt h2 b{color:var(--bright)}
.opt ul{list-style:none;display:grid;gap:7px}
.opt li{font-size:12px;color:var(--slate);line-height:1.35;padding-left:12px;position:relative}
.opt li:before{content:"";position:absolute;left:0;top:6px;width:5px;height:5px;background:var(--bright)}
.tag{display:inline-block;font-family:monospace;font-size:10px;letter-spacing:.8px;padding:3px 7px;margin-bottom:10px;border:1px solid var(--line);color:var(--slate)}
.tag.on{color:#3ddc84;border-color:rgba(61,220,132,.5)}
@media(max-width:480px){.opts{grid-template-columns:1fr}}
</style></head><body>
<div class="card">
<div class="head"><img src="/bolso.png" alt=""><div><h1 id="title">Instalando o <b>Lynx</b></h1><div class="sub" id="msg">Preparando...</div></div></div>

<div id="choose">
<div class="opts">
<button class="opt" id="o-vpn" onclick="escolher('vpn')">
<h2>COM <b>VPN</b></h2>
<div class="tag" id="t-vpn"></div>
<ul>
<li>Trick Track Baraboom</li>
<li>Demorado para carregar as coisas</li>
<li>Abre qualquer site</li>
</ul>
</button>
<button class="opt" id="o-novpn" onclick="escolher('novpn')">
<h2>SEM <b>VPN</b></h2>
<div class="tag" id="t-novpn"></div>
<ul>
<li>Roda jogos mais rapido (Cloudflare)</li>
<li>Nao consegue abrir todos os sites</li>
<li>Melhor escolha para aulas de laboratorio</li>
</ul>
</button>
</div>
</div>

<div id="prog">
<div class="bar"><div class="fill" id="fill"></div></div>
<div class="pct"><b id="pct">0%</b><span id="eta"></span></div>
<ul class="steps" id="steps">
<li data-s="download"><i></i>Baixando o motor do navegador</li>
<li data-s="extract"><i></i>Extraindo arquivos</li>
<li data-s="config"><i></i>Aplicando configurações</li>
<li data-s="launch"><i></i>Abrindo o Lynx</li>
</ul>
<div class="info" id="info"></div>
</div>
</div>
<script>
var order=["download","extract","config","launch"];
function mb(n){return (n/1048576).toFixed(1)+" MB"}
function tm(s){if(s==null)return"";s=Math.round(s);return s>=60?Math.floor(s/60)+"min "+(s%60)+"s":s+"s"}
function escolher(m){
 document.getElementById("o-vpn").disabled=true;document.getElementById("o-novpn").disabled=true;
 fetch("/choose?mode="+m,{method:"POST"});
}
function tick(){
 fetch("/progress",{cache:"no-store"}).then(function(r){return r.json()}).then(function(s){
  var ch=(s.stage=="choose");
  var inst=s.installed||[];
  ["vpn","novpn"].forEach(function(m){var t=document.getElementById("t-"+m);var on=inst.indexOf(m)>=0;t.textContent=on?"JÁ INSTALADO":"NÃO INSTALADO";t.className="tag"+(on?" on":"");});
  document.getElementById("choose").style.display=ch?"block":"none";
  document.getElementById("prog").style.display=ch?"none":"block";
  document.getElementById("title").innerHTML=ch?"Como você quer o <b>Lynx</b>?":"Instalando o <b>Lynx</b>";
  document.getElementById("msg").textContent=ch?"Escolha antes de instalar":s.msg;
  document.getElementById("fill").style.width=s.overall+"%";
  document.getElementById("pct").textContent=Math.floor(s.overall)+"%";
  document.getElementById("eta").textContent=(s.stage=="download"&&s.eta!=null)?"faltam ~"+tm(s.eta):"";
  var idx=order.indexOf(s.stage);if(s.stage=="done")idx=99;
  document.querySelectorAll("#steps li").forEach(function(li){
   var i=order.indexOf(li.dataset.s);
   li.className=i<idx?"ok":(i==idx?"on":"");
  });
  if(s.stage=="done"&&!window._c){window._c=1;setTimeout(function(){window.close()},1200);}
  var info=document.getElementById("info");
  if(s.stage=="error"){info.className="info err";info.textContent=s.msg;}
  else if(s.stage=="download"&&s.total){info.textContent=mb(s.done)+" / "+mb(s.total)+"  ·  "+mb(s.speed)+"/s";}
  else{info.textContent="";}
 }).catch(function(){});
}
setInterval(tick,400);tick();
</script></body></html>"""

choice = {"mode": None}
choice_evt = threading.Event()

class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=web, **k)

        def log_message(self, *a):
            pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _send_json(self, data, code=200):
            body = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_home(self):
            src = os.path.join(web, "index.html")
            try:
                with open(src, encoding="utf-8") as f:
                    html = f.read()
            except OSError:
                return super().do_GET()
            em = _read_email()
            th = _fetch_theme(em)
            html = _inject_theme(html, th)
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                return self._serve_home()
            
            if self.path == "/painel":
                try:
                    with open(os.path.join(web, "painel.html"), encoding="utf-8") as f:
                        body = f.read().encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except OSError:
                    self.send_error(404)
                return

            if self.path.startswith("/email"):
                em = _read_email()
                th = _fetch_theme(em)
                return self._send_json({"email": em, "theme": th})

            if self.path.startswith("/api/mods"):
                em = _read_email()
                if not em: return self._send_json({"ok": False, "error": "no_email"})
                try:
                    r = requests.post("https://lynx-gate.mamaetata216.workers.dev/", json={"action": "getMods", "email": em})
                    return self._send_json(r.json())
                except Exception as e:
                    return self._send_json({"ok": False, "error": str(e)})

            return super().do_GET()

        def do_POST(self):
            if self.path == "/save-email":
                try:
                    length = int(self.headers.get("Content-Length", "0") or "0")
                    raw = self.rfile.read(length).decode("utf-8")
                    data = json.loads(raw)
                    em = str(data.get("email", "")).strip().lower()
                    if "@" in em:
                        write_text(os.path.join(base, ".email"), em + "\n")
                        _theme_cache.pop(em, None)
                        return self._send_json({"ok": True, "email": em})
                    else:
                        return self._send_json({"ok": False})
                except Exception as e:
                    return self._send_json({"ok": False, "error": str(e)})
            
            if self.path == "/api/save_mods":
                try:
                    em = _read_email()
                    if not em: return self._send_json({"ok": False, "error": "no_email"})
                    length = int(self.headers.get("Content-Length", "0") or "0")
                    mods_data = json.loads(self.rfile.read(length).decode("utf-8"))
                    r = requests.post("https://lynx-gate.mamaetata216.workers.dev/", json={"action": "saveMods", "email": em, "mods": mods_data})
                    return self._send_json(r.json())
                except Exception as e:
                    return self._send_json({"ok": False, "error": str(e)})

            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

def setup_log(message):
    path = os.path.join(tempfile.gettempdir(), "lynx-setup-%s.log" % os.getuid())
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + str(message) + "\n")
    except OSError:
        pass

def _launch_panel_command(command, name, marker=None, cleanup=None):
    quiet = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        proc = subprocess.Popen(command, **quiet)
        time.sleep(0.35)
        rc = proc.poll()
        if rc is not None and rc != 0:
            setup_log("%s encerrou com código %s" % (name, rc))
            if cleanup:
                shutil.rmtree(cleanup, ignore_errors=True)
            return False, None
        setup_log("Painel solicitado por %s: %s" % (name, command[-1]))
        return True, marker
    except Exception as e:
        setup_log("Falha ao iniciar %s: %s" % (name, e))
        if cleanup:
            shutil.rmtree(cleanup, ignore_errors=True)
        return False, None

def _write_panel_firefox_prefs(profile):
    os.makedirs(profile, exist_ok=True)
    with open(os.path.join(profile, "user.js"), "w", encoding="utf-8") as f:
        f.write(
            'user_pref("browser.shell.checkDefaultBrowser", false);\n'
            'user_pref("browser.startup.homepage_welcome_url", "");\n'
            'user_pref("datareporting.policy.dataSubmissionEnabled", false);\n'
            'user_pref("browser.aboutwelcome.enabled", false);\n'
            'user_pref("ui.systemUsesDarkTheme", 1);\n'
            'user_pref("browser.theme.content-theme", 0);\n'
            'user_pref("browser.theme.toolbar-theme", 0);\n'
        )

def open_window(url):
    chromium_names = (
        "google-chrome", "google-chrome-stable", "chromium",
        "chromium-browser", "brave-browser", "brave",
        "microsoft-edge", "microsoft-edge-stable", "vivaldi-stable",
        "opera", "epiphany"
    )
    for name in chromium_names:
        path = shutil.which(name)
        if not path:
            continue
        prof = os.path.join(tempfile.gettempdir(), "lynx-setup-%d" % os.getpid())
        ok, marker = _launch_panel_command(
            [path, "--app=" + url, "--window-size=620,560",
             "--user-data-dir=" + prof, "--no-first-run",
             "--no-default-browser-check"], name, prof, prof)
        if ok:
            return marker

    for name in ("firefox", "firefox-esr"):
        path = shutil.which(name)
        if not path:
            continue
        prof = os.path.join(os.path.expanduser("~"), "lynx-setup-%d" % os.getpid())
        try:
            _write_panel_firefox_prefs(prof)
        except Exception as e:
            setup_log("Falha ao preparar perfil de %s: %s" % (name, e))
            shutil.rmtree(prof, ignore_errors=True)
            continue
        ok, marker = _launch_panel_command(
            [path, "--no-remote", "--profile", prof, "--new-window", url],
            name, prof, prof)
        if ok:
            return marker

    for opener, prefix in (("xdg-open", []), ("gio", ["open"]),
                           ("sensible-browser", [])):
        path = shutil.which(opener)
        if not path:
            continue
        ok, marker = _launch_panel_command([path] + prefix + [url], opener)
        if ok:
            return marker

    browser_env = os.environ.get("BROWSER", "").strip()
    if browser_env:
        try:
            command = shlex.split(browser_env)
            if command:
                replaced = False
                for i, arg in enumerate(command):
                    if "%s" in arg:
                        command[i] = arg.replace("%s", url)
                        replaced = True
                if not replaced:
                    command.append(url)
                ok, marker = _launch_panel_command(command, "BROWSER")
                if ok:
                    return marker
        except Exception as e:
            setup_log("Falha ao interpretar BROWSER=%s: %s" % (browser_env, e))

    try:
        if webbrowser.open(url, new=1, autoraise=True):
            setup_log("Painel solicitado por webbrowser: %s" % url)
            return None
    except Exception as e:
        setup_log("Falha no webbrowser: %s" % e)

    flatpak = shutil.which("flatpak")
    if flatpak:
        for app, name in (("org.mozilla.firefox", "Firefox Flatpak"),
                          ("org.chromium.Chromium", "Chromium Flatpak")):
            ok, marker = _launch_panel_command([flatpak, "run", app, url], name)
            if ok:
                return marker

    bundled = os.path.join(BASE, "browser", "firefox", "firefox")
    if os.path.isfile(bundled) and os.access(bundled, os.X_OK):
        prof = os.path.join(os.path.expanduser("~"), "lynx-setup-%d" % os.getpid())
        try:
            _write_panel_firefox_prefs(prof)
        except Exception as e:
            setup_log("Falha ao preparar perfil do Firefox incluído: %s" % e)
            shutil.rmtree(prof, ignore_errors=True)
        else:
            ok, marker = _launch_panel_command(
                [bundled, "--no-remote", "--profile", prof, "--new-window", url],
                "Firefox incluído no Lynx", prof, prof)
            if ok:
                return marker

    msg = "Não foi possível abrir o painel: nenhum navegador gráfico conseguiu iniciar."
    setup_log(msg + " URL=" + url)
    raise RuntimeError(msg)

def close_window(marker):
    if not marker:
        return
    me = os.getpid()
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == me:
            continue
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as f:
                cmd = f.read().decode(errors="ignore")
        except OSError:
            continue
        if marker in cmd:
            try:
                os.kill(int(pid), 15)
            except OSError:
                pass
    time.sleep(1.5)
    shutil.rmtree(marker, ignore_errors=True)

def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 LynxSetup"})
    with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        state.update(stage="download", total=total, msg="Baixando o Firefox...")
        done, t0, last = 0, time.time(), 0
        while True:
            chunk = r.read(262144)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            now = time.time()
            if now - last > 0.25:
                speed = done / max(now - t0, 0.001)
                pct = (done / total * 100) if total else 0
                state.update(done=done, speed=speed, percent=pct,
                             overall=pct * 0.70,
                             eta=((total - done) / speed) if total and speed else None)
                last = now
    state.update(done=done, percent=100, overall=70)

def extract(tar_path, tmp):
    size = os.path.getsize(tar_path)
    state.update(stage="extract", msg="Extraindo arquivos...", eta=None)
    kw = {"filter": "tar"} if hasattr(tarfile, "tar_filter") else {}
    with open(tar_path, "rb") as raw:
        with tarfile.open(fileobj=raw, mode="r|xz") as tf:
            for m in tf:
                tf.extract(m, tmp, **kw)
                state["overall"] = 70 + 25 * (raw.tell() / size)

def prepare_firefox_bundle():
    firefox_path = os.path.join(BASE, "browser", "firefox", "firefox")
    if os.path.isfile(firefox_path) and os.access(firefox_path, os.X_OK):
        return firefox_path

    cfg_url = os.path.join(CFG, "firefox-url.txt")
    try:
        with open(cfg_url, encoding="utf-8") as f:
            url = f.read().strip()
    except OSError:
        url = FIREFOX_URL
    if not url:
        url = FIREFOX_URL

    tar_path = os.path.join(BASE, "firefox.tar.xz")
    tmp = os.path.join(BASE, "_extract")
    os.makedirs(BASE, exist_ok=True)
    try:
        download(url, tar_path)
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp, exist_ok=True)
        extract(tar_path, tmp)
        extracted = os.path.join(tmp, "firefox")
        if not os.path.isfile(os.path.join(extracted, "firefox")):
            raise RuntimeError("O pacote baixado não contém o executável Firefox esperado.")

        dest = os.path.join(BASE, "browser", "firefox")
        shutil.rmtree(dest, ignore_errors=True)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        os.rename(extracted, dest)
        firefox_path = os.path.join(dest, "firefox")
        if not os.path.isfile(firefox_path):
            raise RuntimeError("O Firefox não foi encontrado após a extração.")
        if not os.access(firefox_path, os.X_OK):
            os.chmod(firefox_path, os.stat(firefox_path).st_mode | 0o111)
        if not os.access(firefox_path, os.X_OK):
            raise RuntimeError("O executável do Firefox não pôde receber permissão de execução.")
        return firefox_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            os.remove(tar_path)
        except OSError:
            pass

def run_setup():
    os.makedirs(BASE, exist_ok=True)
    lock = open(os.path.join(BASE, ".setup.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        setup_log("O bloqueio do instalador já está ocupado; procurando painel em execução.")
        url_file = os.path.join(BASE, ".setup-url")
        try:
            existing_url = Path(url_file).read_text(encoding="utf-8").strip()
            with urllib.request.urlopen(existing_url + "progress", timeout=1) as response:
                if response.status == 200:
                    open_window(existing_url)
                    open(os.path.join(BASE, ".started"), "w").close()
                    return
        except Exception as e:
            setup_log("Não foi possível reutilizar o painel ativo: %s" % e)
        notify("Lynx Browser", "O instalador já está em execução. Aguarde ou encerre a instância anterior e tente novamente.")
        return

    srv = None
    win = None
    tar_path = os.path.join(BASE, "firefox.tar.xz")
    tmp = os.path.join(BASE, "_extract")
    try:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        panel_url = "http://127.0.0.1:%d/" % srv.server_address[1]
        write_text(os.path.join(BASE, ".setup-url"), panel_url + "\n")
        try:
            win = open_window(panel_url)
        except RuntimeError as first_open_error:
            setup_log("Nenhum navegador do sistema abriu o painel; preparando Firefox incluído: %s" % first_open_error)
            prepare_firefox_bundle()
            win = open_window(panel_url)
        open(os.path.join(BASE, ".started"), "w").close()

        mode_file = os.path.join(BASE, ".mode")
        state["installed"] = [m for m in ("vpn", "novpn")
                              if os.path.isdir(os.path.join(BASE, "profile-" + m))]
        forced = SETUP_ARGS[0] if SETUP_ARGS and SETUP_ARGS[0] in ("vpn", "novpn") else None
        if forced:
            choice["mode"] = forced
        else:
            state.update(stage="choose", msg="Como você quer o Lynx?")
            if not choice_evt.wait(timeout=900) or choice["mode"] not in ("vpn", "novpn"):
                raise RuntimeError("Nenhuma opção foi escolhida.")
        with open(mode_file, "w", encoding="utf-8") as f:
            f.write(choice["mode"])
        state.update(stage="starting", msg="Preparando...")

        firefox_path = os.path.join(BASE, "browser", "firefox", "firefox")
        if not os.path.isfile(firefox_path) or not os.access(firefox_path, os.X_OK):
            prepare_firefox_bundle()
        state.update(stage="config", overall=max(state.get("overall", 0), 96),
                     msg="Aplicando configurações...")

        state.update(stage="launch", overall=99, msg="Abrindo o Lynx...")
        chosen_mode = choice["mode"]
        detached([sys.executable, SCRIPT_PATH, "_browser", BASE, chosen_mode])
        time.sleep(3)
        state.update(stage="done", overall=100, msg="Pronto! Abrindo o Lynx...")
        time.sleep(2)
        close_window(win)
    except Exception as e:
        setup_log("Erro no instalador: %s" % e)
        state.update(stage="error", msg="Erro: %s" % e)
        notify("Lynx Browser", "Falha no instalador: %s" % e)
        if srv is not None:
            time.sleep(90)
    finally:
        if srv is not None:
            try:
                srv.shutdown()
                srv.server_close()
            except Exception:
                pass
        shutil.rmtree(tmp, ignore_errors=True)
        os._exit(0)

def set_runtime_base(base):
    global BASE, CFG
    BASE = os.path.abspath(base)
    CFG = os.path.join(BASE, "config")

def detached(args, *, env=None, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL):
    return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=stdout,
                            stderr=stderr, start_new_session=True, env=env)

def notify(title, msg):
    notify_bin = shutil.which("notify-send")
    if notify_bin:
        subprocess.run([notify_bin, title, msg], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)

def install_assets(root, install):
    logo  = os.path.join(root, "lynx-logo.png")
    bolso = os.path.join(root, "bolso.png")
    # FIX 6: condição correta — baixa se o arquivo não existir OU estiver vazio
    if not (os.path.isfile(logo) and os.path.getsize(logo) > 0):
        urllib.request.urlretrieve("https://raw.githubusercontent.com/Pax0102/img/main/1.png", logo)
    if not (os.path.isfile(logo) and os.path.getsize(logo) > 0):
        raise RuntimeError("ERRO: logo inválida.")
    if not (os.path.isfile(bolso) and os.path.getsize(bolso) > 0):
        urllib.request.urlretrieve("https://raw.githubusercontent.com/Pax0102/img/main/2.png", bolso)
    if not (os.path.isfile(bolso) and os.path.getsize(bolso) > 0):
        raise RuntimeError("ERRO: imagem bolso inválida.")
    icons = os.path.join(install, "config", "icons")
    os.makedirs(icons, exist_ok=True)
    shutil.copy2(logo,  os.path.join(icons, "lynx-logo.png"))
    shutil.copy2(bolso, os.path.join(icons, "bolso.png"))
    return logo, bolso

def install_config(install, logo):
    cfg = os.path.join(install, "config")
    os.makedirs(os.path.join(cfg, "web-novpn"), exist_ok=True)
    os.makedirs(os.path.join(cfg, "web-vpn"),   exist_ok=True)
    write_home_pages(cfg, logo)
    write_text(os.path.join(cfg, "firefox-url.txt"),       FIREFOX_URL + "\n")
    write_text(os.path.join(cfg, "lynx.conf"),             "DNS_FILTER=0\n")
    write_text(os.path.join(cfg, "blocked-sites.txt"),     "")
    write_text(os.path.join(cfg, "blocklist-default.txt"), BLOCKLIST_DEFAULT)
    write_text(os.path.join(cfg, "vpn.conf"),
               "ENABLED=0\nHOST=127.0.0.1\nPORT=1080\nUSERNAME=\nPASSWORD=\n")

def launch_lynx(install, mode_flag=""):
    work = work_dir(install)
    try:
        os.remove(os.path.join(work, ".started"))
    except OSError:
        pass
    cmd = [sys.executable, os.path.join(install, "lynx.py"), "_start", install]
    if mode_flag:
        cmd.append(mode_flag)
    detached(cmd)
    ok = False
    for _ in range(2400):
        if os.path.isfile(os.path.join(work, ".started")):
            ok = True
            break
        time.sleep(0.25)
    if ok:
        time.sleep(1)
        if sys.stdout.isatty() and os.environ.get("LYNX_KEEP_TERMINAL", "0") != "1":
            try:
                os.kill(os.getppid(), signal.SIGHUP)
            except OSError:
                pass
    else:
        print("Aviso: o Lynx não confirmou a abertura em 600s. Terminal mantido aberto.")
        print("Tente de novo ou rode: %s _start %s" % (os.path.join(install, "lynx.py"), install))

def build(argv):
    root = os.getcwd()
    install = os.environ.get("LYNX_INSTALL_DIR") or DEFAULT_INSTALL
    rebuild = False
    mode_flag = ""
    for arg in argv:
        if arg == "--rebuild":
            rebuild = True
        elif arg == "--com-vpn":
            mode_flag = "vpn"
        elif arg == "--sem-vpn":
            mode_flag = "novpn"
    build_id = hashlib.sha256(Path(sys.argv[0]).read_bytes()).hexdigest()[:12]
    installed_script = os.path.join(install, "lynx.py")
    if not rebuild and not mode_flag and os.path.isfile(installed_script) and os.access(installed_script, os.X_OK):
        try:
            old_id = hashlib.sha256(Path(installed_script).read_bytes()).hexdigest()[:12]
        except OSError:
            old_id = ""
        if old_id == build_id:
            launch_lynx(install)
            return 0
        rebuild = True

    logo  = os.path.join(root, "lynx-logo.png")
    bolso = os.path.join(root, "bolso.png")
    for cmd in ("sed", "grep"):
        if shutil.which(cmd) is None:
            print("ERRO: comando necessário não encontrado: %s" % cmd)
            return 1

    old_lockutil = os.path.join(install, "lockutil.py")
    if os.path.isfile(old_lockutil):
        try:
            res = subprocess.run([sys.executable, old_lockutil, "workdir", install],
                                 check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            work_now = res.stdout.strip()
        except Exception:
            work_now = work_dir(install)
        if os.path.isdir(work_now):
            print("ERRO: feche o Lynx e espere alguns segundos antes de reconstruir.")
            return 1
        try:
            subprocess.run([sys.executable, old_lockutil, "unlock", install], check=True)
        except Exception:
            print("ERRO: não consegui abrir o cofre.")
            return 1
    elif os.path.isfile(installed_script):
        work_now = work_dir(install)
        if os.path.isdir(work_now):
            print("ERRO: feche o Lynx e espere alguns segundos antes de reconstruir.")
            return 1
        try:
            unlock(install)
        except Exception:
            print("ERRO: não consegui abrir o cofre.")
            return 1

    print("[1/6] Preparando voto ao bolsonaro 22")
    os.makedirs(install, exist_ok=True)
    preserved = {"browser", ".mode", ".icons-done", "profile-vpn", "profile-novpn", "lynx.py", "m"}
    for name in os.listdir(install):
        if name not in preserved:
            _remove(os.path.join(install, name))
    os.makedirs(os.path.join(install, "browser"), exist_ok=True)
    os.makedirs(os.path.join(install, "config", "icons"), exist_ok=True)
    os.chmod(install, 0o700)
    if mode_flag:
        write_text(os.path.join(install, ".mode"), mode_flag + "\n")

    print("[2/6] O voto esta sendo processado...")
    try:
        logo, bolso = install_assets(root, install)
    except Exception as e:
        print(str(e))
        return 1

    print("[3/6] Voto confirmado!")
    install_config(install, logo)
    print("[4/6] Ez Lula perdeu")
    print("[5/6] Scripts...")
    source = os.path.abspath(sys.argv[0])
    target_dir = os.path.dirname(installed_script)
    os.makedirs(target_dir, exist_ok=True)
    shutil.copy2(source, installed_script)
    os.chmod(installed_script, 0o700)
    print("[6/6] Finalizando...")

    desktop_cmd = shutil.which("xdg-user-dir")
    desk_dir = os.path.join(os.path.expanduser("~"), "Desktop")
    if desktop_cmd:
        try:
            p = subprocess.run([desktop_cmd, "DESKTOP"], text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, check=False)
            if p.stdout.strip():
                desk_dir = p.stdout.strip()
        except OSError:
            pass
    to_remove = [
        os.path.join(os.path.expanduser("~"), ".local/share/applications/lynx-browser.desktop"),
        os.path.join(desk_dir, "Lynx Browser.desktop"),
        os.path.join(os.path.expanduser("~"), ".local/bin/lynx-browser"),
        os.path.join(os.path.expanduser("~"), ".local/share/icons/hicolor/256x256/apps/lynx-browser.png")]
    for p in to_remove:
        try: os.remove(p)
        except OSError: pass
    udb = shutil.which("update-desktop-database")
    apps_dir = os.path.join(os.path.expanduser("~"), ".local/share/applications")
    if udb:
        subprocess.run([udb, apps_dir], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    for p in (logo, bolso):
        try: os.remove(p)
        except OSError: pass
    try:
        seal(install)
    except Exception as e:
        print("ERRO ao fechar o cofre: %s" % e)
        return 1
    print("Pronto. Abrindo o Lynx...")
    launch_lynx(install, mode_flag)
    return 0

def parse_mode(args, existing=""):
    mode = ""
    setup_1vpn = False
    for a in args:
        if a in ("vpn", "novpn"):
            mode = a
        elif a == "--setup-1vpn":
            setup_1vpn = True
    if not mode and existing:
        mode = existing.strip()
    if mode != "novpn":
        mode = "vpn"
    return mode, setup_1vpn

def pattern_for_site(value):
    s = value.split("#", 1)[0]
    s = s.replace('"', "").replace("\\", "").replace("\r", "").strip()
    if not s:
        return ""
    if s.startswith("http://"):
        s = s[7:]
    if s.startswith("https://"):
        s = s[8:]
    if s.startswith("www."):
        s = s[4:]
    if "/" in s and s.split("/", 1)[1]:
        return "*://*.%s*" % s
    s = s[:-1] if s.endswith("/") else s
    return "*://*.%s/*" % s

def run_browser(base, args):
    set_runtime_base(base)
    firefox = os.path.join(BASE, "browser", "firefox", "firefox")
    conf    = os.path.join(BASE, "config", "lynx.conf")
    policy_dir = os.path.join(BASE, "browser", "firefox", "distribution")
    if not os.access(firefox, os.X_OK):
        print("ERRO: Firefox não encontrado.")
        return 1
    mode_path = os.path.join(BASE, ".mode")
    try:
        existing = Path(mode_path).read_text().strip()
    except OSError:
        existing = ""
    mode, setup_1vpn = parse_mode(args, existing)
    write_text(mode_path, mode + "\n")
    profile = os.path.join(BASE, "profile-" + mode)
    os.makedirs(os.path.join(profile, "chrome"), exist_ok=True)
    os.makedirs(policy_dir, exist_ok=True)
    class_args = []

    if mode == "vpn":
        dns_filter = read_config(conf).get("DNS_FILTER", "0")
        if setup_1vpn:
            cmd = 'chrome.storage.local.set({ currentLocation: "lax", isConnected: true });'
            print("Em about:debugging clique em Inspecionar na 1VPN e cole no Console:")
            print("  " + cmd)
            for clipper in ("wl-copy", "xclip"):
                path = shutil.which(clipper)
                if path:
                    if clipper == "wl-copy":
                        subprocess.run([path], input=cmd.encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                    else:
                        subprocess.run([path, "-selection", "clipboard"], input=cmd.encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                    break
            home = os.environ.get("LYNX_HOME")
            if home:
                detached([sys.executable, SCRIPT_PATH, "_guard", home])
            subprocess.run([firefox, "--no-remote", "--profile", profile,
                            "about:debugging#/runtime/this-firefox"], check=False)
            return 0

        prefs = [
            ('security.cert_pinning.enforcement_level', '2'),
            ('security.enterprise_roots.enabled', 'false'),
            ('privacy.trackingprotection.enabled', 'true'),
            ('privacy.trackingprotection.pbmode.enabled', 'true'),
            ('privacy.trackingprotection.socialtracking.enabled', 'true'),
            ('privacy.partition.network_state', 'false'),
            ('media.peerconnection.enabled', 'false'), ('dom.battery.enabled', 'false'),
            ('browser.send_pings', 'false'),
            ('toolkit.legacyUserProfileCustomizations.stylesheets', 'true'),
            ('extensions.activeThemeID', '"firefox-compact-dark@mozilla.org"'),
            ('browser.startup.firstrunSkipsHomepage', 'true'), ('browser.disableResetPrompt', 'true'),
            ('browser.shell.checkDefaultBrowser', 'false'), ('browser.warnOnQuit', 'false'),
            ('browser.sessionstore.resume_from_crash', 'false'),
            ('startup.homepage_welcome_url', '""'), ('startup.homepage_welcome_url.additional', '""'),
            ('startup.homepage_override_url', '""'), ('browser.startup.upgradeDialog.enabled', 'false'),
            ('xpinstall.signatures.required', 'false'),
            ('extensions.webextensions.ExtensionStorageIDB.enabled', 'false')]
        lines = ['user_pref("%s", %s);' % (k, v) for k, v in prefs]
        if dns_filter == "1":
            lines += ['user_pref("network.trr.mode", 3);',
                      'user_pref("network.trr.uri", "https://doh.cleanbrowsing.org/doh/adult-filter/");',
                      'user_pref("network.trr.bootstrapAddress", "185.228.168.10");']
        else:
            lines += ['user_pref("network.trr.mode", 5);', 'user_pref("network.trr.uri", "");',
                      'user_pref("network.trr.bootstrapAddress", "");']
        lines += ['user_pref("network.proxy.type", 0);',
                  'user_pref("network.proxy.no_proxies_on", "localhost, 127.0.0.1");']
        write_text(os.path.join(profile, "user.js"), "\n".join(lines) + "\n")
        seed_dir = os.path.join(profile, "browser-extension-data", "1vpn@example.com")
        seed = os.path.join(seed_dir, "storage.js")
        if not os.path.isfile(seed):
            os.makedirs(seed_dir, exist_ok=True)
            write_text(seed, '{"currentLocation":"lax","isConnected":true}')

        patterns = []
        for name in ("blocklist-default.txt", "blocked-sites.txt"):
            try:
                rows = Path(os.path.join(BASE, "config", name)).read_text(encoding="utf-8").splitlines()
            except OSError:
                rows = []
            for row in rows:
                p = pattern_for_site(row)
                if p:
                    patterns.append(p)
        patterns += ["*://*/*%s*" % kw for kw in ("porn", "hentai", "nsfw")]
        policy = {"policies": {
            "WebsiteFilter": {"Block": patterns}, "BlockAboutConfig": True,
            "BlockAboutProfiles": True, "BlockAboutSupport": True,
            "ExtensionSettings": {"1vpn@example.com": {
                "installation_mode": "force_installed",
                "install_url": "https://addons.mozilla.org/firefox/downloads/latest/1vpn/latest.xpi",
                "default_area": "navbar", "private_browsing": True}}}}
        write_text(os.path.join(policy_dir, "policies.json"),
                   json.dumps(policy, ensure_ascii=False, indent=4) + "\n")
        write_text(os.path.join(profile, "chrome", "userChrome.css"),
                   "#aboutHeaderLearnMore { display: none !important; }\n")
        class_args = ["--class", "LynxBrowser"]
    else:
        try:
            os.remove(os.path.join(policy_dir, "policies.json"))
        except OSError:
            pass
        prefs = [
            ('network.trr.mode', '2'),
            ('network.trr.uri', '"https://cloudflare-dns.com/dns-query"'),
            ('network.trr.bootstrapAddress', '"1.1.1.1"'),
            ('privacy.trackingprotection.enabled', 'true'),
            ('privacy.trackingprotection.pbmode.enabled', 'true'),
            ('privacy.trackingprotection.socialtracking.enabled', 'true'),
            ('privacy.partition.network_state', 'true'),
            ('media.peerconnection.enabled', 'false'), ('dom.battery.enabled', 'false'),
            ('browser.send_pings', 'false'),
            ('network.proxy.type', '0'),
            ('extensions.activeThemeID', '"firefox-compact-dark@mozilla.org"'),
            ('toolkit.legacyUserProfileCustomizations.stylesheets', 'true'),
            ('browser.startup.firstrunSkipsHomepage', 'true'),
            ('browser.disableResetPrompt', 'true'),
            ('datareporting.policy.dataSubmissionPolicyBypassNotification', 'true'),
            ('browser.shell.checkDefaultBrowser', 'false'), ('browser.warnOnQuit', 'false'),
            ('browser.sessionstore.resume_from_crash', 'false'),
            ('startup.homepage_welcome_url', '""'),
            ('startup.homepage_welcome_url.additional', '""'),
            ('startup.homepage_override_url', '""'),
            ('browser.startup.upgradeDialog.enabled', 'false')]
        write_text(os.path.join(profile, "user.js"),
                   "\n".join('user_pref("%s", %s);' % (k, v) for k, v in prefs) + "\n")
        css = '''#appMenu-protonMainView .panel-header h1,
#appMenu-protonMainView .panel-header description {
    visibility: collapse !important;
}
#titlebar {
    -moz-appearance: none !important;
}
#PanelUI-menu-button .toolbarbutton-icon {
    list-style-image: none !important;
}
#aboutHeaderLearnMore {
    display: none !important;
}
'''
        write_text(os.path.join(profile, "chrome", "userChrome.css"), css)
        marker = os.path.join(BASE, ".icons-done")
        if not os.path.isfile(marker):
            logo = os.path.join(BASE, "config", "icons", "lynx-logo.png")
            if os.path.isfile(logo):
                for dirpath, _, files in os.walk(os.path.join(BASE, "browser", "firefox")):
                    for name in files:
                        if name.lower().endswith(".png") and re.search(
                                r"icon|logo|mozicon",
                                os.path.relpath(os.path.join(dirpath, name),
                                                os.path.join(BASE, "browser", "firefox")), re.I):
                            try:
                                shutil.copy2(logo, os.path.join(dirpath, name))
                            except OSError:
                                pass
            Path(marker).touch()

    port = 47321
    home_url = "http://localhost:%d/" % port
    start_url = "about:blank"
    webdir = os.path.join(BASE, "config", "web-" + mode)
    detached([sys.executable, SCRIPT_PATH, "_server", BASE, str(port), webdir])
    for _ in range(30):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.15):
                start_url = home_url
                break
        except OSError:
            time.sleep(0.1)
    if start_url == home_url:
        with open(os.path.join(profile, "user.js"), "a", encoding="utf-8") as f:
            f.write('user_pref("browser.startup.homepage", "%s");\n' % home_url)
            f.write('user_pref("browser.startup.page", 1);\n')

    ff_dir = os.path.join(BASE, "browser", "firefox")
    os.makedirs(os.path.join(ff_dir, "defaults", "pref"), exist_ok=True)
    write_text(os.path.join(ff_dir, "defaults", "pref", "autoconfig.js"),
               'pref("general.config.filename", "lynx.cfg");\n'
               'pref("general.config.obscure_value", 0);\n'
               'pref("general.config.sandbox_enabled", false);\n')
    cfg_js = '''//
try {
  var lynxUrl = "%s";
  Services.obs.addObserver({
    observe: function () {
      try {
        var svc = Components.classes["@mozilla.org/browser/aboutnewtab-service;1"]
          .getService(Components.interfaces.nsIAboutNewTabService);
        svc.newTabURL = lynxUrl;
      } catch (e) {
        try {
          var m = ChromeUtils.importESModule("resource:///modules/AboutNewTab.sys.mjs");
          m.AboutNewTab.newTabURL = lynxUrl;
        } catch (e2) {}
      }
    }
  }, "final-ui-startup", false);
} catch (e) {}
''' % home_url
    write_text(os.path.join(ff_dir, "lynx.cfg"), cfg_js)
    detached([firefox, "--no-remote"] + class_args + ["--profile", profile, start_url])
    Path(os.path.join(BASE, ".started")).touch()
    home = os.environ.get("LYNX_HOME")
    if home:
        detached([sys.executable, SCRIPT_PATH, "_guard", home])
    return 0


def run_server(base, port=47321, web=None):
    mark = os.path.join(base, "profile-")
    web  = web or os.path.join(base, "config", "web-vpn")

    PALETTE = {
        "azul":     ("#3b82f6", "#60a5fa", "#1e3a8a"),
        "roxo":     ("#8b5cf6", "#a78bfa", "#4c1d95"),
        "verde":    ("#10b981", "#34d399", "#064e3b"),
        "vermelho": ("#ef4444", "#f87171", "#7f1d1d"),
    }
    RGB_MAP = {
        "azul":     "59,130,246",
        "roxo":     "139,92,246",
        "verde":    "16,185,129",
        "vermelho": "239,68,68",
    }

    # FIX 4: cache por email com TTL de 60 s; retorna valor stale se o worker
    # falhar em vez de degradar silenciosamente para "azul"
    _theme_cache = {}   # {email: (theme, timestamp)}
    _THEME_TTL   = 60   # segundos

    def _read_email():
        try:
            with open(os.path.join(base, ".email"), encoding="utf-8") as f:
                return f.read().strip().lower()
        except OSError:
            return ""

    def _fetch_theme(email):
        payload = {
            "action": "getPublicTheme",
            "email": email
        }

        headers = {
            "Content-Type": "application/json"
        }

        response = requests.post(
            "https://lynx-gate.mamaetata216.workers.dev/",
            json=payload,
            headers=headers
        )
        response_data = response.json()
        theme = response_data.get("theme")
        return theme

    def _inject_theme(html, theme):
        b, br, d = PALETTE.get(theme, PALETTE["azul"])
        rgb = RGB_MAP.get(theme, "59,130,246")
        
        html = html.replace("--accent:#3b82f6",       "--accent:"        + b)
        html = html.replace("--accent-2:#60a5fa",     "--accent-2:"      + br)
        html = html.replace("--accent-dim:#1e3a8a",   "--accent-dim:"    + d)
        html = html.replace("--glow-rgb:59,130,246",  "--glow-rgb:"      + rgb)
        
        return html

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=web, **k)

        def log_message(self, *a):
            pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _serve_home(self):
            src = os.path.join(web, "index.html")
            try:
                with open(src, encoding="utf-8") as f:
                    html = f.read()
            except OSError:
                return super().do_GET()
            em = _read_email()
            th = _fetch_theme(em)
            html = _inject_theme(html, th)
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                return self._serve_home()
            if self.path.startswith("/email"):
                # FIX 5: usa o mesmo cache — não faz round-trip duplicado
                em = _read_email()
                th = _fetch_theme(em)
                body = json.dumps({"email": em, "theme": th}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            return super().do_GET()

        def do_POST(self):
            if self.path == "/save-email":
                try:
                    length = int(self.headers.get("Content-Length", "0") or "0")
                    raw    = self.rfile.read(length).decode("utf-8")
                    data   = json.loads(raw)
                    em     = str(data.get("email", "")).strip().lower()
                    if "@" in em:
                        write_text(os.path.join(base, ".email"), em + "\n")
                        # Invalida cache para forçar fetch fresco na próxima requisição
                        _theme_cache.pop(em, None)
                        body = json.dumps({"ok": True, "email": em}).encode()
                    else:
                        body = json.dumps({"ok": False}).encode()
                except Exception as e:
                    setup_log("save-email falhou: %s" % e)
                    body = json.dumps({"ok": False}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def browser_running():
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open("/proc/%s/cmdline" % pid, "rb") as f:
                    cmd = f.read().decode(errors="ignore")
            except OSError:
                continue
            if mark in cmd:
                return True
        return False

    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", int(port)), Handler)
    except OSError:
        return 0
    threading.Thread(target=server.serve_forever, daemon=True).start()
    seen, gone = False, None
    while True:
        time.sleep(3)
        if browser_running():
            seen, gone = True, None
        else:
            gone = gone or time.time()
            if time.time() - gone > (15 if seen else 90):
                break
    os._exit(0)


def run_sites(base, args):
    set_runtime_base(base)
    list_path = os.path.join(BASE, "config", "blocked-sites.txt")
    try:
        mode = Path(os.path.join(BASE, ".mode")).read_text().strip()
    except OSError:
        mode = "vpn"
    if mode == "novpn":
        print("A lista de sites só vale no modo COM VPN (bash build-lynx.sh --com-vpn).")
        return 1
    action = args[0] if args else "list"
    site   = args[1] if len(args) > 1 else ""
    os.makedirs(os.path.dirname(list_path), exist_ok=True)
    try:
        rows = Path(list_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        rows = []
    if action == "add":
        if not site:
            print("Uso: ./sites add site.com"); return 1
        with open(list_path, "a", encoding="utf-8") as f:
            f.write(site + "\n")
        print("Adicionado: %s (reabra o Lynx)" % site)
    elif action == "remove":
        if not site:
            print("Uso: ./sites remove site.com"); return 1
        rows = [r for r in rows if r != site]
        write_text(list_path, "".join(r + "\n" for r in rows))
        print("Removido: %s (reabra o Lynx)" % site)
    elif action == "list":
        filtered = [r for r in rows if not re.match(r"^\s*(#|$)", r)]
        print("\n".join(filtered) if filtered else "(lista vazia)")
    elif action == "edit":
        editor = os.environ.get("EDITOR", "nano")
        return subprocess.run(editor.split() + [list_path]).returncode
    else:
        print("Uso: ./sites add|remove|list|edit [site]"); return 1
    return 0


def run_vpn(base, args):
    set_runtime_base(base)
    conf = os.path.join(BASE, "config", "vpn.conf")
    try:
        mode = Path(os.path.join(BASE, ".mode")).read_text().strip()
    except OSError:
        mode = "vpn"
    if mode != "novpn":
        print("Este controle só vale no modo SEM VPN (bash build-lynx.sh --sem-vpn).")
        return 1
    if not os.path.isfile(conf):
        print("Arquivo de configuração não encontrado."); return 1
    action = args[0] if args else "status"
    if action in ("on", "off"):
        value = "1" if action == "on" else "0"
        rows = Path(conf).read_text(encoding="utf-8").splitlines()
        for i, row in enumerate(rows):
            if row.startswith("ENABLED="):
                rows[i] = "ENABLED=" + value
        write_text(conf, "\n".join(rows) + "\n")
        print("VPN/Proxy: %s. Reinicie o navegador." % ("ATIVADO" if value == "1" else "DESATIVADO"))
    elif action == "status":
        c = read_config(conf)
        if c.get("ENABLED", "0") == "1":
            print("VPN/Proxy: ATIVADO - %s:%s" % (c.get("HOST", ""), c.get("PORT", "")))
        else:
            print("VPN/Proxy: DESATIVADO")
    elif action == "config":
        return subprocess.run(["nano", conf]).returncode
    else:
        print("Uso: ./vpn on | off | status | config")
    return 0


def run_test(base):
    set_runtime_base(base)
    profile = tempfile.mkdtemp(prefix="lynx-clean-profile-")
    write_text(os.path.join(profile, "user.js"),
               'user_pref("network.trr.mode", 5);\n'
               'user_pref("network.trr.uri", "");\n'
               'user_pref("network.proxy.type", 0);\n')
    result = subprocess.run([os.path.join(BASE, "browser", "firefox", "firefox"), "--no-remote",
                             "--profile", profile, "https://example.com"], check=True).returncode
    shutil.rmtree(profile, ignore_errors=True)
    return result


def run_start(home, args):
    os.environ["LYNX_HOME"] = home
    try:
        work = open_vault(home)
    except Exception:
        notify("Lynx Browser", "Falha ao abrir o cofre.")
        return 1
    if not work or not os.path.isdir(work):
        notify("Lynx Browser", "Cofre não encontrado. Rode o build-lynx.py de novo.")
        return 1
    if args and args[0] in ("sites", "vpn"):
        cmd, rest = args[0], args[1:]
        rc = run_sites(work, rest) if cmd == "sites" else run_vpn(work, rest)
        if rc != 0:
            return rc
        lock(home)
        return 0
    mode_arg = ""
    for a in args:
        if a in ("vpn", "novpn"):
            mode_arg = a
    if mode_arg and not os.path.isfile(os.path.join(work, ".mode")):
        write_text(os.path.join(work, ".mode"), mode_arg + "\n")
    firefox = os.path.join(work, "browser", "firefox", "firefox")
    if os.access(firefox, os.X_OK):
        if mode_arg:
            detached([sys.executable, SCRIPT_PATH, "_browser", work] + args, env=os.environ.copy())
            return 0
        if "--setup-1vpn" in args:
            detached([sys.executable, SCRIPT_PATH, "_browser", work] + args, env=os.environ.copy())
            return 0
    setup_args = [sys.executable, SCRIPT_PATH, "_setup", work]
    if mode_arg:
        setup_args.append(mode_arg)
    detached(setup_args, env=os.environ.copy())
    detached([sys.executable, SCRIPT_PATH, "_guard", home], env=os.environ.copy())
    return 0


def dispatch(argv):
    global SETUP_ARGS
    if not argv:
        return build([])
    command = argv[0]
    if command in ("--rebuild", "--com-vpn", "--sem-vpn"):
        return build(argv)
    if command == "_start":
        if len(argv) < 2: return 2
        return run_start(os.path.abspath(argv[1]), argv[2:])
    if command == "_browser":
        if len(argv) < 2: return 2
        return run_browser(argv[1], argv[2:])
    if command == "_setup":
        if len(argv) < 2: return 2
        set_runtime_base(argv[1]); SETUP_ARGS = argv[2:]
        run_setup()
        return 0
    if command == "_server":
        if len(argv) < 2: return 2
        base = os.path.abspath(argv[1])
        port = int(argv[2]) if len(argv) > 2 else 47321
        web  = argv[3] if len(argv) > 3 else os.path.join(base, "config", "web-vpn")
        return run_server(base, port, web)
    if command == "_guard":
        if len(argv) < 2: return 2
        guard(os.path.abspath(argv[1])); return 0
    return build(argv)

if __name__ == "__main__":
    try:
        sys.exit(dispatch(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print("ERRO: %s" % exc, file=sys.stderr)
        sys.exit(1)
