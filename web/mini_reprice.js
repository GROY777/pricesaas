async function refreshReprice() {
  try {
    const rows = await api('/api/products/changed-prices');
    document.getElementById('miniReprice').hidden = !rows.length;
    document.getElementById('miniRepriceCount').textContent = rows.length;
  } catch (err) { message.textContent = err.message; }
}
document.getElementById('miniRepricePrint').onclick = async e => {
  e.currentTarget.disabled = true;
  try { await api('/api/print/changed-prices', {method:'POST'}); message.textContent = 'Задание отправлено на печать'; await refreshReprice(); }
  catch (err) { message.textContent = err.message; }
  finally { e.currentTarget.disabled = false; }
};
refreshReprice();
