const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

async function run(missingIntegration) {
  const elements = Object.fromEntries(['companyName', 'planBadge', 'key', 'link', 'today', 'subscription', 'message', 'templates'].map(id => [id, {}]));
  if (!missingIntegration) elements.integrationStatus = {};
  const selected = {};
  let lastPatch;
  const document = {
    getElementById: id => elements[id] || null,
    querySelector: selector => selector === 'main > div.grid' ? {append(panel) { for (const id of ['companyInput', 'companyStatus', 'saveCompany']) elements[id] = {}; }} : selected,
    createElement: () => ({})
  };
  const profile = {company_name:'Магазин', plan:'free', api_key:'key', deep_link:'link', printed_today:3, free_prints_used:4, template_type:'a4_3x4', moysklad_configured:true};
  const fetch = async (path, options = {}) => {
    if (path === '/api/me/settings') lastPatch = JSON.parse(options.body);
    return {ok:true, json:async () => path === '/api/me' ? profile : {}};
  };
  const context = vm.createContext({document, fetch, localStorage:{getItem:()=>'test'}, location:{}, CSS:{escape:x=>x}, console});
  vm.runInContext(fs.readFileSync('web/dashboard.js','utf8'), context);
  vm.runInContext(fs.readFileSync('web/company.js','utf8'), context);
  await vm.runInContext('load()', context);
  assert.equal(elements.companyName.textContent, 'Магазин');
  assert.equal(elements.companyInput.value, 'Магазин');
  assert.equal(elements.today.textContent, 3);
  assert.match(elements.subscription.textContent, /26/);
  elements.companyInput.value = 'Новый магазин';
  await elements.saveCompany.onclick();
  assert.equal(lastPatch.company_name, 'Новый магазин');
  assert.equal(elements.companyName.textContent, 'Новый магазин');
}
run(false).then(() => run(true)).then(() => console.log('Dashboard profile, missing element and company update: OK')).catch(error => { console.error(error); process.exitCode = 1; });
