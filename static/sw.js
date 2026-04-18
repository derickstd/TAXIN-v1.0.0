/* Taxman256 Service Worker */
const CACHE = 'taxman256-v1';
const STATIC = [
  '/static/css/app.css',
  '/static/js/app.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css',
  'https://cdnjs.cloudflare.com/ajax/libs/jquery/3.7.1/jquery.min.js',
  'https://cdnjs.cloudflare.com/ajax/libs/select2/4.1.0-rc.0/js/select2.min.js',
  'https://cdnjs.cloudflare.com/ajax/libs/select2/4.1.0-rc.0/css/select2.min.css',
  'https://cdnjs.cloudflare.com/ajax/libs/flatpickr/4.6.13/flatpickr.min.js',
  'https://cdnjs.cloudflare.com/ajax/libs/flatpickr/4.6.13/flatpickr.min.css',
];

const OFFLINE_URL = '/offline/';

/* ── Install: pre-cache static assets ── */
self.addEventListener('install', function(e) {
  e.waitUntil(
    caches.open(CACHE).then(function(cache) {
      return cache.addAll(STATIC).catch(function() {});
    }).then(function() {
      return self.skipWaiting();
    })
  );
});

/* ── Activate: clean old caches ── */
self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(
        keys.filter(function(k) { return k !== CACHE; })
            .map(function(k) { return caches.delete(k); })
      );
    }).then(function() {
      return self.clients.claim();
    })
  );
});

/* ── Fetch strategy ── */
self.addEventListener('fetch', function(e) {
  var req = e.request;
  var url = new URL(req.url);

  /* Skip non-GET, chrome-extension, admin */
  if (req.method !== 'GET') return;
  if (url.pathname.startsWith('/admin/')) return;
  if (url.protocol === 'chrome-extension:') return;

  /* Static assets → cache first */
  if (
    url.pathname.startsWith('/static/') ||
    url.hostname.includes('cdnjs.cloudflare.com') ||
    url.hostname.includes('cdn.jsdelivr.net') ||
    url.hostname.includes('fonts.googleapis.com') ||
    url.hostname.includes('fonts.gstatic.com')
  ) {
    e.respondWith(
      caches.match(req).then(function(cached) {
        if (cached) return cached;
        return fetch(req).then(function(res) {
          if (!res || res.status !== 200) return res;
          var clone = res.clone();
          caches.open(CACHE).then(function(c) { c.put(req, clone); });
          return res;
        });
      })
    );
    return;
  }

  /* HTML pages → network first, fall back to offline page */
  if (req.headers.get('accept') && req.headers.get('accept').includes('text/html')) {
    e.respondWith(
      fetch(req).then(function(res) {
        var clone = res.clone();
        caches.open(CACHE).then(function(c) { c.put(req, clone); });
        return res;
      }).catch(function() {
        return caches.match(req).then(function(cached) {
          return cached || caches.match(OFFLINE_URL);
        });
      })
    );
    return;
  }
});
