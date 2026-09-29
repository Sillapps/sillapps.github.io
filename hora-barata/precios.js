/* Hora Barata: precio PVPC de hoy y mañana desde la API pública de Red Eléctrica (REData).
   Sin cookies (credentials: "omit"), sin analítica, sin dependencias. */
(function (root) {
  "use strict";

  var API = "https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real";
  var TZ = "Europe/Madrid";
  var PLAY = "https://play.google.com/store/apps/details?id=com.sillapps.ecoclaimspocket&hl=es";

  function pad(n) {
    return (n < 10 ? "0" : "") + n;
  }

  // Día (AAAA-MM-DD) y hora (0-23) actuales en hora peninsular.
  function madridNow(date) {
    var parts = {};
    new Intl.DateTimeFormat("en-GB", {
      timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", hourCycle: "h23"
    }).formatToParts(date || new Date()).forEach(function (p) { parts[p.type] = p.value; });
    return { day: parts.year + "-" + parts.month + "-" + parts.day, hour: parseInt(parts.hour, 10) % 24 };
  }

  function addDays(day, n) {
    var d = new Date(day + "T12:00:00Z");
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }

  function buildUrl(today) {
    return API + "?start_date=" + today + "T00:00&end_date=" + addDays(today, 1) +
      "T23:59&time_trunc=hour";
  }

  // Devuelve { "AAAA-MM-DD": [{ hour, label, kwh }] } a partir de la serie "PVPC" (€/MWh).
  function parse(json) {
    var included = (json && json.included) || [];
    var series = null;
    for (var i = 0; i < included.length; i++) {
      if (included[i].type === "PVPC" || included[i].id === "1001") { series = included[i]; break; }
    }
    if (!series || !series.attributes || !series.attributes.values) return null;
    var out = {};
    series.attributes.values.forEach(function (v) {
      if (typeof v.value !== "number" || typeof v.datetime !== "string") return;
      var day = v.datetime.slice(0, 10);
      var hour = parseInt(v.datetime.slice(11, 13), 10);
      var list = out[day] || (out[day] = []);
      var label = pad(hour) + ":00";
      // Día del cambio de hora de octubre: la hora 02 aparece dos veces.
      if (list.length && list[list.length - 1].hour === hour) label += " (2)";
      list.push({ hour: hour, label: label, kwh: v.value / 1000 });
    });
    return Object.keys(out).length ? out : null;
  }

  function fmt(kwh) {
    return kwh.toLocaleString("es-ES", { minimumFractionDigits: 3, maximumFractionDigits: 3 });
  }

  // Clasifica cada hora en barata / media / cara por tercios de precio.
  function levels(list) {
    var order = list.map(function (x, i) { return i; })
      .sort(function (a, b) { return list[a].kwh - list[b].kwh; });
    var res = new Array(list.length);
    var third = list.length / 3;
    order.forEach(function (idx, rank) {
      res[idx] = rank < third ? "cheap" : rank < 2 * third ? "mid" : "high";
    });
    return res;
  }

  // Franja de `len` horas seguidas más barata, empezando en `from` o después.
  function bestWindow(list, len, from) {
    var best = -1, bestSum = Infinity;
    for (var s = from || 0; s + len <= list.length; s++) {
      var sum = 0;
      for (var k = 0; k < len; k++) sum += list[s + k].kwh;
      if (sum < bestSum) { bestSum = sum; best = s; }
    }
    return best < 0 ? null : { start: best, avg: bestSum / len };
  }

  function stats(list) {
    var min = 0, max = 0, sum = 0;
    list.forEach(function (x, i) {
      if (x.kwh < list[min].kwh) min = i;
      if (x.kwh > list[max].kwh) max = i;
      sum += x.kwh;
    });
    return { min: min, max: max, avg: sum / list.length };
  }

  function endLabel(list, idx) {
    return pad((list[idx].hour + 1) % 24) + ":00";
  }

  /* ---------- DOM ---------- */

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function fail(box) {
    box.className = "";
    box.textContent = "";
    var p = el("p", "hb-msg", "No hemos podido cargar los precios ahora mismo. ");
    var a = el("a", null, "Consulta los precios en la app");
    a.href = PLAY;
    p.appendChild(a);
    p.appendChild(document.createTextNode(" o vuelve a intentarlo en unos minutos."));
    box.appendChild(p);
  }

  function renderDay(box, list, isToday, nowHour) {
    box.className = "";
    box.textContent = "";
    var st = stats(list);
    var lv = levels(list);
    var max = list[st.max].kwh;

    var sum = el("p", "hb-summary");
    sum.appendChild(el("span", null, "Mín. " + fmt(list[st.min].kwh) + " (" + list[st.min].label + ")"));
    sum.appendChild(el("span", null, "Máx. " + fmt(list[st.max].kwh) + " (" + list[st.max].label + ")"));
    sum.appendChild(el("span", null, "Media " + fmt(st.avg) + " €/kWh"));
    box.appendChild(sum);

    var nowIdx = -1;
    if (isToday) {
      for (var i = 0; i < list.length; i++) if (list[i].hour === nowHour) { nowIdx = i; break; }
    }
    var win = bestWindow(list, 2, isToday && nowIdx >= 0 ? nowIdx : 0);
    var tip = el("p", "hb-tip");
    if (win) {
      tip.textContent = (isToday ? "Lavadora de 2 h, lo más barato que queda hoy: " : "Lavadora de 2 h, lo más barato mañana: ") +
        list[win.start].label + "–" + endLabel(list, win.start + 1) + " (media " + fmt(win.avg) + " €/kWh).";
    } else {
      tip.textContent = "Hoy ya no quedan dos horas seguidas: mira los precios de mañana.";
    }
    box.appendChild(tip);

    var ol = el("ol", "hb-bars");
    list.forEach(function (x, i) {
      var li = el("li", "hb-row hb-" + lv[i] + (i === nowIdx ? " hb-now" : ""));
      li.appendChild(el("span", "hb-h", x.label));
      var track = el("span", "hb-track");
      track.setAttribute("aria-hidden", "true");
      var fill = el("span", "hb-fill");
      fill.style.width = Math.max(4, Math.round((x.kwh / max) * 100)) + "%";
      track.appendChild(fill);
      li.appendChild(track);
      li.appendChild(el("span", "hb-v", fmt(x.kwh)));
      if (i === nowIdx) li.appendChild(el("span", "hb-tag", "ahora"));
      ol.appendChild(li);
    });
    box.appendChild(ol);
  }

  function init() {
    var box = document.getElementById("hb-prices");
    if (!box) return;
    var tabs = document.querySelectorAll("[data-hb-day]");
    var now = madridNow();
    var days = { hoy: now.day, manana: addDays(now.day, 1) };
    var data = null;

    function show(which) {
      for (var i = 0; i < tabs.length; i++) {
        tabs[i].setAttribute("aria-pressed", tabs[i].getAttribute("data-hb-day") === which ? "true" : "false");
      }
      var list = data && data[days[which]];
      if (list && list.length) {
        renderDay(box, list, which === "hoy", madridNow().hour);
      } else if (which === "manana") {
        box.className = "";
        box.textContent = "";
        box.appendChild(el("p", "hb-msg",
          "Los precios de mañana se publican hacia las 20:15 (hora peninsular). Vuelve un poco más tarde."));
      } else {
        fail(box);
      }
    }

    for (var i = 0; i < tabs.length; i++) {
      tabs[i].addEventListener("click", function () { show(this.getAttribute("data-hb-day")); });
    }

    function load(attempt) {
      var ctrl = typeof AbortController === "function" ? new AbortController() : null;
      var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, 10000);
      fetch(buildUrl(now.day), {
        credentials: "omit", referrerPolicy: "no-referrer", cache: "no-store",
        signal: ctrl ? ctrl.signal : undefined
      })
        .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
        .then(function (json) {
          clearTimeout(timer);
          data = parse(json);
          if (!data || !data[days.hoy]) throw new Error("sin datos");
          var tabRow = document.getElementById("hb-tabs");
          if (tabRow) tabRow.hidden = false;
          show("hoy");
        })
        .catch(function () {
          clearTimeout(timer);
          // La API a veces rechaza una petición suelta: un reintento antes de rendirse.
          if (attempt < 2) setTimeout(function () { load(attempt + 1); }, 1500 * attempt);
          else fail(box);
        });
    }
    load(1);
  }

  var api = { madridNow: madridNow, addDays: addDays, buildUrl: buildUrl, parse: parse, fmt: fmt,
    levels: levels, bestWindow: bestWindow, stats: stats };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();
  }
})(this);
