(() => {
  const el = id => document.getElementById(id), selected = new Set();
  let page = 1, total = 0, timer;
  const message = text => { el('catalogMessage').textContent = text; };
  const request = async (path, method, body) => api(path, {method, headers: {'Content-Type':'application/json'}, body:JSON.stringify(body)});
  async function loadCatalog() {
    try {
      const params = new URLSearchParams({q:el('catalogQuery').value, filter:el('catalogFilter').value, page, limit:50});
      const data = await (await api('/api/catalog?' + params)).json(); total = data.total;
      const tbody = el('catalogRows'); tbody.replaceChildren();
      for (const item of data.items) {
        const tr = document.createElement('tr');
        const cell = () => {const td=document.createElement('td'); td.className='p-2 border-b'; tr.append(td); return td;};
        const check=document.createElement('input'); check.type='checkbox'; check.checked=selected.has(item.id); check.onchange=()=>check.checked?selected.add(item.id):selected.delete(item.id); cell().append(check);
        for (const value of [item.name,item.article || '—',item.barcode || '—',item.price,item.unit,item.updated_at ? new Date(item.updated_at).toLocaleString('ru-RU') : '—']) cell().textContent=value;
        const actions=cell(), edit=document.createElement('button'), del=document.createElement('button'); edit.textContent='Изменить'; del.textContent='Удалить'; edit.className=del.className='text-blue-700 mr-3';
        edit.onclick=()=>editProduct(item); del.onclick=async()=>{if(confirm('Удалить товар «'+item.name+'»?')) await remove([item.id]);}; actions.append(edit,del); tbody.append(tr);
      }
      el('catalogPage').textContent=`Страница ${page} · Всего ${total}`; el('catalogPrev').disabled=page<=1; el('catalogNext').disabled=page*50>=total;
    } catch(e) {message(e.message);}
  }
  async function editProduct(item) {
    const name=prompt('Наименование',item?.name || ''); if(name===null)return;
    const article=prompt('Артикул',item?.article || ''); if(article===null)return;
    const barcode=prompt('Штрихкод (можно оставить пустым)',item?.barcode || ''); if(barcode===null)return;
    const price=prompt('Цена, ₽',item?.price ?? '0'); if(price===null)return;
    const unit=prompt('Единица измерения',item?.unit || 'шт.'); if(unit===null)return;
    try {await request('/api/catalog'+(item?'/'+item.id:''),item?'PATCH':'POST',{name,article,barcode:barcode || null,price,unit}); message('Товар сохранён'); await loadCatalog();} catch(e){message(e.message);}
  }
  async function remove(ids) {try {const result=await (await request('/api/catalog/delete','POST',{ids})).json(); ids.forEach(id=>selected.delete(id)); message(`Удалено: ${result.deleted}`); await loadCatalog();}catch(e){message(e.message);}}
  el('catalogQuery').oninput=()=>{clearTimeout(timer);timer=setTimeout(()=>{page=1;loadCatalog();},300)};
  el('catalogFilter').onchange=()=>{page=1;loadCatalog();};
  el('catalogPrev').onclick=()=>{if(page>1){page--;loadCatalog();}}; el('catalogNext').onclick=()=>{if(page*50<total){page++;loadCatalog();}};
  el('catalogAdd').onclick=()=>editProduct(null);
  el('catalogSelect').onchange=e=>document.querySelectorAll('#catalogRows input[type=checkbox]').forEach(box=>{if(box.checked!==e.target.checked)box.click();});
  el('catalogDelete').onclick=()=>{if(selected.size&&confirm(`Удалить выбранные товары: ${selected.size}?`))remove([...selected]);};
  el('catalogPrint').onclick=async()=>{if(!selected.size)return;try{const result=await (await request('/api/catalog/print','POST',{ids:[...selected]})).json();message(`Отправлено на печать: ${result.items_count}`);}catch(e){message(e.message);}};
  el('catalogClear').onclick=async()=>{if(!confirm('Удалить ВСЕ товары магазина? Это действие нельзя отменить.'))return;if(prompt('Для подтверждения введите УДАЛИТЬ')!=='УДАЛИТЬ')return;try{const data=await (await api('/api/catalog',{method:'DELETE'})).json();selected.clear();page=1;message(`Удалено товаров: ${data.deleted}`);loadCatalog();}catch(e){message(e.message);}};
  el('catalogExport').onclick=async()=>{try{const blob=await (await api('/api/catalog/export')).blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='PriceSnap_Products.xlsx';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){message(e.message);}};
  const replace=el('catalogReplace');
  api('/api/me').then(r=>r.json()).then(data=>{replace.checked=!!data.replace_missing_products;}).catch(e=>message(e.message));
  replace.onchange=async()=>{const checked=replace.checked;try{await request('/api/me/settings','PATCH',{replace_missing_products:checked});message('Настройка синхронизации сохранена');}catch(e){replace.checked=!checked;message(e.message);}};
  loadCatalog();
})();
