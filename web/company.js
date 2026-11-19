const companyPanel = document.createElement('section');
companyPanel.className = 'card panel space-y-4';
companyPanel.innerHTML = '<div class="iconbox">✎</div><h2>Настройки магазина</h2><label for="companyInput" class="block text-sm font-semibold">Название магазина на ценнике</label><input id="companyInput" class="field" maxlength="255" required><button id="saveCompany" class="btn btn-primary">Сохранить название</button><p id="companyStatus" role="status"></p>';
document.querySelector('main > div.grid')?.append(companyPanel);
const saveCompany = document.getElementById('saveCompany');
if (saveCompany) saveCompany.onclick = async () => {
  const field = document.getElementById('companyInput');
  const status = document.getElementById('companyStatus');
  if (!field || !status) return;
  const name = field.value.trim();
  if (!name) { status.textContent = 'Укажите название магазина'; return; }
  try {
    await api('/api/me/settings', {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({company_name:name})});
    const heading = document.getElementById('companyName');
    if (heading) heading.textContent = name;
    field.value = name;
    status.textContent = 'Название сохранено';
  } catch (error) { status.textContent = error.message; }
};
