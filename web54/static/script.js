/* ============================================================
   «Солигорск» v3 — клиентский JS (vanilla, без зависимостей).
   Подключён в <head> без defer: тема применяется до отрисовки.
   ============================================================ */
(function () {
  'use strict';

  var rootEl = document.documentElement;
  var THEME_KEY = 'soligorsk-theme';

  /* ---------- Тема ---------- */
  function systemDark() {
    return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
  }
  function storedTheme() {
    try {
      var v = localStorage.getItem(THEME_KEY);
      return (v === 'light' || v === 'dark') ? v : null;
    } catch (e) { return null; }
  }
  var theme = storedTheme() || (systemDark() ? 'dark' : 'light');
  if (theme === 'dark') rootEl.setAttribute('data-theme', 'dark');

  function onReady(fn) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn);
    } else { fn(); }
  }

  onReady(function () {
    initThemeToggle();
    initPasswordToggle();
    initConfirmations();
    initTableFilters();
    initSorting();
    initCharts();
    initCharCounters();
    initSlashFocus();
    initCopyButtons();
    initChartLightbox();
    initDataExtremes();
    initOmCurrent();
  });

  function initThemeToggle() {
    var btn = document.getElementById('theme-toggle');
    if (!btn) return;
    btn.addEventListener('click', function () {
      var dark = rootEl.getAttribute('data-theme') === 'dark';
      if (dark) { rootEl.removeAttribute('data-theme'); }
      else { rootEl.setAttribute('data-theme', 'dark'); }
      try { localStorage.setItem(THEME_KEY, dark ? 'light' : 'dark'); } catch (e) {}
    });
  }

  function initPasswordToggle() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-toggle-password]'), function (btn) {
      btn.addEventListener('click', function () {
        var wrap = btn.closest('.password-wrap');
        var input = wrap ? wrap.querySelector('input') : null;
        if (!input) return;
        var show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        wrap.classList.toggle('pw-visible', show);
        btn.setAttribute('aria-label', show ? 'Скрыть пароль' : 'Показать пароль');
      });
    });
  }

  /* ---------- Копирование (кнопки data-copy) ---------- */
  function initCopyButtons() {
    document.addEventListener('click', function (e) {
      var btn = e.target.closest ? e.target.closest('[data-copy]') : null;
      if (!btn) return;
      e.preventDefault();
      var text = btn.getAttribute('data-copy');
      function done() {
        btn.classList.add('copied');
        var old = btn.getAttribute('title');
        btn.setAttribute('title', 'Скопировано: ' + text);
        setTimeout(function () { btn.classList.remove('copied'); btn.setAttribute('title', old); }, 1200);
      }
      function fallback() {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); } catch (err) {}
        ta.remove();
        done();
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, fallback);
      } else { fallback(); }
    });
  }

  /* ---------- Lightbox графиков ---------- */
  function initChartLightbox() {
    var box = document.getElementById('charts');
    if (!box) return;
    var overlay = null;
    function close() {
      if (overlay) { overlay.remove(); overlay = null; }
      document.removeEventListener('keydown', onKey);
    }
    function onKey(e) { if (e.key === 'Escape') close(); }
    box.addEventListener('click', function (e) {
      var img = e.target.closest ? e.target.closest('.chart img') : null;
      if (!img) return;
      overlay = document.createElement('div');
      overlay.className = 'lightbox';
      var big = document.createElement('img');
      big.src = img.src;
      big.alt = img.alt;
      var cap = document.createElement('div');
      cap.className = 'lightbox-cap';
      var fig = img.closest('figure');
      var capEl = fig ? fig.querySelector('figcaption') : null;
      cap.textContent = capEl ? capEl.textContent : '';
      overlay.appendChild(big);
      if (cap.textContent) overlay.appendChild(cap);
      overlay.addEventListener('click', close);
      document.body.appendChild(overlay);
      document.addEventListener('keydown', onKey);
    });
  }

  /* ---------- Модальные подтверждения ---------- */
  var modalBackdrop = null, modalText = null, modalYes = null, modalNo = null;
  var modalCb = null, lastFocus = null, approvedForm = null;

  function ensureModal() {
    if (modalBackdrop) return;
    modalBackdrop = document.createElement('div');
    modalBackdrop.className = 'modal-backdrop';
    modalBackdrop.hidden = true;
    modalBackdrop.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">' +
        '<h3 class="modal-title" id="modal-title">Подтверждение</h3>' +
        '<p class="modal-text"></p>' +
        '<div class="modal-actions">' +
          '<button type="button" class="btn modal-no">Отмена</button>' +
          '<button type="button" class="btn btn-danger modal-yes">Подтвердить</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(modalBackdrop);
    modalText = modalBackdrop.querySelector('.modal-text');
    modalNo = modalBackdrop.querySelector('.modal-no');
    modalYes = modalBackdrop.querySelector('.modal-yes');
    modalNo.addEventListener('click', closeModal);
    modalYes.addEventListener('click', function () {
      var cb = modalCb;
      closeModal();
      if (cb) cb();
    });
    modalBackdrop.addEventListener('mousedown', function (e) {
      if (e.target === modalBackdrop) closeModal();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && modalBackdrop && !modalBackdrop.hidden) closeModal();
    });
  }

  function openConfirm(text, cb) {
    ensureModal();
    modalText.textContent = text;
    modalCb = cb;
    lastFocus = document.activeElement;
    modalBackdrop.hidden = false;
    document.body.classList.add('modal-open');
    modalNo.focus();
  }

  function closeModal() {
    if (!modalBackdrop) return;
    modalBackdrop.hidden = true;
    document.body.classList.remove('modal-open');
    modalCb = null;
    if (lastFocus && typeof lastFocus.focus === 'function') lastFocus.focus();
  }

  function initConfirmations() {
    document.addEventListener('submit', function (e) {
      var form = e.target;
      if (!form || !form.getAttribute) return;
      var msg = form.getAttribute('data-confirm');
      if (!msg) return;
      if (approvedForm === form) { approvedForm = null; return; }
      e.preventDefault();
      openConfirm(msg, function () {
        approvedForm = form;
        try {
          if (typeof form.requestSubmit === 'function') { form.requestSubmit(); }
          else { form.submit(); }
        } catch (err) { form.submit(); }
        setTimeout(function () { if (approvedForm === form) approvedForm = null; }, 0);
      });
    });
    document.addEventListener('click', function (e) {
      var t = e.target;
      var link = (t && t.closest) ? t.closest('a[data-confirm]') : null;
      if (!link) return;
      e.preventDefault();
      openConfirm(link.getAttribute('data-confirm'), function () {
        window.location.href = link.href;
      });
    });
  }

  /* ---------- Живой фильтр + чипы ---------- */
  function initTableFilters() {
    var state = {};

    function getState(id) {
      if (!state[id]) state[id] = { q: '', cat: 'all' };
      return state[id];
    }
    function realRows(tbody) {
      return Array.prototype.filter.call(tbody.querySelectorAll('tr'), function (tr) {
        return !tr.classList.contains('filter-empty') && !tr.classList.contains('empty-row');
      });
    }
    function rowSearchText(tr) {
      if (tr._searchText == null) {
        var parts = [];
        Array.prototype.forEach.call(tr.children, function (cell) {
          if (!cell.classList.contains('no-filter')) parts.push(cell.textContent);
        });
        tr._searchText = parts.join(' ').replace(/\s+/g, ' ').trim().toLowerCase();
      }
      return tr._searchText;
    }
    function apply(id) {
      var tbody = document.getElementById(id);
      if (!tbody) return;
      var st = getState(id);
      var rows = realRows(tbody);
      var shown = 0;
      rows.forEach(function (tr) {
        var okQ = !st.q || rowSearchText(tr).indexOf(st.q) !== -1;
        var okC = st.cat === 'all' || tr.getAttribute('data-cat') === st.cat;
        var vis = okQ && okC;
        tr.hidden = !vis;
        if (vis) shown++;
      });
      var emptyRow = tbody.querySelector('.filter-empty');
      if (emptyRow) emptyRow.hidden = !(rows.length > 0 && shown === 0);
      var counter = document.querySelector('[data-filter-count="' + id + '"]');
      if (counter) {
        var filtered = !!(st.q || st.cat !== 'all');
        counter.textContent = filtered
          ? ('показано ' + shown + ' из ' + rows.length)
          : ('всего ' + rows.length);
      }
      document.dispatchEvent(new Event('table:refresh'));
    }

    Array.prototype.forEach.call(document.querySelectorAll('[data-filter-for]'), function (input) {
      var id = input.getAttribute('data-filter-for');
      getState(id);
      input.addEventListener('input', function () {
        getState(id).q = input.value.trim().toLowerCase();
        apply(id);
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-chips-for]'), function (wrap) {
      var id = wrap.getAttribute('data-chips-for');
      getState(id);
      wrap.addEventListener('click', function (e) {
        var chip = e.target.closest ? e.target.closest('[data-cat]') : null;
        if (!chip || !wrap.contains(chip)) return;
        getState(id).cat = chip.getAttribute('data-cat');
        Array.prototype.forEach.call(wrap.querySelectorAll('[data-cat]'), function (b) {
          b.classList.toggle('active', b === chip);
        });
        apply(id);
      });
    });
    Object.keys(state).forEach(apply);
  }

  /* ---------- Сортировка ---------- */
  function initSorting() {
    Array.prototype.forEach.call(document.querySelectorAll('table.sortable'), function (table) {
      var tbody = table.tBodies && table.tBodies[0];
      if (!tbody) return;
      var ths = table.querySelectorAll('th[data-sort]');
      Array.prototype.forEach.call(ths, function (th) {
        th.addEventListener('click', function () {
          var idx = th.cellIndex;
          var type = th.getAttribute('data-sort');
          var dir = th.classList.contains('sort-asc') ? -1 : 1;
          Array.prototype.forEach.call(ths, function (o) {
            o.classList.remove('sort-asc', 'sort-desc');
            o.removeAttribute('aria-sort');
          });
          th.classList.add(dir === 1 ? 'sort-asc' : 'sort-desc');
          th.setAttribute('aria-sort', dir === 1 ? 'ascending' : 'descending');

          var rows = Array.prototype.filter.call(tbody.querySelectorAll('tr'), function (tr) {
            return !tr.classList.contains('filter-empty') && !tr.classList.contains('empty-row');
          });
          function key(tr) {
            var cell = tr.children[idx];
            var raw = cell ? cell.textContent.trim() : '';
            if (type === 'num') {
              var v = parseFloat(raw.replace(',', '.'));
              return isNaN(v) ? null : v;
            }
            return raw.toLowerCase();
          }
          rows.sort(function (a, b) {
            var ka = key(a), kb = key(b);
            var aEmpty = ka === null || ka === '';
            var bEmpty = kb === null || kb === '';
            if (aEmpty && bEmpty) return 0;
            if (aEmpty) return 1;
            if (bEmpty) return -1;
            if (type === 'num') return (ka - kb) * dir;
            return ka < kb ? -dir : (ka > kb ? dir : 0);
          });
          var frag = document.createDocumentFragment();
          rows.forEach(function (r) { frag.appendChild(r); });
          var emptyRow = tbody.querySelector('.filter-empty');
          var emptyDataRow = tbody.querySelector('.empty-row');
          tbody.appendChild(frag);
          if (emptyDataRow) tbody.appendChild(emptyDataRow);
          if (emptyRow) tbody.appendChild(emptyRow);
          document.dispatchEvent(new Event('table:refresh'));
        });
      });
    });
  }

  /* ---------- Автообновление графиков (60 с, только ?v=) ---------- */
  function initCharts() {
    var box = document.getElementById('charts');
    if (!box) return;
    var imgs = box.querySelectorAll('img.chart-img');
    if (!imgs.length) return;

    var demo = box.getAttribute('data-demo') === '1';
    var PERIOD_SEC = 60;
    var nextRefresh = Date.now() + PERIOD_SEC * 1000;
    var lastRefresh = Date.now();
    var countdownEl = document.getElementById('charts-countdown');
    var updatedEl = document.getElementById('charts-updated');
    var refreshBtn = document.getElementById('charts-refresh');

    function pad(n) { return (n < 10 ? '0' : '') + n; }
    function timeNow() {
      var d = new Date();
      return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
    }
    function refresh() {
      var bust = Date.now();
      Array.prototype.forEach.call(imgs, function (img) {
        var mode = img.getAttribute('data-mode');
        img.src = '/admin/chart/' + mode + '?v=' + bust + (demo ? '&demo=1' : '');
      });
      nextRefresh = bust + PERIOD_SEC * 1000;
      lastRefresh = bust;
      if (updatedEl) updatedEl.textContent = 'обновлено в ' + timeNow();
    }
    function tick() {
      var left = Math.max(0, Math.round((nextRefresh - Date.now()) / 1000));
      if (countdownEl) countdownEl.textContent = left;
      if (left <= 0) refresh();
    }
    if (refreshBtn) refreshBtn.addEventListener('click', refresh);
    if (updatedEl) updatedEl.textContent = 'обновлено в ' + timeNow();
    setInterval(tick, 1000);
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden && Date.now() - lastRefresh > 30 * 1000) refresh();
    });
  }

  /* ---------- Счётчики символов ---------- */
  function initCharCounters() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-char-for]'), function (counter) {
      var el = document.getElementById(counter.getAttribute('data-char-for'));
      if (!el) return;
      var max = parseInt(el.getAttribute('maxlength'), 10) || 0;
      function update() {
        var len = el.value.length;
        counter.textContent = max ? (len + ' / ' + max) : String(len);
        counter.classList.toggle('near-limit', !!max && len > max * 0.9);
      }
      el.addEventListener('input', update);
      update();
    });
  }

  /* ---------- «/» — фокус на поиск ---------- */
  function initSlashFocus() {
    document.addEventListener('keydown', function (e) {
      if (e.key !== '/' || e.ctrlKey || e.altKey || e.metaKey) return;
      var t = e.target;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      var input = document.querySelector('.filter-input');
      if (input && !input.hidden) {
        e.preventDefault();
        input.focus();
      }
    });
  }

  /* ---------- max/min температуры среди видимых строк ---------- */
  function initDataExtremes() {
    var tbody = document.getElementById('data-tbody');
    if (!tbody) return;
    function update() {
      Array.prototype.forEach.call(tbody.querySelectorAll('.t-min, .t-max'), function (td) {
        td.classList.remove('t-min', 't-max');
      });
      var rows = Array.prototype.filter.call(tbody.querySelectorAll('tr'), function (tr) {
        return !tr.classList.contains('filter-empty') && !tr.classList.contains('empty-row') && !tr.hidden;
      });
      if (rows.length < 2) return;
      var hi = null, lo = null;
      rows.forEach(function (tr) {
        var td = tr.children[2];
        if (!td) return;
        var v = parseFloat((td.textContent || '').replace(',', '.'));
        if (isNaN(v)) return;
        td._extVal = v;
        if (!lo || v < lo._extVal) lo = td;
        if (!hi || v > hi._extVal) hi = td;
      });
      if (lo && hi && lo !== hi) {
        lo.classList.add('t-min');
        hi.classList.add('t-max');
      }
    }
    document.addEventListener('table:refresh', update);
    update();
  }

  /* ---------- Текущая официальная погода (Open-Meteo) по кнопке ---------- */
  function initOmCurrent() {
    var btn = document.getElementById('om-fetch');
    var body = document.getElementById('om-body');
    if (!btn || !body) return;

    function kv(k, v) {
      return '<div class="om-k">' + k + '</div><div class="om-v mono">' + v + '</div>';
    }
    function fmt(v, suffix) {
      return (v === null || v === undefined) ? '—' : v + (suffix || '');
    }
    function render(d) {
      var html = '<div class="om-grid">'
        + kv('Погода', d.weather)
        + kv('Температура', fmt(d.temp, ' °C'))
        + kv('Ощущается', fmt(d.feels, ' °C'))
        + kv('Влажность', fmt(d.hum, ' %'))
        + kv('Давление', fmt(d.pressure_mm, ' мм'))
        + kv('Ветер', (d.wind_ms === null || d.wind_ms === undefined)
             ? '—' : fmt(d.wind_ms, ' м/с') + ', ' + d.wind_dir)
        + kv('Облачность', fmt(d.cloud, ' %'))
        + kv('Осадки за час', fmt(d.precip, ' мм'))
        + '</div>';
      if (d.station_temp !== null && d.station_temp !== undefined) {
        html += '<div class="om-station">Станция сейчас: <strong class="mono">'
              + d.station_temp + ' °C</strong></div>';
        if (d.temp !== null && d.temp !== undefined) {
          var avg = ((d.station_temp + d.temp) / 2).toFixed(1);
          html += '<div class="om-station">Для показа (усреднённая): <strong class="mono">'
                + avg + ' °C</strong></div>';
        }
      }
      html += '<p class="hint">Наблюдение Open-Meteo на ' + (d.obs_local || '—')
            + ' (местн.) · данные кэшируются 10 минут</p>';
      body.innerHTML = html;
    }

    function load() {
      btn.disabled = true;
      body.innerHTML = '<p class="hint">Загрузка…</p>';
      fetch('/admin/openmeteo/current')
        .then(function (r) { return r.json(); })
        .then(function (d) {
          btn.disabled = false;
          btn.textContent = 'Обновить';
          if (!d.ok) throw new Error(d.error || 'ошибка');
          render(d);
        })
        .catch(function (e) {
          btn.disabled = false;
          btn.textContent = 'Повторить';
          body.innerHTML = '<p class="hint warn-text">Не удалось получить данные: '
            + (e.message || 'сеть') + '</p>';
        });
    }
    btn.addEventListener('click', load);
  }
})();
