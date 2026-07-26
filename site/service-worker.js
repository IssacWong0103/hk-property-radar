/* HK Property Radar — network-first so YR always gets the latest data & code when
   online; the cache is only an offline fallback. (A data dashboard values freshness
   over micro-perf.) Cross-origin (Plotly CDN) is left to the browser. */
const CACHE = 'hkpr-v3';
const PRECACHE = ['./', 'index.html', 'icons/icon-192.png', 'icons/icon-512.png', 'icons/icon-180.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  if (new URL(e.request.url).origin !== location.origin) return;   // CDN → browser
  e.respondWith(
    fetch(e.request)
      .then(r => { if (r && r.ok) { const cp = r.clone(); caches.open(CACHE).then(c => c.put(e.request, cp)); } return r; })
      .catch(() => caches.match(e.request).then(r => r || (e.request.mode === 'navigate' ? caches.match('index.html') : undefined)))
  );
});
