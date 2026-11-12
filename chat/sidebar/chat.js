const msgBox = document.getElementById('messages');
const input = document.getElementById('input');

function addMsg(m) {
  const el = document.createElement('div');
  el.className = 'msg';
  el.innerHTML = `<span class="name">${m.name}</span>${m.text}`;
  msgBox.appendChild(el);
  msgBox.scrollTop = msgBox.scrollHeight;
}

document.getElementById('send').addEventListener('click', async () => {
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  const res = await browser.runtime.sendMessage({ type: 'chat_send', room: 'global', text });
  if (res.error) alert('Erro ao enviar: ' + res.error);
});

// Escuta mensagens que o background.js (WebSocket) recebe
browser.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'chat_incoming') {
    addMsg(msg.message);
  }
});
