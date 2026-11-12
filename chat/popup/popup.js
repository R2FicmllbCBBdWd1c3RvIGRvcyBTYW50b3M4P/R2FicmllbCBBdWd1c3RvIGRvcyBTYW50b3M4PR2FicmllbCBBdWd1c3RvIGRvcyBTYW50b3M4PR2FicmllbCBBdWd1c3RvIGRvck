document.addEventListener('DOMContentLoaded', async () => {
  const res = await browser.runtime.sendMessage({ type: 'get_state' });
  const status = document.getElementById('status');
  if (res && res.jwt) {
    status.textContent = 'Conectado como: ' + (res.currentUser?.name || 'Aluno');
    status.style.color = '#34d399';
  } else {
    status.textContent = 'Desconectado';
    status.style.color = '#e05252';
  }
});
