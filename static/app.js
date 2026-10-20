'use strict';
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = v => Number(v || 0).toLocaleString('fa-IR');
const labels = {connected:'متصل',pending:'در انتظار',disconnected:'قطع اتصال',restricted:'محدود شده',deleting:'در حال حذف',collecting:'در حال جمع‌آوری',ready:'آماده',partial:'فهرست ناقص',failed:'ناموفق',draft:'پیش‌نویس',running:'در حال ارسال',paused:'متوقف',completed:'پایان‌یافته',cancelled:'لغوشده',sending:'در حال ارسال',sent:'ارسال‌شده',skipped:'ردشده',uncertain:'نیاز به بررسی'};
const titles = {lists:'فهرست اعضا',accounts:'حساب‌ها',campaigns:'کمپین‌ها',activity:'گزارش فعالیت'};
let state, token, route = 'lists', selected = null, page = 0, search = '', formOpen = false;
let authId = null, authStep = null, sourceGroups = [], senderOrder = [], detailCache = null;
let polling = false, actionBusy = false, noticeTimer;
const badge = s => `<span class="badge ${['connected','ready','completed','sent'].includes(s)?'good':['partial','paused','uncertain'].includes(s)?'warn':['failed','restricted','cancelled','disconnected'].includes(s)?'bad':['running','collecting','sending'].includes(s)?'live':''}">${esc(labels[s] || s)}</span>`;
const accountName = id => state.account_labels?.[id] || state.accounts.find(a => a.id === id)?.label || id;
const accountChecks = (selectedIds = []) => state.accounts.filter(a => a.status === 'connected').map(a => `<label class="check"><input type="checkbox" name="account" value="${a.id}" ${selectedIds.includes(a.id)?'checked':''}>${esc(a.label)} <bdi>@${esc(a.username || a.phone)}</bdi></label>`).join('');
const icon = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4h14v16H7M3 8h10M3 12h10M3 16h10"/></svg>`;

// Refresh live state without freezing it while keyboard controls have focus.
function setLiveHTML(selector, html) {
  const region=$(selector); if(!region)return;
  const active=document.activeElement;
  const hadFocus=region.contains(active);
  const identity=hadFocus?{id:active.id, action:active.dataset.action, key:active.dataset.id, resolution:active.dataset.resolution}:null;
  const reviewed=$('#reviewed',region)?.checked;
  region.innerHTML=html;
  if(reviewed && $('#reviewed',region)) {
    $('#reviewed',region).checked=true;
    $('#review-button',region).disabled=false;
  }
  if(!hadFocus)return;
  let replacement=identity.id?document.getElementById(identity.id):null;
  if(!replacement && identity.action)replacement=$$('[data-action]',region).find(el=>el.dataset.action===identity.action && el.dataset.id===identity.key && el.dataset.resolution===identity.resolution);
  if(replacement && !replacement.disabled)replacement.focus({preventScroll:true});
  else {region.tabIndex=-1;region.focus({preventScroll:true});}
}

