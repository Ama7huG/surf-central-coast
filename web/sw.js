// Service worker: makes the site installable and keeps the last forecast for offline use.
// - Page and forecast (index.html, data.js): network first, cached copy when offline.
// - Leaflet, fonts, icons: cache first (they never change).
// - Map tiles are NOT cached here (Esri's terms); the browser's normal HTTP cache still applies.
const CACHE = 'ccsurf-v1';
const SHELL = ['./', 'index.html', 'data.js', 'manifest.json', 'icons/icon-192.png', 'icons/icon-512.png', 'icons/apple-touch-icon.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

const STATIC_HOSTS = ['unpkg.com', 'fonts.googleapis.com', 'fonts.gstatic.com'];

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  if (url.origin === self.location.origin) {
    if (url.pathname.match(/\/icons\//)) {
      e.respondWith(caches.match(req).then(r => r || fetch(req)));
      return;
    }
    // network first, so the forecast is always the newest one available
    e.respondWith(
      fetch(req, {cache: 'no-cache'}).then(res => {
        if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
        return res;
      }).catch(() => caches.match(req, {ignoreSearch: true}).then(r => r || caches.match('index.html')))
    );
    return;
  }

  if (STATIC_HOSTS.includes(url.hostname)) {
    e.respondWith(caches.match(req).then(r => r || fetch(req).then(res => {
      if (res.ok || res.type === 'opaque') { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
      return res;
    })));
  }
  // everything else (map tiles, …): default browser behaviour
});
