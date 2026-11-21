(() => {
  const importFile = document.getElementById('importFile');
  const importPreview = document.getElementById('importPreview');
  const importMapping = document.getElementById('importMapping');
  const importStatus = document.getElementById('importStatus');
  const fields = ['sku', 'name', 'price', 'old_price', 'barcode', 'unit'];
  const showStatus = (message, error = false) => { if (importStatus) { importStatus.textContent = message; importStatus.className = `text-sm mt-2 ${error ? 'text-red-700' : 'text-emerald-700'}`; } };
  const authFetch = (url, options = {}) => fetch(url, {...options, headers: {...(options.headers || {}), Authorization: `Bearer ${token}`}});
  if (importFile) importFile.addEventListener('change', async () => {
    const file = importFile.files?.[0]; if (!file) return;
    const form = new FormData(); form.append('file', file); showStatus('Анализируем колонки…');
    try {
      const response = await authFetch('/api/products/preview-columns', {method: 'POST', body: form});
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || 'Не удалось прочитать файл');
      const preview = await response.json(); importMapping.replaceChildren();
      for (const key of fields) { const label = document.createElement('label'); label.className = 'block text-sm'; label.textContent = key; const select = document.createElement('select'); select.dataset.key = key; select.className = 'field'; select.append(new Option('— не выбрано —', '')); (preview.headers || []).forEach(header => select.append(new Option(header, header))); if (preview.detected_mapping?.[key]) select.value = preview.detected_mapping[key]; label.append(select); importMapping.append(label); }
      importPreview.textContent = (preview.rows || []).map(row => Object.values(row).join(' · ')).join('\n');
      showStatus(preview.needs_manual_mapping ? 'Выберите обязательные колонки вручную.' : `Распознаны колонки: Наименование → ${preview.detected_mapping.name}, Цена → ${preview.detected_mapping.price}`);
    } catch (error) { showStatus(error.message || 'Ошибка анализа файла', true); }
  });
  document.getElementById('saveMapping')?.addEventListener('click', async () => {
    const mapping = Object.fromEntries([...importMapping.querySelectorAll('select')].filter(select => select.value).map(select => [select.dataset.key, select.value]));
    try { const response = await authFetch('/api/me/settings', {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({column_mapping: mapping})}); if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || 'Не удалось сохранить сопоставление'); showStatus('Сопоставление колонок сохранено.'); } catch (error) { showStatus(error.message || 'Ошибка сохранения', true); }
  });
  document.getElementById('sampleExcel')?.addEventListener('click', async () => {
    try { showStatus('Готовим пример Excel…'); const response = await authFetch('/api/products/sample-excel'); if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || 'Не удалось скачать пример Excel'); const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = 'PriceSnap_Example.xlsx'; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); showStatus('Пример Excel скачан.'); } catch (error) { showStatus(error.message || 'Ошибка скачивания', true); }
  });
})();
