const CACHE='bizhub-static-v5';
const STATIC=['/static/manifest.webmanifest','/static/uploads/bizhub-app-icon.png','/static/uploads/icon-192.png','/static/uploads/icon-512.png','/static/uploads/icon-512-maskable.png'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(STATIC)).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('push',e=>{const d=e.data?e.data.json():{};e.waitUntil(self.registration.showNotification(d.title||'BizHub notification',{body:d.message||'',data:{link:d.link||'/'},icon:'/static/uploads/bizhub-app-icon.png'}));});
self.addEventListener('notificationclick',e=>{e.notification.close();e.waitUntil(clients.openWindow(e.notification.data.link||'/'));});
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET') return;
  const u=new URL(e.request.url);
  if(u.origin!==location.origin) return;
  if(e.request.mode==='navigate'){
    e.respondWith(fetch(e.request).catch(()=>caches.match('/'))); return;
  }
  if(u.pathname.startsWith('/static/')){
    e.respondWith(caches.match(e.request).then(x=>x||fetch(e.request).then(r=>{const copy=r.clone();caches.open(CACHE).then(c=>c.put(e.request,copy));return r;})));
  }
});
