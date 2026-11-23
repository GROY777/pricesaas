(() => {
  const width = document.getElementById('labelWidth'), height = document.getElementById('labelHeight');
  const presets = document.getElementById('labelPresets'), preview = document.getElementById('labelPreview'), status = document.getElementById('labelStatus');
  let saved = [];
  function update() {
    const w = Number(width.value), h = Number(height.value);
    const scale = Math.min(3, 300 / Math.max(w, 1), 250 / Math.max(h, 1));
    preview.style.width = `${w * scale}px`; preview.style.height = `${h * scale}px`;
    preview.style.fontSize = `${Math.max(8, Math.min(16, w * scale / 14))}px`;
    const nodes = preview.children;
    nodes[0].style.fontSize = `${Math.max(6, Math.min(10, h * scale * .07))}px`;
    nodes[1].style.fontSize = `${Math.max(7, Math.min(14, h * scale * .11))}px`;
    nodes[2].style.fontSize = `${Math.max(9, Math.min(24, h * scale * .18, w * scale * .15))}px`;
    nodes[3].style.fontSize = `${Math.max(5, Math.min(8, w * scale * .04))}px`;
  }
  function renderPresets() {
    presets.replaceChildren(new Option('Стандарт 60×50 мм', 'standard'));
    saved.forEach((p, i) => presets.add(new Option(p.name, String(i))));
  }
  async function save() {
    if (!width.reportValidity() || !height.reportValidity()) return false;
    try {
      await api('/api/me/settings', {method:'PATCH', headers:{'Content-Type':'application/json'}, body: JSON.stringify({label_settings:{width:Number(width.value), height:Number(height.value), presets:saved}})});
      status.textContent = 'Размер сохранён.'; return true;
    } catch (e) { status.textContent = e.message || 'Ошибка сохранения'; return false; }
  }
  width.oninput = height.oninput = update;
  presets.onchange = () => { const p = presets.value === 'standard' ? {width:60,height:50} : saved[Number(presets.value)]; if (p) {width.value=p.width; height.value=p.height; update();} };
  document.getElementById('labelSave').onclick = save;
  document.getElementById('labelSavePreset').onclick = async () => { if (!width.reportValidity() || !height.reportValidity()) return; const name = prompt('Название пресета'); if (!name || !name.trim()) return; if (saved.length >= 20 || name.trim().length > 60) { status.textContent = 'Допустимо до 20 пресетов, название — до 60 символов.'; return; } saved.push({name:name.trim(),width:Number(width.value),height:Number(height.value)}); if (await save()) renderPresets(); else saved.pop(); };
  (async () => { try { const data = await (await api('/api/me')).json(); const s = data.label_settings || {}; width.value = s.width ?? 60; height.value = s.height ?? 50; saved = Array.isArray(s.presets) ? s.presets : []; renderPresets(); update(); } catch (e) {status.textContent = e.message;} })();
})();
