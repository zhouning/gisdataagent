/**
 * Service Worker — Offline mode for GIS Data Agent (v23.0).
 *
 * Caching strategy:
 * - Static assets (JS/CSS/HTML): Cache-first, update in background
 * - Map tiles: Cache-first with network fallback (stale-while-revalidate)
 * - API calls: Network-first with cache fallback
 * - User data files: Cache on first load
 */

const CACHE_NAME = 'gis-agent-v23';
const TILE_CACHE = 'gis-agent-tiles-v23';
const DATA_CACHE = 'gis-agent-data-v23';

// Static assets to precache on install
const PRECACHE_URLS = [
  '/',
  '/index.html',
];

// Tile URL patterns to cache
const TILE_PATTERNS = [
  /tile\.openstreetmap\.org/,
  /webrd0[1-4]\.is\.autonavi\.com/,    // Gaode
  /t[0-7]\.tianditu\.gov\.cn/,          // Tianditu
  /basemaps\.cartocdn\.com/,            // CartoDB
  /server\.arcgisonline\.com/,          // ESRI
];

// Install: precache static assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_URLS).catch(() => {
        // Non-fatal: some assets may not be available during dev
      });
    })
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== CACHE_NAME && k !== TILE_CACHE && k !== DATA_CACHE)
          .map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// Fetch: route requests to appropriate strategy
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Map tiles: cache-first
  if (TILE_PATTERNS.some((p) => p.test(url.hostname))) {
    event.respondWith(tileStrategy(event.request));
    return;
  }

  // User data files: cache on load
  if (url.pathname.startsWith('/api/user/files/')) {
    event.respondWith(dataStrategy(event.request));
    return;
  }

  // API calls: network-first
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // Static assets: cache-first
  if (event.request.destination === 'script' ||
      event.request.destination === 'style' ||
      event.request.destination === 'document') {
    event.respondWith(cacheFirst(event.request));
    return;
  }

  // Default: network
  event.respondWith(fetch(event.request));
});

// Cache-first for static assets
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    return new Response('Offline', { status: 503 });
  }
}

// Cache-first for map tiles (stale-while-revalidate)
async function tileStrategy(request) {
  const cache = await caches.open(TILE_CACHE);
  const cached = await cache.match(request);
  const fetchPromise = fetch(request).then((response) => {
    if (response.ok) {
      cache.put(request, response.clone());
    }
    return response;
  }).catch(() => null);

  return cached || (await fetchPromise) || new Response('', { status: 503 });
}

// Network-first for API calls
async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok && request.method === 'GET') {
      const cache = await caches.open(DATA_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    return cached || new Response(JSON.stringify({ error: 'Offline' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}

// Cache-on-load for user data files
async function dataStrategy(request) {
  const cache = await caches.open(DATA_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    return new Response(JSON.stringify({ error: 'Offline' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}
