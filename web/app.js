// GitHub Pages standalone planner. No remote API and no push notifications.
const STORAGE_KEY='flight-tracker-plans-v1';
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let monitors=[],editing=null;
const validCode=s=>/^[A-Z]{3}$/.test(s);
function read(){try{const d=JSON.parse(localStorage.getItem(STORAGE_KEY)||'[]');return Array.isArray(d)?d:[]}catch{return []}}
function persist(){localStorage.setItem(STORAGE_KEY,JSON.stringify(monitors));}
function notice(message){$('message').textContent=message;}
function dateValid(s){return /^\d{4}-\d{2}-\d{2}$/.test(s)&&!Number.isNaN(Date.parse(s+'T00:00:00Z'));}
function validate(m){
 if(!validCode(m.origin)||!validCode(m.destination))throw Error('請輸入 3 碼英文機場代碼，例如 TPE、NRT');
 if(m.origin===m.destination)throw Error('出發機場與目的地不能相同');
 if(!dateValid(m.depart_start)||!dateValid(m.depart_end)||m.depart_start>m.depart_end)throw Error('請確認去程日期區間');
 if(Boolean(m.return_start)!==Boolean(m.return_end))throw Error('回程需同時設定最早及最晚日期');
 if(m.return_start&&(!dateValid(m.return_start)||!dateValid(m.return_end)||m.return_start>m.return_end||m.return_end<m.depart_start))throw Error('請確認回程日期區間');
 if(!Array.isArray(m.airlines)||!m.airlines.length)throw Error('請至少選擇一家航空公司');
 if(m.min_stay!==null&&m.max_stay!==null&&m.min_stay>m.max_stay)throw Error('最少停留天數不能大於最多天數');
 for(const k of ['target_price','up_threshold','down_threshold'])if(m[k]!==null&&(!Number.isFinite(m[k])||m[k]<0))throw Error('票價與門檻不能為負數');
}
function refresh(){
 $('count').textContent=`${monitors.length} 條航線`;
 $('summary').textContent='規劃想去的地方與日期，保留你關注的航線';
 $('monitors').innerHTML=monitors.length?monitors.map(m=>`<article class="card"><div class="pills"><span class="pill">${m.enabled?'已儲存':'暫停'}</span>${m.airlines.map(a=>`<span class="pill">${esc(a)}</span>`).join('')}</div><div class="route">${esc(m.origin)} → ${esc(m.destination)}</div><div class="date">${esc(m.depart_start)} ${m.depart_end!==m.depart_start?'～ '+esc(m.depart_end):''}${m.return_start?' ｜ 回程 '+esc(m.return_start)+(m.return_end!==m.return_start?'～'+esc(m.return_end):''):''}</div><div class="date">${m.target_price!==null?'目標價 NT$'+esc(m.target_price.toLocaleString()):'未設定目標價'} · 尚未連線查價</div><div class="cardfooter"><button class="secondary" data-remove="${esc(m.id)}">刪除</button><button data-edit="${esc(m.id)}">編輯</button></div></article>`).join(''):'<div class="card"><h2>開始規劃第一趟旅程 ✈️</h2><p>新增機場、日期、航空公司與價格目標。資料目前只保存在你的裝置。</p></div>';
}
function edit(m){editing=m?.id||null;$('editorTitle').textContent=m?'編輯航線':'新增航線';const f=$('monitorform');f.reset();const keys=['origin','destination','depart_start','depart_end','return_start','return_end','min_stay','max_stay','cabin','target_price','up_threshold','down_threshold'];if(m){for(const k of keys)f.elements[k].value=m[k]??'';for(const k of ['notify_up','notify_down','enabled'])f.elements[k].checked=m[k];f.querySelectorAll('[name=airlines]').forEach(el=>el.checked=m.airlines.includes(el.value));}else{f.elements.up_threshold.value=500;f.elements.down_threshold.value=500;}$('formerror').textContent='';$('editor').showModal();}
$('add').onclick=()=>edit(null);
$('close').onclick=()=>$('editor').close();
$('monitors').onclick=e=>{const b=e.target.closest('button');if(!b)return;const id=b.dataset.edit||b.dataset.remove,m=monitors.find(x=>x.id===id);if(!m)return;if(b.dataset.edit)edit(m);else if(confirm('刪除這條航線？')){monitors=monitors.filter(x=>x.id!==id);persist();refresh();notice('航線已刪除');}};
$('monitorform').onsubmit=e=>{e.preventDefault();const f=e.target,value=k=>f.elements[k].value,optional=k=>value(k)||null,n=k=>value(k)===''?null:Number(value(k));const data={id:editing||crypto.randomUUID(),origin:value('origin').trim().toUpperCase(),destination:value('destination').trim().toUpperCase(),depart_start:value('depart_start'),depart_end:value('depart_end'),return_start:optional('return_start'),return_end:optional('return_end'),min_stay:n('min_stay'),max_stay:n('max_stay'),airlines:[...f.querySelectorAll('[name=airlines]:checked')].map(x=>x.value),cabin:value('cabin'),target_price:n('target_price'),up_threshold:n('up_threshold'),down_threshold:n('down_threshold'),notify_up:f.elements.notify_up.checked,notify_down:f.elements.notify_down.checked,enabled:f.elements.enabled.checked};try{validate(data);if(editing)monitors=monitors.map(m=>m.id===editing?data:m);else monitors.push(data);persist();$('editor').close();refresh();notice('已儲存在此瀏覽器。提醒：目前沒有自動查價或推播。');}catch(err){$('formerror').textContent=err.message;}};
$('export').onclick=()=>{const blob=new Blob([JSON.stringify({format:'flight-tracker-pages-v1',monitors},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='flight-tracker-backup.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);};
$('import').onclick=()=>$('importfile').click();
$('importfile').onchange=async e=>{const file=e.target.files[0];if(!file)return;try{if(file.size>1024*1024)throw Error('檔案超過 1 MB');const data=JSON.parse(await file.text());if(data.format!=='flight-tracker-pages-v1'||!Array.isArray(data.monitors)||data.monitors.length>300)throw Error('備份檔格式不正確');for(const m of data.monitors){if(!m||typeof m.id!=='string'||m.id.length>120)throw Error('備份資料不完整');validate(m);}if(!confirm('匯入會取代目前所有航線，確定嗎？'))return;monitors=data.monitors;persist();refresh();notice('備份已匯入');}catch(err){notice('匯入失敗：'+err.message);}finally{e.target.value='';}};
monitors=read();refresh();
if('serviceWorker'in navigator)navigator.serviceWorker.register('./service-worker.js').catch(()=>{});
