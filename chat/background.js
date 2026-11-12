const WORKER_URL = 'https://frostedge-gate.mamaetata216.workers.dev/';
const LOCAL_URL = 'http://localhost:47321';
const EXT_VERSION = '1.0';

// State
let ws = null, wsReconnect = null, jwt = null, banned = false, currentUser = null;

// Init
async function init() {
  const data = await browser.storage.local.get(['jwt', 'banned']);
  if (data.jwt) jwt = data.jwt;
  if (data.banned) banned = data.banned;
  
  if (banned) {
    lockBrowser();
    return;
  }
  
  if (!jwt) return; // wait for login
  
  // Check ban on startup
  const isBanned = await checkBan();
  if (isBanned) return;
  
  connectWS();
}

async function checkBan() {
  try {
    const r = await fetch(WORKER_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jwt, action: 'browser:checkBan' })
    });
    const d = await r.json();
    if (d.banned) {
      await setBanned(d.bannedBy);
      return true;
    }
    if (d.error === 'bad_jwt' || d.error === 'expired') {
      await browser.storage.local.remove(['jwt']);
      jwt = null;
    }
  } catch {}
  return false;
}

async function setBanned(by) {
  banned = true;
  await browser.storage.local.set({ banned: true, bannedBy: by || 'um administrador' });
  lockBrowser();
}

async function setUnbanned() {
  banned = false;
  await browser.storage.local.set({ banned: false, bannedBy: null });
  // Reconnect WS
  connectWS();
}

function lockBrowser() {
  // Redirect all tabs to banned page
  browser.tabs.query({}).then(tabs => {
    for (const tab of tabs) {
      browser.tabs.update(tab.id, { url: browser.runtime.getURL('banned.html') });
    }
  });
  // Listen for new tabs and redirect
  if (!browser._banTabListener) {
    browser._banTabListener = true;
    browser.tabs.onCreated.addListener(() => {
      setTimeout(() => {
        browser.tabs.query({}).then(tabs => {
          for (const t of tabs) {
            if (!t.url || t.url.startsWith('moz-extension')) return;
            browser.tabs.update(t.id, { url: browser.runtime.getURL('banned.html') });
          }
        });
      }, 100);
    });
  }
}

function connectWS() {
  if (!jwt) return;
  if (ws) try { ws.close(); } catch {}
  
  ws = new WebSocket(`wss://frostedge-gate.mamaetata216.workers.dev/ws?t=${encodeURIComponent(jwt)}`);
  
  ws.onopen = () => {
    sendLog('ws_connected');
    if (wsReconnect) { clearTimeout(wsReconnect); wsReconnect = null; }
  };
  
  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleWsMessage(msg);
    } catch {}
  };
  
  ws.onclose = () => {
    wsReconnect = setTimeout(connectWS, 5000);
  };
  
  ws.onerror = () => {
    sendLog('ws_error');
    try { ws.close(); } catch {}
  };
}

async function handleWsMessage(msg) {
  const myEmail = currentUser?.email;
  const target = (msg.target || '').toLowerCase().trim();
  const isMe = target === 'all' || target === myEmail;
  if (!isMe) return;
  
  switch (msg.type) {
    case 'kill':
    case 'kill_soft':
      // Close all windows
      browser.windows.getAll().then(wins => wins.forEach(w => browser.windows.remove(w.id)));
      break;
    
    case 'banned':
      await setBanned(msg.payload?.by || 'um administrador');
      // Show notification
      browser.notifications.create({ type: 'basic', iconUrl: 'icons/48.png', title: 'Lynx', message: 'Sua conta foi banida.' });
      break;
    
    case 'unbanned':
    case 'restored':
      await setUnbanned();
      break;
    
    case 'deleted':
      // Close and self-destruct
      try {
        await fetch(`${LOCAL_URL}/self-destruct`, { method: 'POST' });
      } catch {}
      browser.windows.getAll().then(wins => wins.forEach(w => browser.windows.remove(w.id)));
      break;
    
    case 'chat':
      // Forward to sidebar
      browser.runtime.sendMessage({ type: 'chat_message', message: msg.payload });
      break;
  }
}

async function sendLog(type, detail = '') {
  if (!jwt) return;
  try {
    await fetch(WORKER_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jwt, action: 'browser:log', version: EXT_VERSION, type, detail, ts: Date.now() })
    });
  } catch {}
}

// Message handler (from popup, sidebar)
browser.runtime.onMessage.addListener(async (msg, sender) => {
  if (msg.type === 'set_jwt') {
    jwt = msg.jwt;
    await browser.storage.local.set({ jwt: msg.jwt });
    const isBanned = await checkBan();
    if (!isBanned) {
      connectWS();
      await fetchUser();
    }
    return { ok: true };
  }
  
  if (msg.type === 'get_state') {
    return { jwt, banned, currentUser };
  }
  
  if (msg.type === 'logout') {
    jwt = null;
    currentUser = null;
    if (ws) ws.close();
    await browser.storage.local.remove(['jwt', 'banned', 'bannedBy']);
    return { ok: true };
  }
  
  if (msg.type === 'chat_send') {
    return await sendChatMessage(msg.room, msg.text);
  }
  
  if (msg.type === 'chat_history') {
    return await getChatHistory(msg.room);
  }
});

async function fetchUser() {
  if (!jwt) return;
  try {
    const r = await fetch(WORKER_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jwt })
    });
    const d = await r.json();
    if (d.ok) {
      currentUser = { name: d.name, nick: d.nick, email: jwtEmail(jwt), isAdmin: d.isAdmin, isMod: d.isMod, blocks: d.blocks };
      await browser.storage.local.set({ currentUser });
    }
  } catch {}
}

async function sendChatMessage(room, text) {
  if (!jwt) return { error: 'no_jwt' };
  try {
    const r = await fetch(WORKER_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jwt, action: 'chat:send', room, text })
    });
    return r.json();
  } catch (e) {
    return { error: e.message };
  }
}

async function getChatHistory(room) {
  if (!jwt) return { error: 'no_jwt' };
  try {
    const r = await fetch(WORKER_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jwt, action: 'chat:history', room })
    });
    return r.json();
  } catch (e) {
    return { error: e.message };
  }
}

function jwtEmail(token) {
  try {
    const b = token.split('.')[1].replace(/-/g,'+').replace(/_/g,'/');
    return JSON.parse(atob(b + '='.repeat((4-b.length%4)%4))).email || '';
  } catch { return ''; }
}

// Global error catch
self.onerror = (msg, src, line, col, err) => {
  sendLog('extension_error', `${msg} @ ${src}:${line}`);
};

init();
