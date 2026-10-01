// Today's choghadiya: rendering only. Every time comes from today.js, the Shubh Samay app's
// own calculation compiled from Dart (globalThis.shubhSamay, see the app repo's
// tool/web/today_api.dart). Nothing is sent anywhere; the chosen place is kept in this
// browser's localStorage only.
(() => {
  'use strict';

  const STORE = 'shubhSamay.today.place';
  const $ = (id) => document.getElementById(id);
  const app = $('today-app');

  // ------------------------------------------------------------ words (the app's English strings, lib/l10n/app_en.arb)
  const NAME = { amrit: 'Amrit', shubh: 'Shubh', labh: 'Labh', char: 'Char', rog: 'Rog', kaal: 'Kaal', udveg: 'Udveg' };
  const QUALITY = { good: 'Auspicious', neutral: 'Neutral', bad: 'Inauspicious' };
  const MARKER = { vaarVela: 'Vaar Vela', kaalVela: 'Kaal Vela', kaalRatri: 'Kaal Ratri' };
  const KAAL = { rahu: 'Rahu Kaal', yamaganda: 'Yamaganda', gulika: 'Gulika Kaal' };
  const AVOID = 'Traditionally avoided for new work';
  const TITHI = [
    'Pratipada', 'Dwitiya', 'Tritiya', 'Chaturthi', 'Panchami', 'Shashthi', 'Saptami', 'Ashtami',
    'Navami', 'Dashami', 'Ekadashi', 'Dwadashi', 'Trayodashi', 'Chaturdashi',
  ];
  const MASA = {
    chaitra: 'Chaitra', vaishakha: 'Vaishakha', jyeshtha: 'Jyeshtha', ashadha: 'Ashadha', shravana: 'Shravana',
    bhadrapada: 'Bhadrapada', ashwin: 'Ashwin', kartika: 'Kartika', margashirsha: 'Margashirsha',
    pausha: 'Pausha', magha: 'Magha', phalguna: 'Phalguna',
  };

  // ------------------------------------------------------------ local usage: 12 h or 24 h, date order
  const lang = navigator.language || 'en-IN';
  let use24h = false;
  try {
    const o = new Intl.DateTimeFormat(lang, { hour: 'numeric' }).resolvedOptions();
    use24h = o.hourCycle ? o.hourCycle === 'h23' || o.hourCycle === 'h24' : o.hour12 === false;
  } catch (_) {
    // 12 h, the app's default.
  }
  // As the app: the US order only for US English, else "Wednesday, 30 September 2026".
  const dateLocale = /-US$/i.test(lang) ? 'en-US' : 'en-IN';
  const browserTz = (() => {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
    } catch (_) {
      return null;
    }
  })();

  const pad = (n) => String(n).padStart(2, '0');
  const time = (t) => (use24h ? `${pad(t.h)}:${pad(t.m)}` : `${t.h % 12 || 12}:${pad(t.m)} ${t.h < 12 ? 'AM' : 'PM'}`);

  function el(tag, cls, ...children) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    for (const c of children) if (c != null && c !== false) e.append(c);
    return e;
  }

  /** "6:31 AM", with a small +1 for a time after midnight (the app's nextDayShort). */
  function timeNode(t) {
    const s = el('span', null, time(t));
    if (t.d > 0) s.append(el('span', 'tc-plus', `+${t.d}`));
    if (t.d < 0) s.append(el('span', 'tc-plus', `${t.d}`));
    return s;
  }

  /** "11:12 PM – 12:43 AM +1": the day mark only once, after the end. */
  function rangeNode(span) {
    const start = span.start.d === span.end.d ? { ...span.start, d: 0 } : span.start;
    return el('span', null, timeNode(start), ' – ', timeNode(span.end));
  }

  function longDate(key) {
    const [y, m, d] = key.split('-').map(Number);
    try {
      return new Intl.DateTimeFormat(dateLocale, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }).format(Date.UTC(y, m - 1, d));
    } catch (_) {
      return key;
    }
  }

  function addDays(key, n) {
    const [y, m, d] = key.split('-').map(Number);
    const x = new Date(Date.UTC(y, m - 1, d + n));
    return `${x.getUTCFullYear()}-${pad(x.getUTCMonth() + 1)}-${pad(x.getUTCDate())}`;
  }

  function zoneLabel(tz) {
    try {
      const p = new Intl.DateTimeFormat('en-US', { timeZone: tz, timeZoneName: 'long' }).formatToParts(Date.now());
      return p.find((x) => x.type === 'timeZoneName')?.value || tz;
    } catch (_) {
      return tz;
    }
  }

  const coordinates = (lat, lon) =>
    `${Math.abs(lat).toFixed(2)}° ${lat >= 0 ? 'N' : 'S'}, ${Math.abs(lon).toFixed(2)}° ${lon >= 0 ? 'E' : 'W'}`;

  function tithiName(n) {
    if (n === 15) return 'Purnima';
    if (n === 30) return 'Amavasya';
    return `${n <= 15 ? 'Shukla' : 'Krishna'} ${TITHI[(n - 1) % 15]}`;
  }

  function leftText(ms) {
    const m = Math.ceil(ms / 60000);
    return m < 60 ? `${m} min left` : `${Math.floor(m / 60)} h ${m % 60} min left`;
  }

  // ------------------------------------------------------------ the calculation
  function api(req) {
    const r = JSON.parse(globalThis.shubhSamay(JSON.stringify(req)));
    if (r && r.error) throw new Error(r.error);
    return r;
  }

  function start() {
    if (typeof globalThis.shubhSamay !== 'function') {
      app.replaceChildren(el('p', 'notice-card', 'The calculation could not load. Please reload the page.'));
      return;
    }
    const cities = api({ op: 'cities' });
    const byId = new Map(cities.map((c) => [c.id, c]));

    // -------------------------------------------------- place: saved, else from the browser's time zone
    const store = {
      get() {
        try {
          return JSON.parse(localStorage.getItem(STORE) || 'null');
        } catch (_) {
          return null;
        }
      },
      set(p) {
        try {
          localStorage.setItem(STORE, JSON.stringify(p));
        } catch (_) {
          // Private mode: not remembered.
        }
      },
    };

    function defaultPlace() {
      const tz = browserTz === 'Asia/Calcutta' ? 'Asia/Kolkata' : browserTz;
      const city = cities.find((c) => c.tz === tz) || byId.get('ahmedabad') || cities[0];
      return { kind: 'city', id: city.id };
    }

    function validPlace(p) {
      if (!p || typeof p !== 'object') return false;
      if (p.kind === 'city') return byId.has(p.id);
      return p.kind === 'gps' && Number.isFinite(p.lat) && Number.isFinite(p.lon) && typeof p.tz === 'string';
    }

    let place = store.get();
    if (!validPlace(place)) place = defaultPlace();

    const where = () => (place.kind === 'city' ? byId.get(place.id) : place);

    // -------------------------------------------------- date: today (the panchang day running now), tomorrow, or picked
    let mode = 'today';
    let picked = null;
    const dateInput = $('date-input');
    const chips = document.querySelectorAll('.tc-chip');

    function setMode(m, key) {
      mode = m;
      picked = key || null;
      render();
    }

    chips.forEach((b) => b.addEventListener('click', () => setMode(b.dataset.day)));
    dateInput.addEventListener('change', () => {
      if (/^\d{4}-\d{2}-\d{2}$/.test(dateInput.value)) setMode('pick', dateInput.value);
    });

    // -------------------------------------------------- render
    function renderPlace() {
      const p = where();
      const name = p.name || 'Your location';
      $('place-name').textContent = name;
      const detail = place.kind === 'gps' ? [p.name && 'Your location', coordinates(p.lat, p.lon)] : [p.region];
      detail.push(zoneLabel(p.tz));
      $('place-detail').textContent = detail.filter(Boolean).join(' · ');
    }

    function slotRow(s, now) {
      const isNow = now && now.date === s.date && now.current.night === s.night && now.current.index === s.index;
      const note = [QUALITY[s.q], s.marker && MARKER[s.marker]].filter(Boolean).join(' · ');
      const li = el(
        'li',
        `q-${s.q}${isNow ? ' is-now' : ''}`,
        el(
          'span',
          'tc-label',
          el('span', `tc-dot ${s.q}`),
          el('span', null, el('span', 'tc-name', NAME[s.c], isNow && el('span', 'tc-now-tag', 'Now')), el('span', `tc-note${s.marker ? ' is-bad' : ''}`, note)),
        ),
        el('span', 'tc-time', rangeNode(s)),
      );
      return li;
    }

    function timingRow(label, span, dot, extra, nowMs) {
      if (!span) return el('li', null, el('span', 'tc-label', el('span', `tc-dot ${dot}`), el('span', 'tc-name', label)), el('span', 'tc-time', extra));
      const running = nowMs >= span.start.t && nowMs < span.end.t;
      const q = dot === 'kaal' ? 'q-bad' : 'q-good';
      return el(
        'li',
        `${q}${dot === 'kaal' ? ' is-kaal' : ''}${running ? ' is-now' : ''}`,
        el('span', 'tc-label', el('span', `tc-dot ${dot}`), el('span', 'tc-name', label, running && el('span', 'tc-now-tag', 'Now'))),
        el('span', 'tc-time', rangeNode(span)),
      );
    }

    function nowCard(now, nowMs, placeName) {
      const s = now.current;
      const card = el('section', `tc-card tc-now q-${s.q}`);
      card.setAttribute('aria-label', 'Now');
      card.append(
        el('div', 'tc-now-top', el('span', 'tc-pulse'), `Now · ${s.night ? 'Night' : 'Day'}`, el('span', 'tc-quality', QUALITY[s.q])),
        el('p', 'tc-now-name', NAME[s.c]),
      );
      if (s.marker) card.append(el('p', 'tc-now-marker', `${MARKER[s.marker]} · ${AVOID}`));
      card.append(el('p', 'tc-now-left', leftText(s.end.t - nowMs), el('span', null, '  ·  ends at ', time(s.end))));
      const lines = el('ul', 'tc-lines');
      if (now.kaal) {
        const li = el('li', null, `${KAAL[now.kaal.kind]} now, until ${time(now.kaal.end)}`);
        li.style.setProperty('--c', 'var(--bad)');
        lines.append(li);
      }
      if (now.nextGood) {
        const g = now.nextGood;
        const li = el('li', null, `Next auspicious: ${NAME[g.c]} at ${time(g.start)}${g.start.d > 0 ? ' (tomorrow)' : ''}`);
        li.style.setProperty('--c', 'var(--good)');
        lines.append(li);
      }
      if (!now.kaal && now.nextRahu) {
        const r = now.nextRahu;
        lines.append(el('li', null, `Next Rahu Kaal: ${time(r.start)} – ${time(r.end)}${r.start.d > 0 ? ' (tomorrow)' : ''}`));
      }
      if (lines.childElementCount) card.append(lines);
      card.append(el('p', 'tc-hint', `${time(now.at)} now in ${placeName}`));
      card.lastChild.style.margin = '10px 0 0';
      return card;
    }

    let lastMinute = -1;

    function render() {
      const nowMs = Date.now();
      lastMinute = Math.floor(nowMs / 60000);
      renderPlace();
      const p = where();
      const base = { op: 'day', lat: p.lat, lon: p.lon, tz: p.tz, now: nowMs };
      let day;
      try {
        const today = api(base);
        if (mode === 'today') day = today;
        else if (mode === 'tomorrow') day = api({ ...base, date: addDays(today.today, 1) });
        else day = api({ ...base, date: picked });
        renderDay(day, today, nowMs, p);
      } catch (e) {
        app.replaceChildren(el('div', 'notice-card', el('p', null, 'These timings could not be calculated for this place. Please pick a city from the list.')));
        return;
      }
    }

    function renderDay(day, today, nowMs, p) {
      chips.forEach((b) => {
        const on = (b.dataset.day === 'today' && day.date === today.today) || (b.dataset.day === 'tomorrow' && day.date === addDays(today.today, 1));
        b.setAttribute('aria-pressed', String(on));
      });
      dateInput.value = day.date;
      dateInput.classList.toggle('is-picked', day.date !== today.today && day.date !== addDays(today.today, 1));

      const out = [];
      const placeName = p.name || 'your location';
      if (day.now) out.push(nowCard(day.now, nowMs, placeName));

      // Date, sun and lunar day.
      const head = el('section', 'tc-card');
      const isToday = day.date === today.today;
      head.append(el('h2', 'tc-day-title', longDate(day.date)));
      head.append(el('p', 'tc-day-sub', `${isToday ? 'Today' : day.date === addDays(today.today, 1) ? 'Tomorrow' : 'Panchang day'} in ${placeName}, sunrise to next sunrise`));
      if (!day.valid) {
        head.append(el('p', 'tc-error', 'The Sun does not rise or set here on this date: no choghadiya can be given.'));
        out.push(head);
        app.replaceChildren(...out);
        return;
      }
      const lunar = day.lunar;
      if (lunar) {
        const first = lunar.tithis[0];
        const parts = [`until ${time(first.end)}${first.end.d > 0 ? ` +${first.end.d}` : ''}`];
        if (lunar.kshaya) parts.push(`then ${tithiName(lunar.kshaya.number)} until ${time(lunar.kshaya.end)}${lunar.kshaya.end.d > 0 ? ` +${lunar.kshaya.end.d}` : ''}`);
        else if (lunar.tithis[1]) parts.push(`then ${tithiName(lunar.tithis[1].number)}`);
        const month = `${lunar.amanta.adhik ? 'Adhik ' : ''}${MASA[lunar.amanta.masa]}`;
        head.append(
          el('p', 'tc-tithi', 'Tithi: ', el('strong', null, tithiName(first.number)), ` ${parts.join(' · ')}`),
          el('p', 'tc-day-sub', `${month} · Vikram Samvat ${lunar.vikramSamvat}`),
        );
      }
      const rows = el('ul', 'tc-rows');
      rows.style.marginTop = '12px';
      rows.append(
        timingRow('Sunrise', { start: day.sunrise, end: day.sunrise }, 'sun', null, -1),
        timingRow('Sunset', { start: day.sunset, end: day.sunset }, 'sun', null, -1),
        timingRow(KAAL.rahu, day.rahu, 'kaal', null, nowMs),
        timingRow(KAAL.yamaganda, day.yamaganda, 'kaal', null, nowMs),
        timingRow(KAAL.gulika, day.gulika, 'kaal', null, nowMs),
        timingRow('Abhijit Muhurat', day.abhijit, 'muhurat', 'Not observed on Wednesdays', nowMs),
        timingRow('Brahma Muhurat', day.brahma, 'muhurat', null, nowMs),
      );
      // Sunrise and sunset are instants, not spans.
      rows.children[0].lastChild.replaceChildren(timeNode(day.sunrise));
      rows.children[1].lastChild.replaceChildren(timeNode(day.sunset));
      head.append(rows);
      out.push(head);

      const lists = el('div', 'tc-grid two');
      for (const [title, hint, slots] of [
        ['Day Choghadiya', 'Sunrise to sunset, in 8 equal parts', day.day],
        ['Night Choghadiya', 'Sunset to next sunrise, in 8 equal parts', day.night],
      ]) {
        const card = el('section', 'tc-card', el('h2', null, title), el('p', 'tc-hint', hint));
        const list = el('ul', 'tc-rows');
        for (const s of slots) list.append(slotRow(s, day.now));
        card.append(list);
        lists.append(card);
      }
      out.push(lists);
      app.replaceChildren(...out);
    }

    // -------------------------------------------------- city picker (the app's search: English, Hindi, Gujarati, old names)
    const picker = $('city-picker');
    const search = $('city-search');
    const results = $('city-results');
    const changeBtn = $('change-city');

    function choose(p) {
      place = p;
      store.set(place);
      picker.hidden = true;
      changeBtn.setAttribute('aria-expanded', 'false');
      render();
    }

    function listCities() {
      const ids = api({ op: 'search', q: search.value });
      results.replaceChildren(
        ...ids.map((id) => {
          const c = byId.get(id);
          const b = el('button', null, el('strong', null, c.name), el('span', null, c.region));
          b.type = 'button';
          b.addEventListener('click', () => choose({ kind: 'city', id }));
          return el('li', null, b);
        }),
      );
      if (!ids.length) results.append(el('li', 'tc-status', 'No city found. Try “Use my location”.'));
    }

    changeBtn.addEventListener('click', () => {
      picker.hidden = !picker.hidden;
      changeBtn.setAttribute('aria-expanded', String(!picker.hidden));
      if (!picker.hidden) {
        search.value = '';
        listCities();
        search.focus();
      }
    });
    search.addEventListener('input', listCities);
    search.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        results.querySelector('button')?.click();
      } else if (e.key === 'Escape') {
        picker.hidden = true;
        changeBtn.setAttribute('aria-expanded', 'false');
        changeBtn.focus();
      }
    });

    // -------------------------------------------------- my location: asked only on tap, never sent
    const status = $('locate-status');
    const say = (msg) => {
      status.hidden = !msg;
      status.textContent = msg || '';
    };
    $('use-location').addEventListener('click', () => {
      if (!navigator.geolocation) return say('This browser cannot share its location. Pick your city instead.');
      say('Finding your position…');
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          // Coarse, like the app (about 1 km): enough for sunrise and sunset to the minute.
          const lat = Math.round(pos.coords.latitude * 100) / 100;
          const lon = Math.round(pos.coords.longitude * 100) / 100;
          try {
            const loc = api({ op: 'locate', lat, lon, tz: browserTz, offset: -new Date().getTimezoneOffset() });
            say('');
            choose({ kind: 'gps', lat, lon, tz: loc.tz, name: loc.name, region: loc.region });
          } catch (_) {
            say('Your position could not be used. Pick your city instead.');
          }
        },
        (err) =>
          say(
            err.code === 1
              ? 'Location permission was refused. Pick your city instead.'
              : 'Your position is not available right now. Pick your city instead.',
          ),
        { enableHighAccuracy: false, timeout: 20000, maximumAge: 600000 },
      );
    });

    // -------------------------------------------------- live: once a minute, and when the tab comes back
    render();
    setInterval(() => {
      if (Math.floor(Date.now() / 60000) !== lastMinute) render();
    }, 5000);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') render();
    });
  }

  if (typeof globalThis.shubhSamay === 'function') start();
  else window.addEventListener('load', start);
})();
