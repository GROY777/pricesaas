const moySection = document.createElement('section');
moySection.className = 'bg-white rounded-2xl p-6 space-y-4';
moySection.innerHTML = '<h2 class="text-xl font-bold">МойСклад</h2><p class="text-slate-600">Укажите токен для синхронизации товаров каждые 15 минут.</p><input id="moyToken" type="password" autocomplete="off" placeholder="Токен МойСклад" class="border rounded p-2 w-full"><div class="flex gap-3 flex-wrap"><button id="saveMoy" class="text-blue-700">Сохранить токен</button><button id="clearMoy" class="text-red-700">Удалить токен</button><button id="syncMoy" class="bg-blue-700 text-white px-3 py-2 rounded-lg">Синхронизировать</button></div><p id="moyStatus" role="status"></p>';
document.querySelector('main > div.grid').append(moySection);
async function saveMoyToken(value) {
  try {
    await api('/api/me/settings', {method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify({moysklad_token:value})});
    document.getElementById('moyToken').value = '';
    document.getElementById('moyStatus').textContent = value ? 'Токен сохранён' : 'Токен удалён';
  } catch (e) { document.getElementById('moyStatus').textContent = e.message; }
}
document.getElementById('saveMoy').onclick = () => { const value = document.getElementById('moyToken').value.trim(); if (value) saveMoyToken(value); };
document.getElementById('clearMoy').onclick = () => saveMoyToken(null);
document.getElementById('syncMoy').onclick = async () => {
  const status = document.getElementById('moyStatus'); status.textContent = 'Синхронизация…';
  try { const result = await (await api('/api/me/sync-moysklad', {method:'POST'})).json(); status.textContent = `Синхронизировано: ${result.synced}`; }
  catch (e) { status.textContent = e.message; }
};
