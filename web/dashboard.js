const token = localStorage.getItem('token');
if (!token) location.href = '/';
const byId = id => document.getElementById(id);
const setText = (id, text) => { const el = byId(id); if (el) el.textContent = text; };
const setValue = (id, value) => { const el = byId(id); if (el) el.value = value ?? ''; };

async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {Authorization: 'Bearer ' + token, ...options.headers}});
  if (response.status === 401) {
    localStorage.removeItem('token');
    location.href = '/';
    throw Error('Сессия завершена');
  }
  if (!response.ok) {
    const data = await response.json();
    throw Error(typeof data.detail === 'string' ? data.detail : 'Ошибка запроса');
  }
  return response;
}

async function load() {
  try {
    const data = await (await api('/api/me')).json();
    setText('integrationStatus', data.moysklad_configured ? 'МойСклад подключён' : 'Настроить интеграцию');
    setText('companyName', data.company_name);
    setText('planBadge', data.plan === 'pro' ? 'Магазин' : 'Старт');
    setValue('companyInput', data.company_name);
    setValue('key', data.api_key);
    setValue('link', data.deep_link);
    setText('today', data.printed_today);
    const active = data.plan === 'pro' && data.subscription_until && new Date(data.subscription_until) > new Date();
    setText('subscription', active ? 'Активна до ' + new Date(data.subscription_until).toLocaleDateString('ru-RU') : 'Бесплатных ценников осталось: ' + Math.max(0, 30 + (data.free_prints_bonus || 0) - data.free_prints_used));
    const selected = document.querySelector(`input[name="template"][value="${CSS.escape(data.template_type)}"]`);
    if (selected) selected.checked = true;
  } catch (error) { setText('message', error.message); }
}

const templates = byId('templates');
if (templates) templates.onchange = async event => {
  try { await api('/api/me/settings', {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({template_type:event.target.value})}); }
  catch (error) { setText('message', error.message); }
};
async function regenerate() {
  if (!confirm('Обновить ключ? Подключённым агентам понадобится новый ключ.')) return;
  try { await api('/api/me/settings', {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({regenerate_api_key:true})}); await load(); }
  catch (error) { setText('message', error.message); }
}
async function renewInvite() {
  if (!confirm('Отозвать старую ссылку и создать новую?')) return;
  try { await api('/api/me/settings', {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({regenerate_invite_token:true})}); await load(); }
  catch (error) { setText('message', error.message); }
}
async function copyValue(id) {
  const el = byId(id);
  if (!el) return;
  try { await navigator.clipboard.writeText(el.value); }
  catch (error) { setText('message', 'Не удалось скопировать значение'); }
}
async function pay(productType, templateId) {
  try { const data = await (await api('/api/payments/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({product_type:productType, ...(templateId ? {template_id:templateId} : {})})})).json(); location.href = data.confirmation_url; }
  catch (error) { setText('message', error.message); }
}
const proPrices = {pro_1m: '990', pro_3m: '2 490', pro_12m: '7 990'};
let selectedProPlan = 'pro_1m';
const proPeriods = byId('proPeriods');
const payPro = byId('payPro');
if (proPeriods && payPro) {
  proPeriods.addEventListener('click', event => {
    const selected = event.target.closest('button[data-plan]');
    if (!selected || !proPeriods.contains(selected) || !Object.hasOwn(proPrices, selected.dataset.plan)) return;
    selectedProPlan = selected.dataset.plan;
    proPeriods.querySelectorAll('button[data-plan]').forEach(button => {
      const active = button === selected;
      button.setAttribute('aria-pressed', String(active));
      button.classList.toggle('border-blue-600', active);
      button.classList.toggle('bg-blue-50', active);
      button.classList.toggle('border-slate-200', !active);
      button.classList.toggle('bg-white', !active);
    });
    payPro.textContent = `Оплатить ${proPrices[selectedProPlan]} ₽`;
  });
  payPro.addEventListener('click', () => pay(selectedProPlan));
}
const returnedFromPayment = new URLSearchParams(location.search).get('payment') === 'success';
if (returnedFromPayment) {
  setText('message', 'Вы вернулись со страницы оплаты. Подтверждаем платёж; статус обновится после обработки.');
  history.replaceState(null, '', location.pathname);
}
async function reconcilePayments() {
  try {
    const result = await (await api('/api/payments/sync', {method:'POST'})).json();
    await load();
    if (result.succeeded) setText('message', 'Оплата подтверждена, доступ обновлён.');
    const rows = await (await api('/api/payments/history')).json();
    if (rows.some(p => p.status === 'pending' && Date.now() - new Date(p.created_at).getTime() < 86400000)) {
      setTimeout(reconcilePayments, 20000);
    }
  } catch (error) {
    if (returnedFromPayment) setText('message', error.message);
  }
}
if (token) reconcilePayments();
async function download() {
  try {
    const blob = await (await api('/api/download/agent')).blob();
    const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'PriceAgent_Setup.exe'; link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 10000);
  } catch (error) { setText('message', error.message); }
}