function notice(message, error = false) {
  const el = $('#notice'); el.textContent = message; el.classList.toggle('error', error); el.hidden = false;
  clearTimeout(noticeTimer); noticeTimer = setTimeout(() => {el.hidden = true;}, error ? 12000 : 4500);
}
async function api(path, body, method) {
  const headers = {'X-CSRF-Token':token};
  let data = body;
  if (body !== undefined && !(body instanceof FormData)) {headers['Content-Type']='application/json'; data=JSON.stringify(body);}
  const res = await fetch('/api'+path, {method:method || (body === undefined?'GET':'POST'), headers, body:data});
  const out = await res.json().catch(() => ({}));
  if (!res.ok) {
    let detail = out.detail;
    if (Array.isArray(detail)) detail = detail.map(x => `${x.loc.at(-1)}: ${x.msg}`).join(' / ');
    throw new Error(detail || 'عملیات انجام نشد؛ اتصال برنامه را بررسی کنید.');
  }
  return out;
}
async function refresh() {
  state = await api('/state');
  $$('[data-action="account-delete"],[data-action="list-delete"],[data-action="campaign-delete"],[data-action="cleanup-photos"]').forEach(button=>button.disabled=state.busy);
}
const field = (label, name, opts = '') => `<div class="field"><label for="${name}">${label}</label><input id="${name}" name="${name}" ${opts}></div>`;
function heading(title, sub, actions='') {return `<div class="page-head"><div><h1>${title}</h1><p class="sub">${sub}</p></div><div class="actions">${actions}</div></div>`;}
function guide() {return `<aside class="guide"><h2>از فهرست تا ارسال</h2><ol class="steps"><li><span class="step-number">۱</span><div><strong>اعضا را جمع‌آوری کنید</strong><p>گروه‌های حساب‌های متصل را انتخاب کنید. این مرحله هیچ پیامی ارسال نمی‌کند.</p></div></li><li><span class="step-number">۲</span><div><strong>فهرست را بررسی کنید</strong><p>گیرنده‌های تکراری حذف می‌شوند. پیش از ساخت کمپین، فهرست را مرور کنید.</p></div></li><li><span class="step-number">۳</span><div><strong>کمپین را شروع کنید</strong><p>متن، حساب‌ها و زمان‌بندی را تأیید کنید؛ سپس ارسال را آغاز کنید.</p></div></li></ol><p class="guide-note">تلگرام ممکن است فقط بخشی از اعضای یک گروه را نمایش دهد. وضعیت جمع‌آوری در کنار هر فهرست ثبت می‌شود.</p></aside>`;}
function empty(title, text, action='') {return `<div class="empty"><span class="empty-icon">${icon}</span><h2>${title}</h2><p>${text}</p>${action}</div>`;}
function pager(total) {return `<div class="pager"><span>${num(total)} مورد · صفحه ${num(page+1)}</span><div class="actions"><button class="quiet" data-action="page-prev" ${page===0?'disabled':''}>قبلی</button><button class="quiet" data-action="page-next" ${(page+1)*100>=total?'disabled':''}>بعدی</button></div></div>`;}
function available() {return state.accounts.some(a=>a.status==='connected');}
function render() {
  $$('.rail nav a').forEach(a => a.toggleAttribute('aria-current', a.dataset.nav === route));
  $$('.rail nav a[aria-current]').forEach(a => a.setAttribute('aria-current','page'));
  $('#breadcrumb').textContent=titles[route];
  if (route==='accounts') renderAccounts();
  else if(route==='lists') selected ? renderList() : renderLists();
  else if(route==='campaigns') selected ? renderCampaign() : renderCampaigns();
  else renderActivity();
}
function renderAccounts() {
  $('#workspace').innerHTML = heading('حساب‌های تلگرام','حساب‌های شخصی را متصل کنید و وضعیت هرکدام را ببینید.',`<button data-action="account-form" ${!state.configured || state.busy?'disabled':''}>افزودن حساب</button>`)+
    `<div class="layout"><div><section class="panel"><div class="panel-head"><h2>حساب‌های متصل</h2><span class="hint" id="account-count">${num(state.accounts.length)} حساب</span></div><div id="accounts-table"></div></section>
    <section class="panel"><div class="panel-body"><details ${state.configured?'':'open'}><summary>تنظیمات API تلگرام ${state.configured?'· ثبت شده':''}</summary><p class="sub">API ID و API Hash خود را از <a href="https://my.telegram.org" target="_blank" rel="noopener noreferrer">my.telegram.org</a> دریافت کنید. اطلاعات فقط روی این رایانه ذخیره می‌شود.</p><form id="credentials-form" class="panel-body"><div class="form-grid">${field('API ID','api_id','type="number" required min="1" dir="ltr" autocomplete="off"')}${field('API Hash','api_hash','type="password" required minlength="32" maxlength="32" dir="ltr" autocomplete="off"')}</div><div class="form-actions"><button type="submit">ذخیره تنظیمات</button></div></form></details><div class="form-section"><h3>عکس‌های بدون استفاده</h3><p class="sub">فقط عکس‌هایی که به هیچ کمپینی متصل نیستند پاک می‌شوند.</p><div class="form-actions"><button class="secondary" data-action="cleanup-photos" ${state.busy?'disabled':''}>پاکسازی عکس‌های بدون استفاده</button></div></div></div></section><div id="account-login"></div></div>
    <aside class="guide"><h2>ورود امن در همین برنامه</h2><p class="sub">شماره تلفن، کد ورود تلگرام و در صورت فعال بودن، گذرواژه دومرحله‌ای را وارد کنید.</p><p class="guide-note">کد ورود و گذرواژه در تاریخچه ذخیره نمی‌شوند. فایل نشست حساب روی این رایانه باقی می‌ماند و باید خصوصی بماند.</p></aside></div>`;
  updateAccounts();
}
function updateAccounts() {
  const el = $('#accounts-table'); if(!el)return;
  if($('#account-count'))$('#account-count').textContent=`${num(state.accounts.length)} حساب`;
  el.innerHTML = state.accounts.length ? `<div class="table-wrap"><table><thead><tr><th>حساب</th><th>شماره</th><th>وضعیت</th><th>عملیات</th></tr></thead><tbody>${state.accounts.map(a=>`<tr><td><span class="name">${esc(a.label)}</span><small><bdi>${a.username?'@'+esc(a.username):''}</bdi></small></td><td><bdi>${esc(a.phone)}</bdi></td><td>${badge(a.status)}${a.error?`<small class="mono">${esc(a.error)}</small>`:''}${a.wait_until>Date.now()/1000?`<small>انتظار تا ${new Date(a.wait_until*1000).toLocaleTimeString('fa-IR')}</small>`:''}</td><td><button class="quiet" data-action="account-check" data-id="${a.id}" ${state.busy||a.status==='deleting'?'disabled':''}>بررسی اتصال</button><button class="quiet" data-action="account-relogin" data-id="${a.id}" ${state.busy||a.status==='deleting'?'disabled':''}>ورود مجدد</button><button class="quiet danger" data-action="account-delete" data-id="${a.id}" ${state.busy?'disabled':''}>${a.status==='deleting'?'تلاش مجدد برای حذف':'حذف'}</button></td></tr>`).join('')}</tbody></table></div>` : empty('هنوز حسابی اضافه نشده','ابتدا تنظیمات API را ثبت کنید، سپس شماره حساب تلگرام را وارد کنید.');
}
function showLogin(account=null) {
  formOpen = true; authId=null;authStep=null;
  $('#account-login').innerHTML=`<section class="panel"><div class="panel-head"><h2>${account?'ورود مجدد':'افزودن حساب'}</h2><button class="quiet" data-action="close-login">بستن</button></div><form id="login-form" class="panel-body"><div class="form-grid">${field('نام حساب','label',`required maxlength="100" value="${esc(account?.label||'')}" placeholder="مثلاً حساب اصلی"`)}${field('شماره با کد کشور','phone',`type="tel" required dir="ltr" value="${esc(account?.phone||'')}" placeholder="+989121234567" autocomplete="tel"`)}</div><div class="form-actions"><button type="submit">دریافت کد ورود</button></div></form><div id="verify-box"></div></section>`;
  $('#account-login').scrollIntoView({block:'nearest'});$('#label').focus();
}
function showVerify(step) {
  authStep=step;
  $('#verify-box').innerHTML=`<form id="verify-form" class="panel-body"><div class="field"><label for="secret">${step==='password'?'گذرواژه دومرحله‌ای':'کد ورود تلگرام'}</label><input id="secret" name="secret" type="${step==='password'?'password':'text'}" dir="ltr" required autocomplete="${step==='password'?'off':'one-time-code'}" ${step==='code'?'inputmode="numeric"':''}><span class="hint">${step==='password'?'گذرواژه فقط برای تکمیل ورود استفاده می‌شود.':'کد را از پیام تلگرام یا پیامک وارد کنید.'}</span></div><div class="form-actions"><button type="submit">تکمیل ورود</button></div></form>`;$('#secret').focus();
}
function renderLists() {
  $('#workspace').innerHTML=heading('فهرست اعضا','ابتدا اعضا را جمع‌آوری کنید؛ ارسال در مرحله بعد انجام می‌شود.',`<button class="secondary" data-action="import-form">ورود CSV</button><button data-action="collect-form" ${!available()||state.busy?'disabled':''}>جمع‌آوری از گروه</button>`)+
  (!available()?`<div class="banner"><p>برای دیدن گروه‌ها و جمع‌آوری اعضا، یک حساب تلگرام متصل کنید.</p><a class="button secondary" href="#accounts">اتصال حساب</a></div>`:'')+
  `<div class="layout"><div><div id="list-form"></div><section class="panel"><div class="panel-head"><h2>فهرست‌های ذخیره‌شده</h2><span class="hint">جمع‌آوری مستقل از ارسال</span></div><div id="lists-table"></div></section></div>${guide()}</div>`;updateLists();
}
function collectionSummary(list) {
  if(list.source==='CSV')return 'فایل CSV';
  try {
    const meta=JSON.parse(list.source);
    if(meta.method==='history')return meta.days_back==null?'تاریخچه گفتگو · همه تاریخچه':`تاریخچه گفتگو · ${num(meta.days_back)} روز گذشته`;
  } catch (_) { /* Older saved lists retain their existing member-list label. */ }
  return 'فهرست اعضای گروه';
}
function updateLists() {
  const el=$('#lists-table');if(!el)return;
  el.innerHTML=state.lists.length?`<div class="table-wrap"><table><thead><tr><th>نام فهرست</th><th>اعضا</th><th>وضعیت</th><th>عملیات</th></tr></thead><tbody>${state.lists.map(l=>`<tr><td><span class="name">${esc(l.title)}</span><small>${esc(collectionSummary(l))} · ${new Date(l.created).toLocaleDateString('fa-IR')}</small></td><td>${num(l.included)}<small>از ${num(l.total)} عضو ذخیره‌شده</small></td><td>${badge(l.status)}</td><td><button class="quiet" data-action="open-list" data-id="${l.id}">بررسی فهرست</button><button class="quiet danger" data-action="list-delete" data-id="${l.id}" ${state.busy?'disabled':''}>حذف</button></td></tr>`).join('')}</tbody></table></div>`:empty('اولین فهرست را آماده کنید','گروه‌های حساب متصل را انتخاب کنید یا فایلی با ستون username وارد کنید. پس از بررسی اعضا، کمپین بسازید.');
}
function showCollect() {
  formOpen=true;sourceGroups=[];
  $('#list-form').innerHTML=`<section class="panel">
    <div class="panel-head"><h2>جمع‌آوری اعضای گروه</h2><button class="quiet" data-action="close-list-form">بستن</button></div>
    <form id="collect-form" class="panel-body"><div class="form-grid">
      ${field('نام فهرست','list_title','required maxlength="150" placeholder="مثلاً اعضای گروه‌های کاری"')}
      <div class="field"><label for="source_account">حساب برای مشاهده گروه‌ها</label><select id="source_account">${state.accounts.filter(a=>a.status==='connected').map(a=>`<option value="${a.id}">${esc(a.label)}</option>`).join('')}</select></div>
      <div class="field full"><label for="collection_method">روش جمع‌آوری</label><select id="collection_method"><option value="members">فهرست اعضای گروه</option><option value="history">نویسندگان پیام‌های گفتگو</option></select></div>
    </div>
    <div id="history-options" class="form-section" hidden><h3>بازه تاریخچه گفتگو</h3><div class="form-grid">
      <div class="field"><label for="history_scope">بازه بررسی</label><select id="history_scope"><option value="all">همه تاریخچه قابل دسترس</option><option value="days">تعداد روزهای گذشته</option></select></div>
      ${field('چند روز به گذشته؟','history_days','type="number" min="1" max="36500" step="1" value="30" disabled')}
    </div><p class="hint">بازه از لحظه شروع جمع‌آوری محاسبه می‌شود. فقط نویسندگان قابل شناسایی ذخیره می‌شوند؛ ممکن است دیگر عضو گروه نباشند. متن پیام‌ها ذخیره نمی‌شود.</p></div>
    <div class="form-actions"><button type="button" class="secondary" data-action="load-groups">نمایش گروه‌ها</button><span class="hint">می‌توانید گروه‌های چند حساب را به یک فهرست اضافه کنید.</span></div>
    <div id="group-choices" class="group-choices"></div><div class="form-actions"><button type="submit">شروع جمع‌آوری</button><span class="hint">هیچ پیامی ارسال نمی‌شود.</span></div></form></section>`;
  $('#list_title').focus();
}
function updateHistoryFields() {
  const history=$('#collection_method').value==='history';
  $('#history-options').hidden=!history;
  const limited=history && $('#history_scope').value==='days';
  $('#history_days').disabled=!limited;
  $('#history_days').required=limited;
}
function showImport() {
  formOpen=true;
  $('#list-form').innerHTML=`<section class="panel"><div class="panel-head"><h2>ورود نام‌های کاربری از CSV</h2><button class="quiet" data-action="close-list-form">بستن</button></div><form id="import-form" class="panel-body"><div class="field"><label for="csv_file">فایل CSV با کدگذاری UTF-8</label><input id="csv_file" type="file" accept=".csv,text/csv" required><p class="hint">سطر اول: <bdi class="mono">username</bdi> · هر سطر یک نام کاربری عمومی، با یا بدون @ · حداکثر ۵ مگابایت</p></div><div class="form-actions"><button type="submit">وارد کردن و بررسی</button></div></form></section>`;
}
function renderList() {
  const l=state.lists.find(x=>x.id===selected);if(!l){selected=null;return renderLists();}
  $('#workspace').innerHTML=`<a class="back" href="#lists">بازگشت به فهرست‌ها</a>`+heading(esc(l.title),'اعضای این فهرست را مرور کنید و گیرنده‌های موردنظر را نگه دارید.',`${l.status==='collecting'?`<button class="secondary" data-action="stop-collection" data-id="${l.id}">توقف جمع‌آوری</button>`:`<button data-action="compose-from-list" data-id="${l.id}" ${!l.included||l.status==='failed'?'disabled':''}>ساخت کمپین از این فهرست</button>`}<button class="danger" data-action="list-delete" data-id="${l.id}" ${state.busy?'disabled':''}>حذف فهرست</button>`)+
  `<div id="list-status"></div><section class="panel"><div class="panel-head"><h2>اعضای ذخیره‌شده</h2><input class="search" id="member-search" type="search" aria-label="جست‌وجوی نام یا نام کاربری" placeholder="جست‌وجوی نام یا نام کاربری" value="${esc(search)}"></div><div id="members-table"></div></section>`;
  updateList().catch(e=>notice(e.message,true));
}
async function updateList() {
  const id=selected;if(!id||route!=='lists')return;
  const l=state.lists.find(x=>x.id===id); if(!l)return;
  const out=await api(`/lists/${id}/members?offset=${page*100}&search=${encodeURIComponent(search)}`);
  if(selected!==id || !$('#members-table'))return;
  $('#list-status').innerHTML=`<div class="banner ${l.status==='partial'?'warning':''}"><div>${badge(l.status)} <span>${num(l.included)} گیرنده انتخاب‌شده</span><p class="hint">${esc(collectionSummary(l))}</p><p class="note" dir="auto">${esc(l.note)}</p>${l.status==='partial'?'<p class="hint">این فهرست ممکن است همه اعضای گروه را شامل نشود.</p>':''}</div></div>`;
  $('#members-table').innerHTML=out.rows.length?`<div class="table-wrap"><table><thead><tr><th>انتخاب</th><th>نام</th><th>نام کاربری</th><th>شناسه</th></tr></thead><tbody>${out.rows.map(m=>`<tr><td><input aria-label="انتخاب ${esc(m.name)}" type="checkbox" data-member="${m.id}" ${m.excluded?'':'checked'} ${l.status==='collecting'?'disabled':''}></td><td>${esc(m.name)}</td><td><bdi>${m.username?'@'+esc(m.username):'—'}</bdi></td><td><bdi class="mono">${esc(m.user_id||'—')}</bdi></td></tr>`).join('')}</tbody></table></div>`+pager(out.total):empty('عضوی پیدا نشد',l.status==='collecting'?'جمع‌آوری در حال انجام است؛ نتیجه اینجا نمایش داده می‌شود.':'گروه یا جست‌وجوی دیگری را امتحان کنید.');
}
function renderCampaigns() {
  $('#workspace').innerHTML=heading('کمپین‌ها','از فهرست بررسی‌شده، یک کمپین با گیرنده‌های ثابت بسازید.',`<button data-action="compose" ${!state.lists.some(l=>l.included && ['ready','partial'].includes(l.status))?'disabled':''}>کمپین جدید</button>`)+`<div id="campaign-form"></div><section class="panel"><div class="panel-head"><h2>کمپین‌های شما</h2><span class="hint">شروع فقط با انتخاب شما</span></div><div id="campaigns-table"></div></section>`;updateCampaigns();
}
function updateCampaigns() {
  const el=$('#campaigns-table');if(!el)return;
  el.innerHTML=state.campaigns.length?`<div class="table-wrap"><table><thead><tr><th>کمپین</th><th>پیشرفت</th><th>حساب‌ها</th><th>وضعیت</th><th>عملیات</th></tr></thead><tbody>${state.campaigns.map(c=>{const total=Object.values(c.counts).reduce((a,b)=>a+b,0);return `<tr><td><span class="name">${esc(c.title)}</span><small>${new Date(c.created).toLocaleDateString('fa-IR')}</small></td><td>${num(c.counts.sent)} ارسال از ${num(total)}</td><td>${num(c.account_ids.length)}</td><td>${badge(c.status)}</td><td><button class="quiet" data-action="open-campaign" data-id="${c.id}">مشاهده و مدیریت</button><button class="quiet danger" data-action="campaign-delete" data-id="${c.id}" ${state.busy?'disabled':''}>حذف</button></td></tr>`;}).join('')}</tbody></table></div>`:empty('هنوز کمپینی ساخته نشده','ابتدا یک فهرست اعضا را آماده و بررسی کنید؛ سپس متن و حساب‌های ارسال را انتخاب کنید.',`<a class="button secondary" href="#lists">رفتن به فهرست اعضا</a>`);
}
function showCompose(listId='') {
  formOpen=true;senderOrder=state.accounts.filter(a=>a.status==='connected').map(a=>a.id);
  $('#campaign-form').innerHTML=`<section class="panel"><div class="panel-head"><h2>آماده‌سازی کمپین</h2><button class="quiet" data-action="close-compose">بستن</button></div><form id="compose-form" class="panel-body"><div class="form-grid">${field('نام کمپین','campaign_title','required maxlength="150" placeholder="نام قابل شناسایی برای این ارسال"')}<div class="field"><label for="campaign_list">فهرست اعضا</label><select id="campaign_list" required>${state.lists.filter(l=>l.included && ['ready','partial'].includes(l.status)).map(l=>`<option value="${l.id}" ${l.id===listId?'selected':''}>${esc(l.title)} · ${num(l.included)} نفر${l.status==='partial'?' · ناقص':''}</option>`).join('')}</select></div><div class="field full"><label for="message_text">متن پیام یا زیرنویس عکس</label><textarea id="message_text" dir="auto" maxlength="4096" placeholder="متن پیام خود را بنویسید…"></textarea><span class="hint">متن ساده و پیوند · متن تا ۴۰۹۶، زیرنویس عکس تا ۱۰۲۴ نویسه</span></div><div class="field full"><label for="photo_file">عکس اختیاری</label><input id="photo_file" type="file" accept="image/jpeg,image/png"><span class="hint">یک عکس PNG یا JPEG، حداکثر ۱۰ مگابایت</span></div></div><div class="form-section"><h3>حساب‌های ارسال و ترتیب چرخش</h3><p class="hint">حساب‌های انتخاب‌شده به ترتیب زیر، دسته‌های گیرندگان را دریافت می‌کنند.</p><div id="sender-order" class="account-order"></div></div><div class="form-section"><h3>دسته‌بندی و فاصله ارسال</h3><div class="form-grid">${field('تعداد تلاش در هر دسته','batch_size','type="number" value="10" min="1" max="10000" required')}${field('حداقل فاصله، ثانیه','delay_min','type="number" value="30" min="1" max="86400" required')}${field('حداکثر فاصله، ثانیه','delay_max','type="number" value="60" min="1" max="86400" required')}</div><p class="hint">پس از هر تلاش، یک فاصله تصادفی در این بازه انتخاب می‌شود. در هر لحظه فقط یک صف ارسال فعال است.</p></div><div class="form-actions"><button type="submit">ذخیره و دیدن پیش‌نمایش</button><span class="hint">این دکمه ارسال را آغاز نمی‌کند.</span></div></form></section>`;renderSenders();$('#campaign_title').focus();
}
function renderSenders() {
  const checked=new Set($$('#sender-order input:checked').map(i=>i.value));const initial=!$('#sender-order').children.length;
  $('#sender-order').innerHTML=senderOrder.map((id,i)=>`<div class="account-choice"><label><input type="checkbox" value="${id}" ${initial||checked.has(id)?'checked':''}>${esc(accountName(id))}</label><span class="hint">ترتیب ${num(i+1)}</span><button class="quiet" type="button" data-action="sender-up" data-id="${id}" ${i===0?'disabled':''}>بالاتر</button></div>`).join('')||'<p class="error-text">ابتدا حسابی را متصل کنید.</p>';
}
function renderCampaign() {
  const c=state.campaigns.find(x=>x.id===selected);if(!c){selected=null;return renderCampaigns();}
  $('#workspace').innerHTML=`<a class="back" href="#campaigns">بازگشت به کمپین‌ها</a>`+heading(esc(c.title),'گیرنده‌های این کمپین ثابت‌اند؛ تغییر فهرست اعضا روی این کمپین اثر ندارد.',`<a class="button secondary" href="/api/campaigns/${c.id}/report">دریافت گزارش CSV</a><button class="danger" data-action="campaign-delete" data-id="${c.id}" ${state.busy?'disabled':''}>حذف کمپین</button>`)+
  `<div id="campaign-controls"></div><div class="detail-grid"><section class="panel"><div class="panel-head"><h2>گیرنده‌ها و نتیجه ارسال</h2><span class="hint">ترتیب واقعی صف</span></div><div id="deliveries-table"></div></section><div><section class="panel"><div class="panel-head"><h2>پیش‌نمایش پیام</h2></div><div class="preview"><p class="preview-label">نمای تقریبی پیام خصوصی</p><div class="message" dir="auto">${c.photo_id?`<img src="/api/photos/${c.photo_id}" alt="عکس کمپین">`:''}${esc(c.text)}</div></div><div class="panel-body"><div class="pair"><span>اندازه دسته</span><strong>${num(c.batch_size)} تلاش</strong></div><div class="pair"><span>فاصله تصادفی</span><strong>${num(c.delay_min)} تا ${num(c.delay_max)} ثانیه</strong></div><div class="pair"><span>حساب‌ها</span><strong>${num(c.account_ids.length)}</strong></div></div></section><div id="reassign-box"></div></div></div>`;
  updateCampaign().catch(e=>notice(e.message,true));
}
async function updateCampaign() {
  const id=selected;if(!id||route!=='campaigns')return;
  const out=await api(`/campaigns/${id}?offset=${page*100}`);if(id!==selected||!$('#deliveries-table'))return;
  detailCache=out;const c=out.campaign;const summary=state.campaigns.find(x=>x.id===id);const counts=summary?.counts||{};
  const controlsHTML=`<div class="banner ${c.status==='paused'?'warning':''}"><div>${badge(c.status)}<p class="note">${esc(c.note)}</p>${c.next_attempt_at>Date.now()/1000 && c.status==='running'?`<p class="hint">تلاش بعدی: ${new Date(c.next_attempt_at*1000).toLocaleTimeString('fa-IR')}</p>`:''}<p class="hint">${num(counts.sent)} ارسال‌شده · ${num(counts.pending)} در صف · ${num(counts.skipped)} ردشده · ${num(counts.failed)} ناموفق · ${num(counts.uncertain)} نامشخص</p></div><div class="actions">${c.status==='running'?`<button class="secondary" data-action="pause" data-id="${id}">توقف موقت</button>`:['ready','paused'].includes(c.status)?`<button data-action="start" data-id="${id}" ${state.busy||counts.uncertain?'disabled':''}>${c.status==='paused'?'ادامه ارسال':'شروع ارسال'}</button>`:''}${!['completed','cancelled'].includes(c.status)?`<button class="danger" data-action="cancel" data-id="${id}">لغو کمپین</button>`:''}</div></div>${c.status==='draft'?`<div class="check-review"><label><input type="checkbox" id="reviewed">پیام، گیرنده‌ها، حساب‌های ارسال و تنظیمات این کمپین را بررسی کردم.</label><div class="review-controls"><button id="review-button" data-action="review" data-id="${id}" disabled>تأیید پیش‌نمایش</button><span class="hint">پس از تأیید، دکمه شروع ارسال فعال می‌شود.</span></div></div><br>`:''}`;
  setLiveHTML('#campaign-controls',controlsHTML);
  const deliveriesHTML=`<div class="table-wrap"><table><thead><tr><th>گیرنده</th><th>حساب ارسال</th><th>نتیجه</th><th>جزئیات</th></tr></thead><tbody>${out.rows.map(d=>`<tr><td><span class="name">${esc(d.name)}</span><small><bdi>${d.username?'@'+esc(d.username):esc(d.user_id)}</bdi></small></td><td>${esc(accountName(d.account_id))}</td><td>${badge(d.status)}</td><td>${d.status==='uncertain'?`<div class="actions"><button class="quiet" data-action="resolve" data-id="${d.id}" data-resolution="sent">ارسال شده</button><button class="quiet" data-action="resolve" data-id="${d.id}" data-resolution="pending">تلاش مجدد</button><button class="quiet" data-action="resolve" data-id="${d.id}" data-resolution="skipped">رد کردن</button></div><small class="review-note">قبل از تلاش مجدد، گفت‌وگوی حساب را بررسی کنید.</small>`:`<small class="mono">${esc(d.error|| (d.message_id?'Message #'+d.message_id:'—'))}</small>`}</td></tr>`).join('')}</tbody></table></div>`+pager(out.total);
  setLiveHTML('#deliveries-table',deliveriesHTML);
  if(!$('#reassign-box').innerHTML && ['draft','ready','paused'].includes(c.status))$('#reassign-box').innerHTML=`<section class="panel"><div class="panel-body"><details><summary>تغییر حساب‌های گیرنده‌های باقی‌مانده</summary><form id="reassign-form"><p class="hint">حساب‌ها به ترتیب فهرست حساب‌ها استفاده می‌شوند. پس از تغییر، پیش‌نمایش را دوباره تأیید کنید.</p><div class="checks">${accountChecks(c.account_ids)}</div><div class="form-actions"><button class="secondary" type="submit">بازچینی صف باقی‌مانده</button></div></form></details></div></section>`;
}
function renderActivity() {
  $('#workspace').innerHTML=heading('گزارش فعالیت','برای مشاهده نتیجه هر گیرنده یا دریافت گزارش، کمپین موردنظر را باز کنید.')+`<section class="panel"><div class="panel-head"><h2>تاریخچه کمپین‌ها</h2></div><div id="campaigns-table"></div></section>`;updateCampaigns();
}
async function navigate() {
  const [next,id]=location.hash.slice(1).split('/');route=titles[next]?next:'lists';selected=id||null;page=0;search='';formOpen=false;
  await refresh();render();
}
document.addEventListener('click', async event => {
  const button=event.target.closest('[data-action]');if(!button||button.disabled||actionBusy)return;
  const {action,id}=button.dataset;
  try {
    actionBusy=true;button.disabled=true;
    if(action==='account-form')showLogin();
    else if(action==='account-relogin')showLogin(state.accounts.find(a=>a.id===id));
    else if(action==='close-login'){formOpen=false;$('#account-login').innerHTML='';}
    else if(action==='account-check'){await api(`/accounts/${id}/check`,{});notice('اتصال حساب بررسی شد. این بررسی رفع محدودیت ارسال را تضمین نمی‌کند.');await refresh();updateAccounts();}
    else if(action==='account-delete'){
      const account=state.accounts.find(a=>a.id===id);
      if(!confirm(`حساب «${account?.label||''}» از این برنامه حذف شود؟ نشست محلی پاک می‌شود؛ حساب تلگرام و گزارش‌های قبلی باقی می‌مانند. کمپین‌های ناتمام این حساب به انتخاب حساب جایگزین و تأیید دوباره نیاز خواهند داشت.`))return;
      await api(`/accounts/${id}`,undefined,'DELETE');
      if(authId===id){authId=null;authStep=null;formOpen=false;$('#account-login').innerHTML='';}
      await refresh();updateAccounts();notice('حساب و نشست محلی حذف شدند. کمپین‌های وابسته را پیش از ارسال دوباره بررسی کنید.');
    }
    else if(action==='list-delete'){
      if(!confirm('فهرست و اعضای ذخیره‌شده آن حذف شوند؟ گیرنده‌های کمپین‌هایی که قبلاً ساخته‌اید باقی می‌مانند.'))return;
      await api(`/lists/${id}`,undefined,'DELETE');await refresh();
      if(selected===id){selected=null;location.hash='lists';}else updateLists();
      notice('فهرست حذف شد.');
    }
    else if(action==='campaign-delete'){
      if(!confirm('کمپین، گیرنده‌ها و گزارش ارسال آن برای همیشه حذف شوند؟ پیام‌هایی که قبلاً در تلگرام ارسال شده‌اند حذف نمی‌شوند.'))return;
      const result=await api(`/campaigns/${id}`,undefined,'DELETE');await refresh();
      if(selected===id){selected=null;location.hash='campaigns';}else updateCampaigns();
      notice(result.cleanup_warning||'کمپین و گزارش‌های آن حذف شدند.',!!result.cleanup_warning);
    }
    else if(action==='cleanup-photos'){
      if(!confirm('عکس‌هایی که در هیچ کمپینی استفاده نمی‌شوند، از این رایانه حذف شوند؟'))return;
      const result=await api('/cleanup',{});notice(`${num(result.deleted_photos)} عکس بدون استفاده پاک شد.`);
    }
    else if(action==='collect-form')showCollect();
    else if(action==='import-form')showImport();
    else if(action==='close-list-form'){formOpen=false;$('#list-form').innerHTML='';}
    else if(action==='load-groups'){
      const account=$('#source_account').value;
      const chosen=new Set($$('#group-choices input:checked').map(i=>`${sourceGroups[Number(i.value)].account_id}:${sourceGroups[Number(i.value)].group_id}`));
      const groups=await api(`/accounts/${account}/groups`);
      for(const group of groups)if(!sourceGroups.some(s=>s.account_id===account&&s.group_id===group.id))sourceGroups.push({...group,account_id:account,group_id:group.id});
      $('#group-choices').innerHTML=sourceGroups.map((g,i)=>`<label class="check"><input type="checkbox" value="${i}" ${chosen.has(`${g.account_id}:${g.group_id}`)?'checked':''}>${esc(g.title)}<small>${esc(accountName(g.account_id))} · ${g.count==null?'تعداد نامشخص':num(g.count)}</small></label>`).join('')||'<p class="hint">گروهی پیدا نشد. حساب باید قبلاً عضو گروه باشد.</p>';
    }
    else if(action==='open-list')location.hash='lists/'+id;
    else if(action==='stop-collection'){await api(`/lists/${id}/stop`,{});await refresh();renderList();}
    else if(action==='compose-from-list'){route='campaigns';selected=null;render();showCompose(id);}
    else if(action==='compose')showCompose();
    else if(action==='close-compose'){formOpen=false;$('#campaign-form').innerHTML='';}
    else if(action==='sender-up'){const i=senderOrder.indexOf(id);[senderOrder[i-1],senderOrder[i]]=[senderOrder[i],senderOrder[i-1]];renderSenders();}
    else if(action==='open-campaign')location.hash='campaigns/'+id;
    else if(['review','start','pause','cancel'].includes(action)){
      if(action==='cancel'&&!confirm('کمپین لغو شود؟ پیام‌های ارسال‌شده حذف نمی‌شوند.'))return;
      await api(`/campaigns/${id}/${action}`,{});await refresh();await updateCampaign();
    }
    else if(action==='resolve'){
      if(button.dataset.resolution==='pending'&&!confirm('پس از بررسی گفت‌وگو، این گیرنده دوباره در صف قرار بگیرد؟ ارسال قبلی ممکن است انجام شده باشد.'))return;
      await api(`/campaigns/${selected}/deliveries/${id}/resolve`,{action:button.dataset.resolution});await refresh();await updateCampaign();
    }
    else if(action==='page-prev'||action==='page-next'){page+=action==='page-next'?1:-1;route==='lists'?await updateList():await updateCampaign();}
  }catch(e){notice(e.message,true);}finally{actionBusy=false;if(button.isConnected)button.disabled=false;}
});
document.addEventListener('submit',async event=>{
  event.preventDefault();if(actionBusy)return;
  const form=event.target;const button=$('button[type=submit]',form);if(button)button.disabled=true;actionBusy=true;
  try {
    const data=Object.fromEntries(new FormData(form));
    if(form.id==='credentials-form'){await api('/credentials',{api_id:Number(data.api_id),api_hash:data.api_hash});form.reset();await refresh();renderAccounts();notice('تنظیمات API ذخیره شد.');}
    else if(form.id==='login-form'){
      const out=await api('/accounts/login',data);authId=out.id;
      if(out.step==='done'){formOpen=false;await refresh();renderAccounts();notice('حساب متصل شد.');}else showVerify(out.step);
    }
    else if(form.id==='verify-form'){
      const value=$('#secret').value;$('#secret').value='';
      const out=await api(`/accounts/${authId}/verify`,{[authStep==='password'?'password':'code']:value});
      if(out.step==='done'){formOpen=false;await refresh();renderAccounts();notice('حساب با موفقیت متصل شد.');}else showVerify(out.step);
    }
    else if(form.id==='collect-form'){
      const sources=$$('#group-choices input:checked').map(i=>({account_id:sourceGroups[Number(i.value)].account_id,group_id:Number(sourceGroups[Number(i.value)].group_id)}));
      const method=$('#collection_method').value;
      const days_back=method==='history' && $('#history_scope').value==='days'?Number($('#history_days').value):null;
      const out=await api('/lists/collect',{title:$('#list_title').value,sources,method,days_back});location.hash='lists/'+out.id;
    }
    else if(form.id==='import-form'){
      const body=new FormData();body.append('file',$('#csv_file').files[0]);const out=await api('/lists/import',body);location.hash='lists/'+out.id;
    }
    else if(form.id==='compose-form'){
      const text=$('#message_text').value;const file=$('#photo_file').files[0];let photo_id=null;
      if(!text.trim()&&!file)throw new Error('متن یا عکس پیام را وارد کنید.');
      if(text.length>(file?1024:4096))throw new Error('متن یا زیرنویس بیش از حد طولانی است.');
      if(file){const body=new FormData();body.append('file',file);photo_id=(await api('/photos',body)).id;}
      const out=await api('/campaigns',{title:$('#campaign_title').value,list_id:$('#campaign_list').value,text,photo_id,
        account_ids:$$('#sender-order input:checked').map(i=>i.value),batch_size:Number($('#batch_size').value),delay_min:Number($('#delay_min').value),delay_max:Number($('#delay_max').value)});
      location.hash='campaigns/'+out.id;
    }
    else if(form.id==='reassign-form'){await api(`/campaigns/${selected}/accounts`,{account_ids:$$('input:checked',form).map(i=>i.value)});await refresh();renderCampaign();notice('صف بازچینی شد؛ پیش‌نمایش را دوباره تأیید کنید.');}
  }catch(e){notice(e.message,true);}finally{actionBusy=false;if(button?.isConnected)button.disabled=false;}
});
document.addEventListener('change',async event=>{
  const el=event.target;
  if(el.id==='reviewed')$('#review-button').disabled=!el.checked;
  if(el.id==='collection_method'||el.id==='history_scope')updateHistoryFields();
  if(el.dataset.member){
    try{await api(`/lists/${selected}/members/${el.dataset.member}`,{excluded:!el.checked});await refresh();}
    catch(e){el.checked=!el.checked;notice(e.message,true);}
  }
});
let searchTimer;
document.addEventListener('input',event=>{if(event.target.id==='member-search'){search=event.target.value;page=0;clearTimeout(searchTimer);searchTimer=setTimeout(()=>updateList().catch(e=>notice(e.message,true)),250);}});
window.addEventListener('hashchange',()=>navigate().catch(e=>notice(e.message,true)));
async function poll(){
  if(polling||actionBusy||document.hidden)return;polling=true;
  try{
    const previousListStatus=route==='lists'&&selected?state.lists.find(l=>l.id===selected)?.status:null;
    await refresh();
    const focus=document.activeElement;
    if(route==='lists' && focus?.closest('#members-table'))return;
    if(route==='accounts')updateAccounts();
    else if(route==='lists'){
      if(selected && state.lists.find(l=>l.id===selected)?.status!==previousListStatus)renderList();
      else selected?await updateList():updateLists();
    }
    else if(route==='campaigns')selected?await updateCampaign():updateCampaigns();
    else updateCampaigns();
  }catch(e){notice('ارتباط با برنامه قطع شد؛ پنجره اجرای برنامه را بررسی کنید.',true);}finally{polling=false;}
}
async function init(){try{token=(await api('/bootstrap')).token;await navigate();setInterval(poll,2500);}catch(e){notice(e.message,true);}}
init();
