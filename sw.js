/* sw.js — Qcom keeps working offline once it has loaded (on a phone in a lift, on a train).
   Network first: an online visit always gets the newest build, and the copy kept here is used only when the network
   fails. Questions to the local server (/api/...) and other sites (fonts) are never cached: they pass straight through.
   Registered by app.js on https and on localhost only; opened from disk, the page runs without it. */
'use strict';
const CACHE = 'qcom-v1';
const SHELL = ['./', './manifest.webmanifest', './icon-192.png', './icon-512.png', './apple-touch-icon.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => null).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || url.pathname.indexOf('/api/') !== -1) return;
  e.respondWith(fetch(req).then(res => {
    if (res && res.ok && res.type === 'basic') {
      const copy = res.clone();
      caches.open(CACHE).then(c => c.put(req, copy)).catch(() => null);
    }
    return res;
  }).catch(() => caches.match(req, {ignoreSearch: true})
    .then(hit => hit || (req.mode === 'navigate' ? caches.match('./') : null))
    .then(hit => hit || Response.error())));
});
