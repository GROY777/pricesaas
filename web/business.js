async function loadEmployees() {
  const list = document.getElementById('employeeList');
  try {
    const rows = await (await api('/api/employees')).json();
    list.replaceChildren();
    for (const e of rows) {
      const row = document.createElement('div'); row.className = 'flex justify-between items-center gap-3 border-b border-slate-200 py-3';
      const info = document.createElement('div');
      const name = document.createElement('strong'); name.textContent = e.full_name;
      const status = document.createElement('p'); status.className = 'text-sm text-slate-500';
      status.textContent = !e.is_active ? 'Доступ отозван' : e.activated_at ? 'Активен' + (e.telegram_username ? ' @' + e.telegram_username : '') : 'Ожидает перехода';
      info.append(name, status); row.append(info);
      if (e.is_active) { const button = document.createElement('button'); button.className = 'text-red-700 text-sm font-semibold'; button.textContent = 'Забрать доступ'; button.onclick = async () => { try { await api('/api/employees/' + e.id, {method:'DELETE'}); await loadEmployees(); } catch (err) { setText('businessMessage', err.message); } }; row.append(button); }
      list.append(row);
    }
  } catch (err) { setText('businessMessage', err.message); }
}
document.getElementById('inviteForm').onsubmit = async e => {
  e.preventDefault();
  try { const data = await (await api('/api/employees/invite', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({full_name:document.getElementById('employeeName').value})})).json();
    document.getElementById('employeeLink').value = data.url; document.getElementById('inviteResult').hidden = false; e.target.reset(); await loadEmployees();
  } catch (err) { setText('businessMessage', err.message); }
};
async function loadChangedPrices() {
  try {
    const rows = await (await api('/api/products/changed-prices')).json();
    setText('changedCount', rows.length); setText('changedPrintCount', rows.length);
    document.getElementById('changedPrint').disabled = !rows.length;
    const body = document.getElementById('changedRows'); body.replaceChildren();
    for (const p of rows) { const row = document.createElement('tr'); for (const text of [p.name, p.barcode, `${p.previous_price ?? '—'} → ${p.price}`]) { const cell = document.createElement('td'); cell.className = 'py-2 pr-4'; cell.textContent = text; row.append(cell); } body.append(row); }
  } catch (err) { setText('businessMessage', err.message); }
}
document.getElementById('changedPrint').onclick = async e => { e.currentTarget.disabled = true; try { await api('/api/print/changed-prices', {method:'POST'}); setText('businessMessage', 'Задание отправлено на печать'); await loadChangedPrices(); await load(); } catch (err) { setText('businessMessage', err.message); e.currentTarget.disabled = false; } };
document.getElementById('changedClear').onclick = async () => { if (!confirm('Сбросить список изменившихся цен?')) return; try { await api('/api/products/changed-prices/clear', {method:'POST'}); await loadChangedPrices(); } catch (err) { setText('businessMessage', err.message); } };
loadEmployees(); loadChangedPrices();
