/* Flight Tracker cloud integration, optional until configured. Supabase REST + Auth. */
(() => {
  'use strict';
  const config = window.FLIGHT_CLOUD_CONFIG || {};
  const enabled = Boolean(config.url && config.anonKey);
  const origin = String(config.url || '').replace(/\/$/, '');
  let session = null;
  let timer = null;
  const $ = id => document.getElementById(id);
  const api = async (path, init = {}) => {
    const headers = {apikey:config.anonKey, Authorization:`Bearer ${session?.access_token || config.anonKey}`, ...init.headers};
    const res = await fetch(`${origin}${path}`, { ...init, headers });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.msg || body.message || body.error_description || body.error || `HTTP ${res.status}`);
    }
    if (res.status === 204) return null;
    return res.json();
  };
  const saved = () => { try { return JSON.parse(sessionStorage.getItem('flight-session') || 'null'); } catch { return null; } };
  const save = value => { session = value; if(value) sessionStorage.setItem('flight-session',JSON.stringify(value)); else sessionStorage.removeItem('flight-session'); };
  async function refreshSession() {
    if (!session) return false;
    if (Date.now() < session.expires_at*1000 - 60000) return true;
    try {
      const d=await api('/auth/v1/token?grant_type=refresh_token',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({refresh_token:session.refresh_token})});
      save({...d,expires_at:Math.floor(Date.now()/1000)+d.expires_in});
      return true;
    } catch { save(null); return false; }
  }
  const fields = ['id','origin','destination','depart_start','depart_end','return_start','return_end','min_stay','max_stay','airlines','cabin','target_price','up_threshold','down_threshold','notify_up','notify_down','enabled'];
  function renderStatus(message) { $('cloudStatus').textContent=message; }
  function initAuthUI() {
    $('cloudPanel').hidden = !enabled;
    $('localBanner').hidden = enabled;
    if (!enabled) return;
    $('cloudLogin').onsubmit = async ev => {
      ev.preventDefault();
      const f = ev.target;
      try {
        const mode = ev.submitter?.value || 'signin';
        const payload={email:f.elements.email.value.trim(),password:f.elements.password.value};
        if(mode==='signup') {
          const redirectTo = new URL('./', window.location.href).href;
          
          await api(
            '/auth/v1/signup?redirect_to=' + encodeURIComponent(redirectTo),
            {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(payload)
            }
          );
        
          renderStatus('已送出註冊，請至 Email 完成驗證後再登入。');
          return;
        }
        const data = await api('/auth/v1/token?grant_type=password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        save({...data,expires_at:Math.floor(Date.now()/1000)+data.expires_in});
        await loadMonitors();
      } catch(e) { renderStatus('登入失敗：'+e.message); }
    };
    $('cloudLogout').onclick = () => {save(null);location.reload();};
    $('cloudSync').onclick = () => loadMonitors().catch(e=>renderStatus(e.message));
    $('pushEnable').onclick = subscribePush;
  }
  async function loadMonitors() {
    if(!await refreshSession()) {renderStatus('請登入後使用雲端監控');return;}
    const ms = await api('/rest/v1/monitors?select=*&order=created_at.desc');
    window.flightUseCloud?.(ms);
    $('cloudLoggedOut').hidden=true;$('cloudLoggedIn').hidden=false;
    renderStatus(`雲端已同步 ${ms.length} 條航線`);
    await loadObservations(ms);
  }
  async function loadObservations(monitors) {
    if (!monitors.length) return;
    const ids=monitors.map(m=>m.id).filter(id=>/^[0-9a-f-]{36}$/i.test(id));
    if (!ids.length)return;
    const rows=await api(`/rest/v1/observations?select=monitor_id,airline,departure,return_date,price,checked_at,booking_url&monitor_id=in.(${ids.join(',')})&order=checked_at.desc&limit=1000`);
    window.flightRenderPrices?.(rows);
  }
  const write = async monitor => {
    if(!await refreshSession())throw Error('登入已過期，請重新登入');
    const userId=session.user.id;
    const data=Object.fromEntries(fields.filter(k=>k in monitor).map(k=>[k,monitor[k]]));
    data.owner_id=userId;
    // insert/merge with ownership enforced by server RLS. Never trust owner_id from imports.
    await api('/rest/v1/monitors?on_conflict=id',{method:'POST',headers:{'Content-Type':'application/json',Prefer:'resolution=merge-duplicates,return=minimal'},body:JSON.stringify(data)});
    await loadMonitors();
  };
  const remove = async id => {
    if(!await refreshSession())throw Error('登入已過期');
    await api(`/rest/v1/monitors?id=eq.${encodeURIComponent(id)}`,{method:'DELETE'});
    await loadMonitors();
  };
  const base64UrlToUint8Array = base64 => {
    const padding='='.repeat((4-base64.length%4)%4);
    const raw=atob((base64+padding).replace(/-/g,'+').replace(/_/g,'/'));
    return Uint8Array.from(raw,c=>c.charCodeAt(0));
  };
  async function subscribePush() {
    try {
      if(!await refreshSession())throw Error('請先登入');
      if(!config.vapidPublicKey)throw Error('尚未設定 VAPID public key');
      if(!('serviceWorker'in navigator)||!('PushManager'in window))throw Error('此裝置或瀏覽器不支援 Web Push');
      const permission=await Notification.requestPermission();
      if(permission!=='granted')throw Error('未授予通知權限。iPhone 需先加入主畫面再開啟 App。');
      const registration=await navigator.serviceWorker.ready;
      let sub=await registration.pushManager.getSubscription();
      if(!sub)sub=await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:base64UrlToUint8Array(config.vapidPublicKey)});
      await api('/rest/v1/push_subscriptions?on_conflict=owner_id,endpoint',{method:'POST',headers:{'Content-Type':'application/json',Prefer:'resolution=merge-duplicates,return=minimal'},body:JSON.stringify({owner_id:session.user.id,endpoint:sub.endpoint,subscription:sub.toJSON()})});
      renderStatus('已註冊裝置推播；實際通知仍取決於排程與成功查價。');
    } catch(e){renderStatus('通知設定失敗：'+e.message);}
  }
  window.flightCloud={enabled,get isLoggedIn(){return Boolean(session)},write,remove,loadMonitors};
  addEventListener('DOMContentLoaded',async()=>{
    initAuthUI();
    if (!enabled) return;
  
    const hash = new URLSearchParams(window.location.hash.slice(1));
  
    if (hash.has('access_token') && hash.has('refresh_token')) {
      const accessToken = hash.get('access_token');
      const refreshToken = hash.get('refresh_token');
      const expiresIn = Number(hash.get('expires_in') || 3600);
  
      // Retrieve authenticated user from Supabase.
      const res = await fetch(`${origin}/auth/v1/user`, {
        headers: {
          apikey: config.anonKey,
          Authorization: `Bearer ${accessToken}`
        }
      });
  
      // Remove credentials from the browser address bar.
      history.replaceState(null, '', location.pathname + location.search);
  
      if (res.ok) {
        const user = await res.json();
        save({
          access_token: accessToken,
          refresh_token: refreshToken,
          expires_at: Math.floor(Date.now() / 1000) + expiresIn,
          user
        });
      }
    
    } else {
      save(saved());
    }

    if (await refreshSession()) {
      await loadMonitors().catch(e =>
        renderStatus('同步失敗：' + e.message)
      );
    }

    timer = setInterval(() => {
      if (session) {
        loadMonitors().catch(() => {});
      }
    }, 5 * 60 * 1000);
  });
})();
