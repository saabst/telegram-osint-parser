#!/usr/bin/env python3
"""Собирает все JSON-события из events/ в единый HTML-просмотрщик."""
import os
import json
import glob
from datetime import datetime

EVENTS_DIR = "events"
OUTPUT_FILE = "viewer.html"


def load_all_events():
    events = []
    for path in glob.glob(os.path.join(EVENTS_DIR, "**/*.json"), recursive=True):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                data["_file"] = os.path.basename(path)
                events.append(data)
        except Exception as e:
            print(f"⚠️  Пропущен {path}: {e}")
    return events


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Geo Events Viewer</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
         background: #0f1419; color: #e6e6e6; height: 100vh; display: flex; flex-direction: column; }
  header { background: #1a1f26; padding: 12px 20px; border-bottom: 1px solid #2a3138;
           display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
  header h1 { font-size: 16px; color: #4da3ff; margin-right: 10px; }
  .stats { display: flex; gap: 8px; }
  .stat { background: #232a33; padding: 4px 10px; border-radius: 4px; font-size: 12px; }
  .stat b { color: #4da3ff; }
  .controls { display: flex; gap: 8px; margin-left: auto; flex-wrap: wrap; }
  input, select { background: #232a33; border: 1px solid #2a3138; color: #e6e6e6;
                  padding: 6px 10px; border-radius: 4px; font-size: 13px; }
  input:focus, select:focus { outline: none; border-color: #4da3ff; }
  main { flex: 1; display: flex; overflow: hidden; }
  #list { width: 45%; overflow-y: auto; border-right: 1px solid #2a3138; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  thead { background: #1a1f26; position: sticky; top: 0; z-index: 10; }
  th { padding: 8px; text-align: left; cursor: pointer; user-select: none;
       border-bottom: 2px solid #2a3138; color: #8a94a0; font-weight: 500; }
  th:hover { color: #4da3ff; }
  th.sorted::after { content: " ▼"; color: #4da3ff; }
  th.sorted.asc::after { content: " ▲"; }
  td { padding: 8px; border-bottom: 1px solid #1f252c; vertical-align: top; }
  tr { cursor: pointer; transition: background 0.1s; }
  tr:hover { background: #1a222b; }
  tr.active { background: #1e3a5c; }
  .cat { display: inline-block; padding: 2px 6px; border-radius: 3px;
         font-size: 11px; font-weight: 600; text-transform: uppercase; }
  .cat-прилёты { background: #5c1e1e; color: #ff8080; }
  .cat-перехваты { background: #1e4a5c; color: #80d4ff; }
  .cat-дроны { background: #4a3a1e; color: #ffcc66; }
  .cat-прочее { background: #2a3138; color: #aaa; }
  #map { width: 55%; }
  #details { position: fixed; right: 0; top: 0; bottom: 0; width: 420px;
             background: #1a1f26; border-left: 1px solid #2a3138;
             transform: translateX(100%); transition: transform 0.2s;
             overflow-y: auto; padding: 20px; z-index: 100; }
  #details.open { transform: translateX(0); }
  #details h2 { font-size: 15px; color: #4da3ff; margin-bottom: 12px; }
  #details .close { position: absolute; top: 10px; right: 15px; cursor: pointer;
                    font-size: 20px; color: #888; }
  #details .close:hover { color: #fff; }
  .field { margin-bottom: 12px; }
  .field-label { font-size: 11px; color: #8a94a0; text-transform: uppercase;
                 letter-spacing: 0.5px; margin-bottom: 3px; }
  .field-value { font-size: 13px; line-height: 1.5; word-break: break-word; }
  .full-text { background: #0f1419; padding: 12px; border-radius: 4px;
               font-family: "SF Mono", Consolas, monospace; font-size: 12px;
               white-space: pre-wrap; max-height: 300px; overflow-y: auto; }
  .leaflet-container { background: #0f1419; }
  .marker-popup { font-size: 12px; }
  .marker-popup b { color: #4da3ff; }
  .empty { text-align: center; padding: 40px; color: #666; }
</style>
</head>
<body>
<header>
  <h1>🛰 Geo Events</h1>
  <div class="stats" id="stats"></div>
  <div class="controls">
    <input type="text" id="search" placeholder="🔍 Поиск..." style="width:180px">
    <select id="f-cat"><option value="">Все категории</option></select>
    <select id="f-country"><option value="">Все страны</option></select>
    <select id="f-missile"><option value="">Все типы ракет</option></select>
    <select id="sort">
      <option value="date_desc">Сначала новые</option>
      <option value="date_asc">Сначала старые</option>
      <option value="location">По локации</option>
      <option value="category">По категории</option>
    </select>
  </div>
</header>
<main>
  <div id="list">
    <table>
      <thead><tr>
        <th data-sort="date">Дата</th>
        <th data-sort="category">Категория</th>
        <th data-sort="location">Локация</th>
        <th data-sort="missile">Тип</th>
        <th>Канал</th>
      </tr></thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>
  <div id="map"></div>
</main>

<div id="details">
  <span class="close" onclick="closeDetails()">✕</span>
  <div id="details-content"></div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const DATA = __DATA_PLACEHOLDER__;

const CAT_COLORS = {
  "прилёты": "#ff4444", "перехваты": "#44aaff",
  "дроны": "#ffaa33", "прочее": "#888888"
};

let map, markers = [], currentSort = "date_desc";

function init() {
  map = L.map('map', { worldCopyJump: true }).setView([48.5, 35], 5);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OSM', maxZoom: 18
  }).addTo(map);

  // Заполняем фильтры
  const cats = [...new Set(DATA.map(e => e.category).filter(Boolean))];
  const countries = [...new Set(DATA.map(e => e.geo?.country).filter(Boolean))];
  const missiles = [...new Set(DATA.map(e => e.military?.missile_type).filter(Boolean))];
  fillSelect('f-cat', cats);
  fillSelect('f-country', countries);
  fillSelect('f-missile', missiles);

  // Статистика
  const stats = document.getElementById('stats');
  stats.innerHTML = `<div class="stat">Всего: <b>${DATA.length}</b></div>` +
    cats.map(c => {
      const n = DATA.filter(e => e.category === c).length;
      return `<div class="stat">${c}: <b>${n}</b></div>`;
    }).join('');

  render();

  // Обработчики
  ['search','f-cat','f-country','f-missile','sort'].forEach(id => {
    document.getElementById(id).addEventListener('input', render);
    document.getElementById(id).addEventListener('change', render);
  });

  document.querySelectorAll('th[data-sort]').forEach(th => {
    th.addEventListener('click', () => {
      const field = th.dataset.sort;
      const sel = document.getElementById('sort');
      const cur = sel.value;
      if (cur === field + '_desc') sel.value = field + '_asc';
      else sel.value = field + '_desc';
      render();
    });
  });
}

function fillSelect(id, values) {
  const sel = document.getElementById(id);
  values.forEach(v => {
    const opt = document.createElement('option');
    opt.value = v; opt.textContent = v;
    sel.appendChild(opt);
  });
}

function filter() {
  const q = document.getElementById('search').value.toLowerCase();
  const cat = document.getElementById('f-cat').value;
  const country = document.getElementById('f-country').value;
  const missile = document.getElementById('f-missile').value;

  return DATA.filter(e => {
    if (cat && e.category !== cat) return false;
    if (country && e.geo?.country !== country) return false;
    if (missile && e.military?.missile_type !== missile) return false;
    if (q) {
      const hay = (e.full_text + ' ' + (e.geo?.location_name||'') + ' ' +
                   (e.channel||'')).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

function sort(events) {
  const mode = document.getElementById('sort').value;
  const arr = [...events];
  if (mode === 'date_desc') arr.sort((a,b) => b.date.localeCompare(a.date));
  else if (mode === 'date_asc') arr.sort((a,b) => a.date.localeCompare(b.date));
  else if (mode === 'location') arr.sort((a,b) =>
    (a.geo?.location_name||'zzz').localeCompare(b.geo?.location_name||'zzz'));
  else if (mode === 'category') arr.sort((a,b) =>
    (a.category||'zzz').localeCompare(b.category||'zzz'));
  return arr;
}

function render() {
  const events = sort(filter());
  const tbody = document.getElementById('tbody');
  tbody.innerHTML = '';

  // Чистим маркеры
  markers.forEach(m => map.removeLayer(m));
  markers = [];

  if (events.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty">Ничего не найдено</td></tr>';
    return;
  }

  events.forEach(e => {
    const tr = document.createElement('tr');
    tr.dataset.id = e.id + '_' + e.channel;
    const d = new Date(e.date);
    const dateStr = d.toLocaleString('ru-RU', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
    const loc = e.geo?.location_name || '—';
    const mis = e.military?.missile_type || '—';
    tr.innerHTML = `
      <td>${dateStr}</td>
      <td><span class="cat cat-${e.category||'прочее'}">${e.category||'прочее'}</span></td>
      <td>${loc}</td>
      <td>${mis}</td>
      <td style="color:#8a94a0;font-size:12px">${e.channel||''}</td>
    `;
    tr.addEventListener('click', () => showDetails(e, tr));
    tbody.appendChild(tr);

    // Маркер на карте
    const coords = e.geo?.coordinates;
    if (coords && coords.length > 0) {
      const c = coords[0];
      const color = CAT_COLORS[e.category] || '#888';
      const marker = L.circleMarker([c.lat, c.lon], {
        radius: 7, fillColor: color, color: '#fff', weight: 1,
        opacity: 1, fillOpacity: 0.8
      }).addTo(map);
      marker.bindPopup(`<div class="marker-popup">
        <b>${e.category||'событие'}</b><br>
        ${e.geo?.location_name||''}<br>
        ${e.military?.missile_type||''}<br>
        <small>${dateStr}</small>
      </div>`);
      marker.on('click', () => {
        showDetails(e);
        const row = document.querySelector(`tr[data-id="${CSS.escape(tr.dataset.id)}"]`);
        if (row) row.scrollIntoView({behavior:'smooth', block:'center'});
      });
      marker._eventData = e;
      markers.push(marker);
    }
  });
}

function showDetails(e, rowEl) {
  document.querySelectorAll('tr.active').forEach(r => r.classList.remove('active'));
  if (rowEl) rowEl.classList.add('active');

  const coords = e.geo?.coordinates?.[0];
  const coordStr = coords ? `${coords.lat.toFixed(5)}, ${coords.lon.toFixed(5)}` : '—';
  const mapsLink = coords ?
    `<a href="https://www.google.com/maps?q=${coords.lat},${coords.lon}" target="_blank" style="color:#4da3ff">Открыть в Google Maps ↗</a>` : '';

  const html = `
    <h2>${e.category||'Событие'} · ${e.geo?.location_name||'—'}</h2>
    <div class="field"><div class="field-label">Дата</div>
      <div class="field-value">${new Date(e.date).toLocaleString('ru-RU')}</div></div>
    <div class="field"><div class="field-label">Канал</div>
      <div class="field-value">${e.channel||'—'}</div></div>
    <div class="field"><div class="field-label">Страна</div>
      <div class="field-value">${e.geo?.country||'—'}</div></div>
    <div class="field"><div class="field-label">Локация</div>
      <div class="field-value">${e.geo?.location_name||'—'}</div></div>
    <div class="field"><div class="field-label">Тип ракеты</div>
      <div class="field-value">${e.military?.missile_type||'—'}</div></div>
    <div class="field"><div class="field-label">Координаты</div>
      <div class="field-value">${coordStr}<br>${mapsLink}</div></div>
    ${e.link ? `<div class="field"><div class="field-label">Оригинал</div>
      <div class="field-value"><a href="${e.link}" target="_blank" style="color:#4da3ff">${e.link}</a></div></div>` : ''}
    <div class="field"><div class="field-label">Полный текст поста</div>
      <div class="full-text">${escapeHtml(e.full_text||'')}</div></div>
  `;
  document.getElementById('details-content').innerHTML = html;
  document.getElementById('details').classList.add('open');

  // Центрируем карту
  if (coords) map.flyTo([coords.lat, coords.lon], 10, {duration: 0.5});
}

function closeDetails() {
  document.getElementById('details').classList.remove('open');
  document.querySelectorAll('tr.active').forEach(r => r.classList.remove('active'));
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDetails(); });
init();
</script>
</body>
</html>
"""


def build():
    events = load_all_events()
    print(f"📦 Загружено событий: {len(events)}")

    html = HTML_TEMPLATE.replace("__DATA_PLACEHOLDER__", json.dumps(events, ensure_ascii=False))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ Готово! Открой файл: {os.path.abspath(OUTPUT_FILE)}")


if __name__ == "__main__":
    build()