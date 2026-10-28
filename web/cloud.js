
/* Flight Tracker cloud integration — Supabase Auth, REST and Web Push. */
(() => {
  'use strict';

  const config = window.FLIGHT_CLOUD_CONFIG || {};
  const enabled = Boolean(config.url && config.anonKey);
  const origin = String(config.url || '').replace(/\/$/, '');
  const $ = id => document.getElementById(id);
  let session = null;

  function renderStatus(message) {
    const target = $('cloudStatus');
    if (target) target.textContent = message;
  }

  function saved() {
    try {
      return JSON.parse(sessionStorage.getItem('flight-session') || 'null');
    } catch {
      return null;
    }
  }

  function save(value) {
    session = value;
    if (value) {
      sessionStorage.setItem('flight-session', JSON.stringify(value));
    } else {
      sessionStorage.removeItem('flight-session');
    }
  }

  async function api(path, init = {}) {
    const headers = {
      apikey: config.anonKey,
      Authorization: `Bearer ${session?.access_token || config.anonKey}`,
      ...init.headers
    };
    const res = await fetch(`${origin}${path}`, { ...init, headers });

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(
        body.msg || body.message || body.error_description ||
        body.error || `HTTP ${res.status}`
      );
    }

    if (res.status === 204 || res.status === 205) return null;
    const text = await res.text();
    return text ? JSON.parse(text) : null;
  }

  async function refreshSession() {
    if (!session) return false;
    if (
      session.expires_at &&
      Date.now() < session.expires_at * 1000 - 60000
    ) return true;

    try {
      const data = await api('/auth/v1/token?grant_type=refresh_token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          refresh_token: session.refresh_token
        })
      });

      save({
        ...data,
        expires_at: Math.floor(Date.now() / 1000) + data.expires_in
      });
      return true;
    } catch {
      save(null);
      return false;
    }
  }

  const fields = [
    'id', 'origin', 'destination', 'depart_start', 'depart_end',
    'return_start', 'return_end', 'min_stay', 'max_stay', 'airlines',
    'cabin', 'target_price', 'up_threshold', 'down_threshold',
    'notify_up', 'notify_down', 'enabled'
  ];

  async function loadObservations(monitors) {
    if (!monitors.length) {
      window.flightRenderPrices?.([]);
      return;
    }

    const ids = monitors
      .map(m => m.id)
      .filter(id => /^[0-9a-f-]{36}$/i.test(id));

    if (!ids.length) return;

    const rows = await api(
      `/rest/v1/observations?select=monitor_id,airline,departure,return_date,price,checked_at,booking_url&monitor_id=in.(${ids.join(',')})&order=checked_at.desc&limit=1000`
    );

    window.flightRenderPrices?.(rows || []);
  }

  async function loadMonitors() {
    if (!await refreshSession()) {
      renderStatus('請登入後使用雲端監控');
      return;
    }

    const monitors = await api(
      '/rest/v1/monitors?select=*&order=created_at.desc'
    );

    window.flightUseCloud?.(monitors || []);

    if ($('cloudLoggedOut')) $('cloudLoggedOut').hidden = true;
    if ($('cloudLoggedIn')) $('cloudLoggedIn').hidden = false;

    renderStatus(`雲端已同步 ${(monitors || []).length} 條航線`);

    try {
      await loadObservations(monitors || []);
    } catch (error) {
      renderStatus('航線已同步，但票價讀取失敗：' + error.message);
    }
  }

  async function write(monitor) {
    if (!await refreshSession()) {
      throw new Error('登入已過期，請重新登入');
    }

    const data = Object.fromEntries(
      fields.filter(k => k in monitor).map(k => [k, monitor[k]])
    );

    data.owner_id = session.user.id;

    await api('/rest/v1/monitors?on_conflict=id', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Prefer: 'resolution=merge-duplicates,return=minimal'
      },
      body: JSON.stringify(data)
    });

    await loadMonitors();
  }

  async function remove(id) {
    if (!await refreshSession()) {
      throw new Error('登入已過期，請重新登入');
    }

    await api(
      `/rest/v1/monitors?id=eq.${encodeURIComponent(id)}`,
      { method: 'DELETE' }
    );

    await loadMonitors();
  }

  function base64UrlToUint8Array(base64) {
    const padding = '='.repeat((4 - base64.length % 4) % 4);
    const raw = atob(
      (base64 + padding).replace(/-/g, '+').replace(/_/g, '/')
    );
    return Uint8Array.from(raw, c => c.charCodeAt(0));
  }

  async function subscribePush() {
    try {
      if (!await refreshSession()) throw new Error('請先登入');
      if (!config.vapidPublicKey) {
        throw new Error('尚未設定 VAPID public key');
      }

      if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        throw new Error('此裝置或瀏覽器不支援 Web Push');
      }

      const permission = await Notification.requestPermission();

      if (permission !== 'granted') {
        throw new Error(
          '未授予通知權限。iPhone 需先加入主畫面再開啟 App。'
        );
      }

      const registration = await navigator.serviceWorker.ready;
      let subscription = await registration.pushManager.getSubscription();

      if (!subscription) {
        subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: base64UrlToUint8Array(config.vapidPublicKey)
        });
      }

      await api(
        '/rest/v1/push_subscriptions?on_conflict=owner_id,endpoint',
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Prefer: 'resolution=merge-duplicates,return=minimal'
          },
          body: JSON.stringify({
            owner_id: session.user.id,
            endpoint: subscription.endpoint,
            subscription: subscription.toJSON()
          })
        }
      );

      renderStatus(
        '已註冊裝置推播；實際通知仍取決於排程與成功查價。'
      );
    } catch (error) {
      renderStatus('通知設定失敗：' + error.message);
    }
  }

  function initAuthUI() {
    if ($('cloudPanel')) $('cloudPanel').hidden = !enabled;
    if ($('localBanner')) $('localBanner').hidden = enabled;
    if (!enabled) return;

    const login = $('cloudLogin');

    if (login) login.onsubmit = async event => {
      event.preventDefault();
      const form = event.currentTarget;

      try {
        const mode = event.submitter?.value || 'signin';
        const payload = {
          email: form.elements.email.value.trim(),
          password: form.elements.password.value
        };

        if (mode === 'signup') {
          const redirectTo = new URL('./', location.href).href;

          await api(
            '/auth/v1/signup?redirect_to=' + encodeURIComponent(redirectTo),
            {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(payload)
            }
          );

          renderStatus(
            '註冊信已送出，請到 Email 驗證後再登入。'
          );
          return;
        }

        const data = await api(
          '/auth/v1/token?grant_type=password',
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          }
        );

        save({
          ...data,
          expires_at: Math.floor(Date.now() / 1000) + data.expires_in
        });

        await loadMonitors();
      } catch (error) {
        renderStatus('登入／註冊失敗：' + error.message);
      }
    };

    if ($('cloudLogout')) {
      $('cloudLogout').onclick = async () => {
        try {
          if (session?.access_token) {
            await api('/auth/v1/logout', { method: 'POST' });
          }
        } catch {
          // Clear local session even if network logout fails.
        }

        save(null);
        location.reload();
      };
    }

    if ($('cloudSync')) {
      $('cloudSync').onclick = () =>
        loadMonitors().catch(e => renderStatus(e.message));
    }

    if ($('pushEnable')) {
      $('pushEnable').onclick = subscribePush;
    }
  }

  async function acceptAuthRedirect() {
    const hash = new URLSearchParams(location.hash.slice(1));

    if (!hash.has('access_token') || !hash.has('refresh_token')) {
      return false;
    }

    const accessToken = hash.get('access_token');
    const refreshToken = hash.get('refresh_token');
    const expiresIn = Number(hash.get('expires_in') || 3600);

    // Remove credentials immediately from the address bar.
    history.replaceState(
      null,
      '',
      location.pathname + location.search
    );

    const response = await fetch(`${origin}/auth/v1/user`, {
      headers: {
        apikey: config.anonKey,
        Authorization: `Bearer ${accessToken}`
      }
    });

    if (!response.ok) {
      throw new Error(
        '驗證完成，但無法讀取登入帳號，請使用 Email 和密碼登入'
      );
    }

    const user = await response.json();

    save({
      access_token: accessToken,
      refresh_token: refreshToken,
      expires_at:
        Math.floor(Date.now() / 1000) +
        (Number.isFinite(expiresIn) ? expiresIn : 3600),
      user
    });

    return true;
  }

  window.flightCloud = {
    enabled,
    get isLoggedIn() {
      return Boolean(session);
    },
    write,
    remove,
    loadMonitors
  };

  addEventListener('DOMContentLoaded', async () => {
    initAuthUI();
    if (!enabled) return;

    save(saved());

    try {
      await acceptAuthRedirect();

      if (await refreshSession()) {
        await loadMonitors();
      } else {
        renderStatus('請登入後使用雲端監控');
      }
    } catch (error) {
      renderStatus('雲端初始化失敗：' + error.message);
    }

    setInterval(() => {
      if (session) {
        loadMonitors().catch(() => {});
      }
    }, 5 * 60 * 1000);
  });
})();
