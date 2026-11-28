#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
install_admin_ui v3 — сборщик веб-админки «Солигорск».
Дизайн: «инженерная бумага» — миллиметровая сетка, волосяные линии,
моноширинные данные, один сигнальный акцент. Без градиентов и свечения.

По умолчанию кладёт файлы в <корень>/web/templates и <корень>/web/static
(как ожидает TestV4.py). Если шаблоны в корне проекта — WEB_SUBDIR = "".

Запуск:
    python3 install_admin_ui.py              # текущая папка
    python3 install_admin_ui.py ~/weather-bot

Напоминание: имена пользователей / тренды / удаление пользователя
требуют патча TestV4.py из предыдущих сообщений.
"""

import os
import sys

WEB_SUBDIR = ""

FILES = {}

FILES["templates/base.html"] = r'''
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Админка · Солигорск{% endblock %}</title>
  <meta name="color-scheme" content="light dark">
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Crect width='24' height='24' rx='5' fill='%23191813'/%3E%3Cpath d='M10 13.6V6a2 2 0 0 1 4 0v7.6a3.8 3.8 0 1 1-4 0z' fill='none' stroke='%23f5f4f0' stroke-width='1.6'/%3E%3Ccircle cx='12' cy='16.6' r='1.5' fill='%23f5f4f0'/%3E%3C/svg%3E">
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
  <script src="{{ url_for('static', filename='script.js') }}"></script>
</head>
<body>
<svg xmlns="http://www.w3.org/2000/svg" class="sprite" aria-hidden="true" focusable="false">
  <symbol id="i-logo" viewBox="0 0 24 24"><path d="M10 13.6V5a2.5 2.5 0 0 1 5 0v8.6a4.5 4.5 0 1 1-5 0z"/><path d="M12.5 8v8.2"/><circle cx="12.5" cy="17.5" r="1.7" fill="currentColor" stroke="none"/></symbol>
  <symbol id="i-dash" viewBox="0 0 24 24"><rect x="3.5" y="3.5" width="7.2" height="7.2" rx="1"/><rect x="13.3" y="3.5" width="7.2" height="7.2" rx="1"/><rect x="3.5" y="13.3" width="7.2" height="7.2" rx="1"/><rect x="13.3" y="13.3" width="7.2" height="7.2" rx="1"/></symbol>
  <symbol id="i-users" viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.4"/><path d="M3.2 19.4c.7-3.4 3-5.2 5.8-5.2s5.1 1.8 5.8 5.2"/><path d="M15.4 5.2a3.4 3.4 0 0 1 0 5.6"/><path d="M17.4 14.6c1.9.7 3.1 2.2 3.5 4.4"/></symbol>
  <symbol id="i-db" viewBox="0 0 24 24"><ellipse cx="12" cy="5.4" rx="7.6" ry="2.9"/><path d="M4.4 5.4v13.2c0 1.6 3.4 2.9 7.6 2.9s7.6-1.3 7.6-2.9V5.4"/><path d="M4.4 12c0 1.6 3.4 2.9 7.6 2.9s7.6-1.3 7.6-2.9"/></symbol>
  <symbol id="i-box" viewBox="0 0 24 24"><rect x="3.2" y="4" width="17.6" height="4.4" rx="1"/><path d="M5.2 8.4v9.8a2 2 0 0 0 2 2h9.6a2 2 0 0 0 2-2V8.4"/><path d="M10 12.4h4"/></symbol>
  <symbol id="i-out" viewBox="0 0 24 24"><path d="M14.5 8.5v-2a2 2 0 0 0-2-2H6.3a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h6.2a2 2 0 0 0 2-2v-2"/><path d="M9.5 12h10.7"/><path d="M17.6 9.2l2.8 2.8-2.8 2.8"/></symbol>
  <symbol id="i-refresh" viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v5h-5"/></symbol>
  <symbol id="i-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M18.5 5.5l-1.7 1.7M7.2 16.8l-1.7 1.7"/></symbol>
  <symbol id="i-moon" viewBox="0 0 24 24"><path d="M20.6 13.6A8.6 8.6 0 1 1 10.4 3.4a6.9 6.9 0 0 0 10.2 10.2z"/></symbol>
  <symbol id="i-flask" viewBox="0 0 24 24"><path d="M9.2 3h5.6"/><path d="M10.2 3v5.3L4.9 17a3.1 3.1 0 0 0 2.7 4.5h8.8a3.1 3.1 0 0 0 2.7-4.5L13.8 8.3V3"/><path d="M7.3 14.2h9.4"/></symbol>
  <symbol id="i-send" viewBox="0 0 24 24"><path d="M21 3.5 10.5 14"/><path d="M21 3.5l-6.8 17.3-3.7-6.8-6.8-3.7z"/></symbol>
  <symbol id="i-trash" viewBox="0 0 24 24"><path d="M4 7h16"/><path d="M9.5 7V5.2A1.2 1.2 0 0 1 10.7 4h2.6a1.2 1.2 0 0 1 1.2 1.2V7"/><path d="M6.5 7l.8 12.2A2 2 0 0 0 9.3 21h5.4a2 2 0 0 0 2-1.8L17.5 7"/><path d="M10 11v6M14 11v6"/></symbol>
  <symbol id="i-down" viewBox="0 0 24 24"><path d="M12 4v10.5"/><path d="M7.5 10.5 12 15l4.5-4.5"/><path d="M4.5 19.5h15"/></symbol>
  <symbol id="i-plus" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></symbol>
  <symbol id="i-eye" viewBox="0 0 24 24"><path d="M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/></symbol>
  <symbol id="i-eye-off" viewBox="0 0 24 24"><path d="M2.5 12S6 5.8 12 5.8a9.8 9.8 0 0 1 4 .9M21.5 12S18 18.2 12 18.2a9.8 9.8 0 0 1-4-.9"/><path d="M4 20 20 4"/></symbol>
  <symbol id="i-ban" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.2"/><path d="M6.3 6.3l11.4 11.4"/></symbol>
  <symbol id="i-check" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.2"/><path d="M8.4 12.3l2.4 2.4 4.8-4.8"/></symbol>
  <symbol id="i-search" viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.2"/><path d="M20 20l-4.6-4.6"/></symbol>
  <symbol id="i-warn" viewBox="0 0 24 24"><path d="M12 4.6 2.9 19.4a1.6 1.6 0 0 0 1.4 2.4h15.4a1.6 1.6 0 0 0 1.4-2.4L12 4.6z"/><path d="M12 10v4.4"/><path d="M12 17.4h.01"/></symbol>
  <symbol id="i-copy" viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="1.5"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></symbol>
  <symbol id="i-x" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></symbol>
</svg>

{% block body %}
<div class="app">
  <aside class="sidebar">
    <a class="brand" href="/admin">
      <span class="brand-mark"><svg class="icon" aria-hidden="true"><use href="#i-logo"/></svg></span>
      <span class="brand-text"><strong>Солигорск</strong><small>админка метеостанции</small></span>
    </a>
    <nav class="snav" aria-label="Разделы">
      <a class="snav-link{% if active == 'dashboard' %} active{% endif %}" href="/admin"><svg class="icon" aria-hidden="true"><use href="#i-dash"/></svg>Панель</a>
      <a class="snav-link{% if active == 'users' %} active{% endif %}" href="/admin/users"><svg class="icon" aria-hidden="true"><use href="#i-users"/></svg>Пользователи<span class="snav-badge">{{ users_total }}</span></a>
      <a class="snav-link{% if active == 'data' %} active{% endif %}" href="/admin/data"><svg class="icon" aria-hidden="true"><use href="#i-db"/></svg>Данные</a>
      <a class="snav-link{% if active == 'backups' %} active{% endif %}" href="/admin/backups"><svg class="icon" aria-hidden="true"><use href="#i-box"/></svg>Бэкапы</a>
    </nav>
    <div class="sysinfo">
      <div class="sys-row">
        <span class="sys-dot {{ 'on' if station_online else 'off' }}" aria-hidden="true"></span>
        <span class="sys-line">{{ 'Станция на связи' if station_online else 'Станция молчит' }}</span>
      </div>
      <div class="sys-foot">
        <span>замер · <span class="mono">{{ station_age }}</span></span>
        <span>аптайм · <span class="mono">{{ uptime }}</span></span>
        <span>старт · <span class="mono">{{ bot_started }}</span></span>
      </div>
    </div>
  </aside>

  <div class="shell">
    <header class="topbar">
      <a class="brand-m" href="/admin"><span class="mark"><svg class="icon" aria-hidden="true"><use href="#i-logo"/></svg></span>Солигорск</a>
      <div class="topbar-status">
        <span class="chip {{ 'chip-ok' if station_online else 'chip-bad' }}" title="{{ 'Станция присылает данные' if station_online else 'Станция давно не присылала данные' }}">
          <span class="dot" aria-hidden="true"></span>
          <span class="chip-label">станция</span>
          <span class="chip-extra mono">{{ station_age }}</span>
        </span>
        <form method="post" action="/admin/testmode" class="inline-form"
              data-confirm="{{ 'Выключить тест-режим? Бот начнёт отправлять реальные сообщения.' if test_mode else 'Включить тест-режим? Реальные сообщения отправляться не будут.' }}">
          <button type="submit" class="btn btn-sm{{ ' btn-test-on' if test_mode else ' btn-ghost' }}" title="Переключить тест-режим бота">
            <svg class="icon" aria-hidden="true"><use href="#i-flask"/></svg>
            <span class="btn-label"><span class="hide-sm">Тест-режим: </span>{{ 'вкл' if test_mode else 'выкл' }}</span>
          </button>
        </form>
        <button type="button" class="btn btn-icon btn-ghost" id="theme-toggle" title="Переключить тему" aria-label="Переключить тему">
          <svg class="icon t-hide-dark" aria-hidden="true"><use href="#i-moon"/></svg>
          <svg class="icon t-hide-light" aria-hidden="true"><use href="#i-sun"/></svg>
        </button>
        <form method="post" action="/admin/logout" class="inline-form" data-confirm="Выйти из админки?">
          <button type="submit" class="btn btn-sm btn-ghost" title="Выйти">
            <svg class="icon" aria-hidden="true"><use href="#i-out"/></svg>
            <span class="btn-label hide-sm">Выход</span>
          </button>
        </form>
      </div>
    </header>

    <main class="main">
      {% block content %}{% endblock %}
    </main>

    <footer class="footer">
      <span>Бот запущен {{ bot_started }} · аптайм {{ uptime }}</span>
      <span>Метеостанция «Солигорск» · домашняя локальная сеть</span>
    </footer>
  </div>
</div>

<nav class="docknav" aria-label="Разделы">
  <a class="dock-link{% if active == 'dashboard' %} active{% endif %}" href="/admin"><svg class="icon" aria-hidden="true"><use href="#i-dash"/></svg><span>Панель</span></a>
  <a class="dock-link{% if active == 'users' %} active{% endif %}" href="/admin/users"><svg class="icon" aria-hidden="true"><use href="#i-users"/></svg><span>Люди</span></a>
  <a class="dock-link{% if active == 'data' %} active{% endif %}" href="/admin/data"><svg class="icon" aria-hidden="true"><use href="#i-db"/></svg><span>Данные</span></a>
  <a class="dock-link{% if active == 'backups' %} active{% endif %}" href="/admin/backups"><svg class="icon" aria-hidden="true"><use href="#i-box"/></svg><span>Бэкапы</span></a>
</nav>
{% endblock %}
</body>
</html>
'''

FILES["templates/login.html"] = r'''
{% extends "base.html" %}
{% block title %}Вход · Солигорск{% endblock %}
{% block body %}
<div class="login-page">
  <div class="login-card">
    <div class="login-logo"><svg class="icon" aria-hidden="true"><use href="#i-logo"/></svg></div>
    <h1>Солигорск</h1>
    <p class="login-sub">Админка домашней метеостанции</p>
    <form method="post" action="/admin" class="login-form">
      <label for="password">Пароль</label>
      <div class="password-wrap">
        <input type="password" id="password" name="password" autocomplete="current-password" required autofocus placeholder="••••••••">
        <button type="button" class="pw-toggle" data-toggle-password aria-label="Показать пароль">
          <svg class="icon eye-on" aria-hidden="true"><use href="#i-eye"/></svg>
          <svg class="icon eye-off" aria-hidden="true"><use href="#i-eye-off"/></svg>
        </button>
      </div>
      <button type="submit" class="btn btn-primary btn-block">Войти</button>
    </form>
    <p class="login-foot">Локальная сеть · без выхода в интернет</p>
  </div>
</div>
{% endblock %}
'''

FILES["templates/dashboard.html"] = r'''
{% extends "base.html" %}
{% block title %}Панель · Солигорск{% endblock %}

{% macro tval(v) %}{% if v is none %}<span class="dash">—</span>{% else %}{{ '%.1f'|format(v) }}<span class="unit"> °C</span>{% endif %}{% endmacro %}
{% macro cval(v) %}{% if v is none %}<span class="dash">—</span>{% else %}{{ v }}{% endif %}{% endmacro %}
{% macro trend(v, unit) %}
  {%- set cls = 'flat' if v is not defined or v is none or v == 0 else ('up' if v > 0 else 'down') -%}
  <div class="stat-value stat-trend {{ cls }}">
    {%- if v is defined and v is not none %}{{ '%+.1f'|format(v) }}<span class="unit"> {{ unit }}</span>{% else %}<span class="dash">—</span>{% endif -%}
  </div>
{% endmacro %}

{% block content %}
{% if test_mode %}
<div class="banner" role="status">
  <svg class="icon" aria-hidden="true"><use href="#i-warn"/></svg>
  <div>Бот в тестовом режиме — реальные сообщения пользователям не отправляются. Переключение — кнопка «Тест-режим» в шапке.</div>
</div>
{% endif %}

<div class="page-head">
  <div>
    <h1>Панель</h1>
    <p class="page-sub">Последний замер: <span class="mono">{{ last_ts }}</span>{% if not station_online %} · <span class="warn-text">станция не на связи</span>{% endif %}</p>
  </div>
  <div class="page-actions">
    <a class="btn btn-ghost" href="/admin/export/csv" title="Выгрузка последних 7 дней"><svg class="icon" aria-hidden="true"><use href="#i-down"/></svg>CSV · 7 дней</a>
    <a class="btn btn-ghost" href="/admin/export/xlsx" title="Выгрузка последних 7 дней"><svg class="icon" aria-hidden="true"><use href="#i-down"/></svg>XLSX · 7 дней</a>
  </div>
</div>

<section class="stats-grid" aria-label="Показатели">
  <div class="stat">
    <div class="stat-label">Всего записей</div>
    <div class="stat-value">{{ total }}</div>
    <div class="stat-sub">в базе данных</div>
  </div>
  <div class="stat">
    <div class="stat-label">За 24 часа</div>
    <div class="stat-value">{{ sensor_24h }}</div>
    <div class="stat-sub">новых замеров</div>
  </div>
  <div class="stat">
    <div class="stat-label">Размер БД</div>
    <div class="stat-value">{{ '%.2f'|format(db_size_mb) }}<span class="unit"> МБ</span></div>
    <div class="stat-sub">файл базы</div>
  </div>
  <div class="stat">
    <div class="stat-label">Пользователи бота</div>
    <div class="stat-value">{{ users_total }}</div>
    <div class="stat-sub">{% if users_blocked %}заблокировано: {{ users_blocked }}{% else %}никого не заблокировано{% endif %}</div>
  </div>
  <div class="stat">
    <div class="stat-label">Активность</div>
    <div class="stat-value">{{ active_1h }}</div>
    <div class="stat-sub">человек за последний час</div>
  </div>
  <div class="stat">
    <div class="stat-label">Отказы /update</div>
    <div class="stat-value">{{ rejects_24h }}</div>
    <div class="stat-sub">за последние 24 часа</div>
  </div>
  <div class="stat">
    <div class="stat-label">T за час</div>
    {{ trend(t_delta_1h, '°C') }}
    <div class="stat-sub">тренд температуры</div>
  </div>
  <div class="stat">
    <div class="stat-label">Давление за 3 ч</div>
    {{ trend(p_delta_3h, 'мм') }}
    <div class="stat-sub">тренд давления</div>
  </div>
</section>

<section class="card">
  <div class="card-head">
    <h2><svg class="icon" aria-hidden="true"><use href="#i-dash"/></svg>Сводка температуры</h2>
    <span class="hint">по данным станции</span>
  </div>
  <div class="table-wrap table-wrap-flush">
    <table class="table summary-table">
      <thead>
        <tr>
          <th scope="col">Показатель</th>
          <th scope="col" class="num">24 часа</th>
          <th scope="col" class="num">7 дней</th>
          <th scope="col" class="num">30 дней</th>
        </tr>
      </thead>
      <tbody>
        <tr><td>Минимум</td><td class="num">{{ tval(s24[0]) }}</td><td class="num">{{ tval(s7[0]) }}</td><td class="num">{{ tval(s30[0]) }}</td></tr>
        <tr><td>Средняя</td><td class="num">{{ tval(s24[2]) }}</td><td class="num">{{ tval(s7[2]) }}</td><td class="num">{{ tval(s30[2]) }}</td></tr>
        <tr><td>Максимум</td><td class="num">{{ tval(s24[1]) }}</td><td class="num">{{ tval(s7[1]) }}</td><td class="num">{{ tval(s30[1]) }}</td></tr>
        <tr><td>Замеров</td><td class="num">{{ cval(s24[3]) }}</td><td class="num">{{ cval(s7[3]) }}</td><td class="num">{{ cval(s30[3]) }}</td></tr>
      </tbody>
    </table>
  </div>
</section>

<section class="card" id="charts" data-demo="{{ '1' if chart_demo else '0' }}">
  <div class="card-head">
    <h2><svg class="icon" aria-hidden="true"><use href="#i-refresh"/></svg>Графики</h2>
    <div class="charts-controls">
      <a class="btn btn-sm {{ 'btn-test-on' if chart_demo else 'btn-ghost' }}" href="{{ '?' if chart_demo else '?demo=1' }}"
         data-confirm="{{ 'Вернуть реальные графики?' if chart_demo else 'Переключить графики на тестовые (синтетические) данные?' }}">
        <svg class="icon" aria-hidden="true"><use href="#i-flask"/></svg>
        <span class="btn-label"><span class="hide-sm">Графики: </span>{{ 'тест' if chart_demo else 'реальные' }}</span>
      </a>
      <span class="charts-updated" id="charts-updated">—</span>
      <button type="button" class="btn btn-sm btn-ghost" id="charts-refresh" title="Обновить графики сейчас">
        <svg class="icon" aria-hidden="true"><use href="#i-refresh"/></svg>
        <span class="btn-label">Обновить · <span id="charts-countdown">60</span> с</span>
      </button>
    </div>
  </div>
  {% if chart_demo %}<p class="hint warn-text">Показаны синтетические тестовые данные.</p>{% endif %}
  <p class="hint">Клик по графику открывает его на весь экран.</p>
  <div class="charts-grid">
    <figure class="chart">
      <figcaption>24 часа</figcaption>
      <img class="chart-img" data-mode="24h" src="/admin/chart/24h?v={{ bust }}{% if chart_demo %}&amp;demo=1{% endif %}" alt="График измерений за последние 24 часа">
    </figure>
    <figure class="chart">
      <figcaption>7 дней</figcaption>
      <img class="chart-img" data-mode="7d" src="/admin/chart/7d?v={{ bust }}{% if chart_demo %}&amp;demo=1{% endif %}" alt="График измерений за последние 7 дней">
    </figure>
    <figure class="chart">
      <figcaption>30 дней</figcaption>
      <img class="chart-img" data-mode="30d" src="/admin/chart/30d?v={{ bust }}{% if chart_demo %}&amp;demo=1{% endif %}" alt="График измерений за последние 30 дней">
    </figure>
    <figure class="chart">
      <figcaption>Точка росы</figcaption>
      <img class="chart-img" data-mode="dew" src="/admin/chart/dew?v={{ bust }}{% if chart_demo %}&amp;demo=1{% endif %}" alt="График точки росы">
    </figure>
  </div>
</section>

<section class="card">
  <div class="card-head"><h2><svg class="icon" aria-hidden="true"><use href="#i-plus"/></svg>Быстрые действия</h2></div>
  <div class="quick-actions">
    <a class="btn btn-ghost" href="/admin/users#broadcast"><svg class="icon" aria-hidden="true"><use href="#i-send"/></svg>Рассылка пользователям</a>
    <a class="btn btn-ghost" href="/admin/data#insert"><svg class="icon" aria-hidden="true"><use href="#i-plus"/></svg>Добавить запись вручную</a>
    <a class="btn btn-ghost" href="/admin/backups"><svg class="icon" aria-hidden="true"><use href="#i-box"/></svg>Создать бэкап</a>
  </div>
</section>
{% endblock %}
'''

FILES["templates/users.html"] = r'''
{% extends "base.html" %}
{% block title %}Пользователи · Солигорск{% endblock %}
{% block content %}
{% set blocked_n = users|selectattr('blocked', 'equalto', 1)|list|length %}
<div class="page-head">
  <div>
    <h1>Пользователи</h1>
    <p class="page-sub">Всего: {{ users|length }} · заблокировано: {{ blocked_n }} · имя появляется после первого сообщения боту</p>
  </div>
</div>

<section class="card" id="broadcast">
  <div class="card-head">
    <h2><svg class="icon" aria-hidden="true"><use href="#i-send"/></svg>Рассылка</h2>
    {% if test_mode %}<span class="badge badge-warn">тест-режим — реально не уйдёт</span>{% endif %}
  </div>
  <form method="post" action="/admin/broadcast" data-confirm="Отправить рассылку всем пользователям бота? Отменить отправку будет нельзя.">
    <textarea id="broadcast-text" name="text" rows="3" maxlength="4096" required placeholder="Текст сообщения для всех пользователей…"></textarea>
    <div class="form-foot">
      <span class="char-counter" id="broadcast-counter" data-char-for="broadcast-text">0 / 4096</span>
      <button type="submit" class="btn btn-primary"><svg class="icon" aria-hidden="true"><use href="#i-send"/></svg>Отправить всем</button>
    </div>
  </form>
</section>

<section class="card">
  <div class="card-head">
    <h2><svg class="icon" aria-hidden="true"><use href="#i-users"/></svg>Список пользователей</h2>
    <span class="hint">отсортировано по последней активности</span>
  </div>
  <div class="table-controls">
    <div class="chips" data-chips-for="users-tbody" role="group" aria-label="Фильтр по статусу">
      <button type="button" class="fchip active" data-cat="all">Все</button>
      <button type="button" class="fchip" data-cat="active">Активные</button>
      <button type="button" class="fchip" data-cat="blocked">Заблокированные</button>
    </div>
    <div class="table-tools">
      <span class="search-wrap">
        <svg class="icon" aria-hidden="true"><use href="#i-search"/></svg>
        <input type="search" class="filter-input" data-filter-for="users-tbody" placeholder="Поиск: имя, @username, ID…" aria-label="Фильтр по подстроке">
      </span>
      <span class="filter-count" data-filter-count="users-tbody"></span>
    </div>
  </div>
  <div class="table-wrap">
    <table class="table sortable" id="users-table">
      <thead>
        <tr>
          <th scope="col" data-sort="text">Пользователь</th>
          <th scope="col" data-sort="text">Активность</th>
          <th scope="col">Статус</th>
          <th scope="col" class="th-actions">Действия</th>
        </tr>
      </thead>
      <tbody id="users-tbody">
        {% for u in users %}
        <tr data-cat="{{ 'blocked' if u.blocked else 'active' }}">
          <td class="cell-user">
            <span class="avatar" aria-hidden="true">{{ (u.name[:1]|upper) if u.name else '#' }}</span>
            <span class="user-meta">
              <span class="user-name">{{ u.name if u.name else 'Без имени' }}</span>
              <span class="user-tag mono">{% if u.username %}<a href="https://t.me/{{ u.username }}" target="_blank" rel="noopener">@{{ u.username }}</a>{% else %}—{% endif %} · ID {{ u.uid }}</span>
            </span>
          </td>
          <td class="mono{% if u.act == '—' %} dash{% endif %}">{{ u.act }}</td>
          <td>{% if u.blocked %}<span class="badge badge-danger">заблокирован</span>{% else %}<span class="badge badge-ok">активен</span>{% endif %}</td>
          <td class="td-actions no-filter">
            <button type="button" class="btn btn-sm btn-icon btn-ghost" data-copy="{{ u.uid }}" title="Скопировать ID {{ u.uid }}" aria-label="Скопировать ID">
              <svg class="icon" aria-hidden="true"><use href="#i-copy"/></svg>
            </button>
            {% if u.blocked %}
            <form method="post" action="/admin/users/unblock" class="inline-form">
              <input type="hidden" name="user_id" value="{{ u.uid }}">
              <button type="submit" class="btn btn-sm btn-ghost" title="Разблокировать {{ u.uid }}"><svg class="icon" aria-hidden="true"><use href="#i-check"/></svg><span class="btn-label">Разблокировать</span></button>
            </form>
            {% else %}
            <form method="post" action="/admin/users/block" class="inline-form" data-confirm="Заблокировать пользователя {{ u.uid }}? Он перестанет получать сообщения бота.">
              <input type="hidden" name="user_id" value="{{ u.uid }}">
              <button type="submit" class="btn btn-sm btn-danger-ghost" title="Заблокировать {{ u.uid }}"><svg class="icon" aria-hidden="true"><use href="#i-ban"/></svg><span class="btn-label">Заблокировать</span></button>
            </form>
            {% endif %}
            <form method="post" action="/admin/users/delete" class="inline-form" data-confirm="Удалить пользователя {{ u.uid }} из базы? Он снова появится, если напишет боту.">
              <input type="hidden" name="user_id" value="{{ u.uid }}">
              <button type="submit" class="btn btn-sm btn-icon btn-ghost btn-del" title="Удалить {{ u.uid }}" aria-label="Удалить пользователя">
                <svg class="icon" aria-hidden="true"><use href="#i-x"/></svg>
              </button>
            </form>
          </td>
        </tr>
        {% else %}
        <tr class="empty-row"><td colspan="4">Пользователей пока нет.</td></tr>
        {% endfor %}
        <tr class="filter-empty" hidden><td colspan="4" class="empty-cell">Ничего не найдено — измените поиск или фильтр.</td></tr>
      </tbody>
    </table>
  </div>
</section>
{% endblock %}
'''

FILES["templates/data.html"] = r'''
{% extends "base.html" %}
{% block title %}Данные · Солигорск{% endblock %}
{% block content %}
<div class="page-head">
  <div>
    <h1>Данные</h1>
    <p class="page-sub">Последние {{ records|length }} записей · новое сверху</p>
  </div>
  <div class="page-actions">
    <a class="btn btn-ghost" href="/admin/export/csv" title="Выгрузка последних 7 дней"><svg class="icon" aria-hidden="true"><use href="#i-down"/></svg>CSV · 7 дней</a>
    <a class="btn btn-ghost" href="/admin/export/xlsx" title="Выгрузка последних 7 дней"><svg class="icon" aria-hidden="true"><use href="#i-down"/></svg>XLSX · 7 дней</a>
  </div>
</div>

<section class="card" id="insert">
  <div class="card-head">
    <h2><svg class="icon" aria-hidden="true"><use href="#i-plus"/></svg>Ручная вставка записи</h2>
    <span class="hint">температура и влажность — обязательны</span>
  </div>
  <form method="post" action="/admin/data/insert" class="field-row">
    <label class="field">Температура, °C
      <input type="number" name="t" step="any" required placeholder="21.4">
    </label>
    <label class="field">Влажность, %
      <input type="number" name="h" step="any" min="0" max="100" required placeholder="64">
    </label>
    <label class="field">Давление, мм рт. ст.
      <input type="text" name="p" inputmode="decimal" placeholder="746 (можно пусто)">
    </label>
    <button type="submit" class="btn btn-primary"><svg class="icon" aria-hidden="true"><use href="#i-plus"/></svg>Добавить</button>
  </form>
</section>

<section class="card">
  <div class="card-head">
    <h2><svg class="icon" aria-hidden="true"><use href="#i-db"/></svg>Записи измерений</h2>
  </div>
  <div class="table-controls">
    <div class="chips" data-chips-for="data-tbody" role="group" aria-label="Фильтр по метке">
      <button type="button" class="fchip active" data-cat="all">Все</button>
      <button type="button" class="fchip" data-cat="ok">Без брака</button>
      <button type="button" class="fchip" data-cat="bad">Только брак</button>
    </div>
    <div class="table-tools">
      <span class="search-wrap">
        <svg class="icon" aria-hidden="true"><use href="#i-search"/></svg>
        <input type="search" class="filter-input" data-filter-for="data-tbody" placeholder="Поиск: дата, температура…" aria-label="Фильтр по подстроке">
      </span>
      <span class="filter-count" data-filter-count="data-tbody"></span>
    </div>
  </div>
  <div class="table-wrap">
    <table class="table sortable">
      <thead>
        <tr>
          <th scope="col" data-sort="num" class="num">#</th>
          <th scope="col" data-sort="text">Время</th>
          <th scope="col" data-sort="num" class="num">t, °C</th>
          <th scope="col" data-sort="num" class="num">Влажность, %</th>
          <th scope="col" data-sort="num" class="num">Давление, мм</th>
          <th scope="col" class="th-actions"><span class="visually-hidden">Действия</span></th>
        </tr>
      </thead>
      <tbody id="data-tbody">
        {% for r in records %}
        <tr data-cat="{{ 'bad' if r.bad else 'ok' }}"{% if r.bad %} data-bad="1"{% endif %}>
          <td class="mono num">{{ r.id }}</td>
          <td class="mono">{{ r.ts }}{% if r.bad %} <span class="badge badge-danger" title="Запись помечена как брак умершего датчика">брак</span>{% endif %}</td>
          <td class="num">{{ '%.1f'|format(r.t) }}</td>
          <td class="num">{{ '%.1f'|format(r.h) }}</td>
          <td class="mono{% if r.p == '—' %} dash{% endif %}">{{ r.p }}</td>
          <td class="td-actions no-filter">
            <form method="post" action="/admin/data/delete" class="inline-form" data-confirm="Удалить запись #{{ r.id }} ({{ r.ts }})? Это действие необратимо.">
              <input type="hidden" name="id" value="{{ r.id }}">
              <button type="submit" class="btn btn-sm btn-danger-ghost" title="Удалить запись {{ r.id }}"><svg class="icon" aria-hidden="true"><use href="#i-trash"/></svg><span class="btn-label">Удалить</span></button>
            </form>
          </td>
        </tr>
        {% else %}
        <tr class="empty-row"><td colspan="6">Записей пока нет.</td></tr>
        {% endfor %}
        <tr class="filter-empty" hidden><td colspan="6" class="empty-cell">Ничего не найдено — измените поиск или фильтр.</td></tr>
      </tbody>
    </table>
  </div>
  <p class="hint">Красной подсветкой отмечен брак умершего датчика; <span class="t-max">тёплое</span> и <span class="t-min">холодное</span> — максимум и минимум среди видимых строк. Клик по заголовку — сортировка.</p>
</section>
{% endblock %}
'''

FILES["templates/backups.html"] = r'''
{% extends "base.html" %}
{% block title %}Бэкапы · Солигорск{% endblock %}
{% block content %}
<div class="page-head">
  <div>
    <h1>Бэкапы</h1>
    <p class="page-sub">Копии базы данных · всего: {{ items|length }}{% if items %} · {{ '%.2f'|format(items|sum(attribute='size_mb')) }} МБ{% endif %}</p>
  </div>
  <div class="page-actions">
    <form method="post" action="/admin/backup/create" class="inline-form" data-confirm="Создать бэкап прямо сейчас?">
      <button type="submit" class="btn btn-primary"><svg class="icon" aria-hidden="true"><use href="#i-plus"/></svg>Создать бэкап</button>
    </form>
  </div>
</div>

{% if items %}
<section class="card">
  <div class="table-controls">
    <div class="table-tools">
      <span class="search-wrap">
        <svg class="icon" aria-hidden="true"><use href="#i-search"/></svg>
        <input type="search" class="filter-input" data-filter-for="backups-tbody" placeholder="Поиск по имени файла…" aria-label="Фильтр по подстроке">
      </span>
      <span class="filter-count" data-filter-count="backups-tbody"></span>
    </div>
  </div>
  <div class="table-wrap">
    <table class="table sortable">
      <thead>
        <tr>
          <th scope="col" data-sort="text">Файл</th>
          <th scope="col" data-sort="num" class="num">Размер</th>
          <th scope="col" data-sort="text">Создан</th>
          <th scope="col" class="th-actions"><span class="visually-hidden">Действия</span></th>
        </tr>
      </thead>
      <tbody id="backups-tbody">
        {% for it in items %}
        <tr>
          <td class="mono">{{ it.name }}</td>
          <td class="num mono">{{ '%.2f'|format(it.size_mb) }} МБ</td>
          <td class="mono">{{ it.mtime }}</td>
          <td class="td-actions no-filter">
            <a class="btn btn-sm btn-ghost" href="/admin/backups/download/{{ it.name|urlencode }}" title="Скачать {{ it.name }}"><svg class="icon" aria-hidden="true"><use href="#i-down"/></svg><span class="btn-label">Скачать</span></a>
          </td>
        </tr>
        {% endfor %}
        <tr class="filter-empty" hidden><td colspan="4" class="empty-cell">Ничего не найдено.</td></tr>
      </tbody>
    </table>
  </div>
</section>
{% else %}
<section class="card empty">
  <svg class="icon icon-big" aria-hidden="true"><use href="#i-box"/></svg>
  <h2>Бэкапов пока нет</h2>
  <p>Создайте первую копию базы данных — она появится в этом списке.</p>
  <form method="post" action="/admin/backup/create" class="inline-form" data-confirm="Создать бэкап прямо сейчас?">
    <button type="submit" class="btn btn-primary"><svg class="icon" aria-hidden="true"><use href="#i-plus"/></svg>Создать бэкап</button>
  </form>
</section>
{% endif %}
{% endblock %}
'''

FILES["static/style.css"] = r'''
/* ============================================================
   «Солигорск» v3 — «инженерная бумага».
   Миллиметровая сетка, волосяные линии, моноширинные данные,
   один сигнальный акцент. Никаких градиентов и теней-блюров.
   ============================================================ */

/* --- Токены: светлая («бумага») --- */
:root {
  --bg: #f5f4ef;
  --surface: #fdfdfa;
  --surface-2: #f0efe8;
  --line: #e3e1d7;
  --line-strong: #cdc9bb;
  --ink: #191813;
  --muted: #6d6a5d;
  --faint: #9b9786;

  --accent: #d5481f;          /* сигнальный оранжевый, по чуть-чуть */
  --on-accent: #fdfdfa;
  --accent-soft: rgba(213, 72, 31, .14);

  --ok: #2e7d4f;      --ok-bg: #e7f0e9;
  --danger: #b93a2b;  --danger-bg: #f6e9e5;
  --warn: #8f6408;    --warn-bg: #f3ecd7;
  --warm: #bf4f28;    --cool: #2b6ea3;

  --grid-line: rgba(25, 24, 19, .05);
  --shadow-pop: 0 10px 28px rgba(25, 24, 19, .14);
  --r-s: 4px; --r-m: 6px; --r-l: 8px;

  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --mono: ui-monospace, "SF Mono", "Cascadia Mono", "JetBrains Mono", Consolas, "Liberation Mono", monospace;
}
/* --- Токены: тёмная («уголь») --- */
html[data-theme="dark"] {
  --bg: #131311;
  --surface: #1a1a17;
  --surface-2: #22221e;
  --line: #2c2b25;
  --line-strong: #3d3b32;
  --ink: #e9e7dc;
  --muted: #a29e8d;
  --faint: #6c6858;

  --accent: #ff6a3d;
  --on-accent: #131311;
  --accent-soft: rgba(255, 106, 61, .16);

  --ok: #6fca97;      --ok-bg: rgba(111, 202, 151, .12);
  --danger: #f08375;  --danger-bg: rgba(240, 131, 117, .12);
  --warn: #e3b254;    --warn-bg: rgba(227, 178, 84, .13);
  --warm: #f0895f;    --cool: #7ab5e4;

  --grid-line: rgba(233, 231, 220, .045);
  --shadow-pop: 0 12px 32px rgba(0, 0, 0, .5);
}

/* --- База --- */
*, *::before, *::after { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  font-family: var(--font);
  font-size: 14.5px;
  line-height: 1.55;
  color: var(--ink);
  background-color: var(--bg);
  /* миллиметровка: видна только в просветах между панелями */
  background-image:
    linear-gradient(var(--grid-line) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid-line) 1px, transparent 1px);
  background-size: 28px 28px;
}
::selection { background: var(--accent); color: var(--on-accent); }
img { max-width: 100%; }
h1, h2, h3 { margin: 0; line-height: 1.25; }
p { margin: 0; }
a { color: var(--accent); }
button, input, textarea, select { font: inherit; color: inherit; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
* { scrollbar-width: thin; scrollbar-color: var(--line-strong) transparent; }
.visually-hidden { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
.sprite { position: absolute; width: 0; height: 0; overflow: hidden; }
.icon { width: 18px; height: 18px; flex: none; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
html[data-theme="dark"] .t-hide-dark { display: none; }
html:not([data-theme="dark"]) .t-hide-light { display: none; }
.mono { font-family: var(--mono); font-size: 12.5px; }
.dash { color: var(--faint); }

/* --- Каркас --- */
.app { display: grid; grid-template-columns: 236px 1fr; min-height: 100vh; flex: 1; }
.sidebar {
  position: sticky; top: 0; height: 100vh; align-self: start;
  display: flex; flex-direction: column; gap: 20px;
  padding: 22px 14px 16px;
  background: var(--surface);
  border-right: 1px solid var(--line);
}
.brand { display: flex; align-items: center; gap: 10px; text-decoration: none; color: var(--ink); padding: 0 6px; }
.brand-mark { width: 30px; height: 30px; border-radius: var(--r-m); display: grid; place-items: center; background: var(--ink); color: var(--bg); }
.brand-mark .icon { width: 17px; height: 17px; }
.brand-text strong { display: block; font-size: 12.5px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }
.brand-text small { display: block; font-family: var(--mono); font-size: 10.5px; color: var(--faint); margin-top: 1px; }
.snav { display: flex; flex-direction: column; gap: 2px; }
.snav-link {
  position: relative;
  display: flex; align-items: center; gap: 10px;
  padding: 9px 10px; border-radius: var(--r-m);
  color: var(--muted); text-decoration: none;
  font-size: 13.5px; font-weight: 600;
}
.snav-link .icon { width: 15px; height: 15px; }
.snav-link:hover { color: var(--ink); background: var(--surface-2); }
.snav-link.active { color: var(--ink); background: var(--surface-2); box-shadow: inset 2px 0 0 var(--accent); }
.snav-badge { margin-left: auto; font-family: var(--mono); font-size: 10.5px; padding: 1px 6px; border: 1px solid var(--line-strong); border-radius: 3px; color: var(--muted); }
.sysinfo { margin-top: auto; border: 1px solid var(--line); border-radius: var(--r-m); padding: 11px 12px; font-size: 11.5px; color: var(--muted); display: flex; flex-direction: column; gap: 8px; }
.sys-row { display: flex; align-items: center; gap: 8px; }
.sys-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; background: var(--faint); }
.sys-dot.on { background: var(--ok); }
.sys-dot.off { background: var(--danger); }
.sys-line { color: var(--ink); font-weight: 600; font-size: 12px; }
.sys-foot { display: flex; flex-direction: column; gap: 3px; font-family: var(--mono); font-size: 10.5px; color: var(--faint); }
.shell { display: flex; flex-direction: column; min-width: 0; }
.topbar {
  position: sticky; top: 0; z-index: 40;
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 11px 26px;
  background: var(--surface);
  border-bottom: 1px solid var(--line);
}
.brand-m { display: none; }
.topbar-status { margin-left: auto; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.main { flex: 1; width: 100%; max-width: 1240px; margin-inline: auto; padding: 26px 26px 52px; }
.main > * + * { margin-top: 18px; }
.footer {
  width: 100%; max-width: 1240px; margin-inline: auto;
  padding: 13px 26px;
  border-top: 1px solid var(--line);
  color: var(--faint);
  font-family: var(--mono); font-size: 11px;
  display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap;
}
.docknav { display: none; }

/* --- Чипы статуса --- */
.chip {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 4px 9px; border-radius: var(--r-s);
  border: 1px solid var(--line);
  background: var(--surface);
  font-family: var(--mono); font-size: 11.5px;
  color: var(--muted); white-space: nowrap;
}
.chip .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--faint); }
.chip-ok .dot { background: var(--ok); }
.chip-bad .dot { background: var(--danger); }
.chip-bad { color: var(--danger); border-color: var(--danger); }
.chip-extra { color: var(--muted); }

/* --- Кнопки --- */
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 7px;
  padding: 7px 13px; border-radius: var(--r-m);
  border: 1px solid var(--line-strong);
  background: var(--surface); color: var(--ink);
  font-size: 13px; font-weight: 600; line-height: 1.25;
  text-decoration: none; cursor: pointer; user-select: none;
  transition: background-color .12s ease, border-color .12s ease, color .12s ease;
}
.btn:hover { background: var(--surface-2); border-color: var(--ink); }
.btn:active { transform: translateY(1px); }
.btn .icon { width: 15px; height: 15px; }
.btn-primary { background: var(--ink); border-color: var(--ink); color: var(--bg); }
.btn-primary:hover { background: var(--ink); border-color: var(--ink); opacity: .88; }
.btn-ghost { background: transparent; border-color: transparent; }
.btn-ghost:hover { background: var(--surface-2); border-color: var(--line-strong); }
.btn-danger { background: var(--danger); border-color: var(--danger); color: #fff; }
.btn-danger:hover { background: var(--danger); border-color: var(--danger); opacity: .9; }
.btn-danger-ghost { background: transparent; border-color: transparent; color: var(--danger); }
.btn-danger-ghost:hover { background: var(--danger-bg); border-color: var(--danger); }
.btn-test-on { background: var(--warn-bg); border-color: var(--warn); color: var(--warn); }
.btn-sm { padding: 4px 9px; font-size: 12px; border-radius: var(--r-s); }
.btn-icon { padding: 5px; }
.btn-block { width: 100%; margin-top: 14px; }
.inline-form { display: inline-flex; margin: 0; }
.btn-del:hover { color: var(--danger); border-color: var(--danger); background: var(--danger-bg); }
.btn.copied { color: var(--ok); border-color: var(--ok); }

/* --- Заголовок страницы --- */
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.page-head h1 { font-size: 26px; font-weight: 700; letter-spacing: -0.02em; }
.page-sub { margin-top: 4px; font-size: 13px; color: var(--muted); }
.page-actions { display: flex; gap: 8px; flex-wrap: wrap; }

/* --- Карточки и заголовки секций --- */
.card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-l); padding: 18px 20px; }
.card-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
.card-head h2 {
  display: inline-flex; align-items: center; gap: 8px;
  font-size: 12px; font-weight: 700;
  letter-spacing: .09em; text-transform: uppercase; color: var(--ink);
}
.card-head h2 .icon { width: 14px; height: 14px; color: var(--faint); }

/* --- Статы: единая планка с волосяными разделителями --- */
.stats-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 1px; background: var(--line);
  border: 1px solid var(--line); border-radius: var(--r-l); overflow: hidden;
}
.stat { background: var(--surface); padding: 14px 16px; }
.stat-label { font-size: 10.5px; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; color: var(--muted); }
.stat-value {
  margin-top: 7px;
  font-family: var(--mono); font-size: 24px; font-weight: 600;
  letter-spacing: -.02em; font-variant-numeric: tabular-nums;
}
.stat-value .unit { font-size: 12px; font-weight: 500; color: var(--muted); }
.stat-sub { margin-top: 3px; font-size: 11.5px; color: var(--faint); }
.stat-trend.up { color: var(--warm); }
.stat-trend.down { color: var(--cool); }
.stat-trend.flat { color: var(--muted); }
.stat-trend.up::before { content: "↑ "; }
.stat-trend.down::before { content: "↓ "; }
.stat-trend.flat::before { content: "→ "; color: var(--faint); }

/* --- Таблицы --- */
.table-wrap { border: 1px solid var(--line); border-radius: var(--r-m); overflow: auto; max-height: 66vh; background: var(--surface); }
.table-wrap-flush { max-height: none; }
.table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 13px; }
.table th {
  position: sticky; top: 0; z-index: 5;
  background: var(--surface-2);
  text-align: left; padding: 8px 12px;
  font-size: 10.5px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
  color: var(--muted);
  border-bottom: 1px solid var(--line); white-space: nowrap;
}
.table td { padding: 8px 12px; border-bottom: 1px solid var(--line); vertical-align: middle; }
.table tbody tr:last-child td { border-bottom: 0; }
.table tbody tr:hover td { background: var(--surface-2); }
.table th[data-sort] { cursor: pointer; user-select: none; padding-right: 22px; }
.table th[data-sort]::after {
  content: ""; position: absolute; right: 8px; top: 50%; margin-top: -3px;
  border: 3.5px solid transparent; border-bottom-color: var(--faint); opacity: .6;
}
.table th[data-sort]:hover { color: var(--ink); }
.table th.sort-asc::after { border-bottom-color: var(--accent); opacity: 1; }
.table th.sort-desc::after { border-bottom-color: transparent; border-top-color: var(--accent); opacity: 1; }
.num { text-align: right; font-family: var(--mono); font-size: 12.5px; font-variant-numeric: tabular-nums; }
.td-actions, .th-actions { text-align: right; white-space: nowrap; width: 1%; }
.td-actions .btn, .td-actions .inline-form { vertical-align: middle; }
tr[data-bad="1"] td { background: var(--danger-bg); }
tr[data-bad="1"]:hover td { background: var(--danger-bg); }
tr[hidden] { display: none; }
.empty-row td { text-align: center; color: var(--faint); padding: 24px 12px; }
.empty-cell { text-align: center; color: var(--faint); padding: 18px 12px; }
.summary-table td { font-variant-numeric: tabular-nums; }
.summary-table td:first-child { color: var(--muted); font-weight: 600; font-size: 12.5px; }
.t-max { color: var(--warm); font-weight: 600; }
.t-max::after { content: " ▲"; font-size: 9px; }
.t-min { color: var(--cool); font-weight: 600; }
.t-min::after { content: " ▼"; font-size: 9px; }

/* --- Пользователи --- */
.cell-user { display: flex; align-items: center; gap: 10px; min-width: 220px; }
.avatar {
  width: 30px; height: 30px; border-radius: var(--r-m);
  display: grid; place-items: center; flex: none;
  background: var(--surface-2); border: 1px solid var(--line-strong);
  color: var(--ink); font-family: var(--mono); font-size: 12px; font-weight: 600;
}
.user-meta { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.user-name { font-weight: 600; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 220px; }
.user-tag { color: var(--faint); font-size: 11px; }
.user-tag a { color: var(--accent); text-decoration: none; }
.user-tag a:hover { text-decoration: underline; }

/* --- Фильтры --- */
.table-controls { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.chips { display: flex; gap: 4px; flex-wrap: wrap; }
.fchip {
  padding: 4px 11px; border-radius: var(--r-s);
  border: 1px solid var(--line); background: var(--surface);
  color: var(--muted); font-size: 12px; font-weight: 600; cursor: pointer;
}
.fchip:hover { color: var(--ink); border-color: var(--line-strong); }
.fchip.active { background: var(--ink); border-color: var(--ink); color: var(--bg); }
.table-tools { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.search-wrap { position: relative; display: inline-flex; align-items: center; }
.search-wrap .icon { position: absolute; left: 9px; width: 14px; height: 14px; color: var(--faint); pointer-events: none; }
.filter-input { padding: 7px 11px 7px 30px; border-radius: var(--r-m); border: 1px solid var(--line-strong); background: var(--surface); color: var(--ink); font-size: 13px; width: 240px; max-width: 100%; }
.filter-input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.filter-input::placeholder { color: var(--faint); }
.filter-count { font-family: var(--mono); font-size: 11px; color: var(--faint); white-space: nowrap; }

/* --- Формы --- */
label { font-size: 12px; font-weight: 700; color: var(--muted); letter-spacing: .02em; }
input[type="text"], input[type="password"], input[type="number"], input[type="search"], textarea {
  width: 100%; padding: 8px 11px; border-radius: var(--r-m);
  border: 1px solid var(--line-strong); background: var(--surface); color: var(--ink); font-size: 14px;
}
input:focus, textarea:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
input::placeholder, textarea::placeholder { color: var(--faint); }
textarea { resize: vertical; min-height: 84px; }
.field-row { display: flex; align-items: flex-end; gap: 12px; flex-wrap: wrap; }
.field { flex: 1 1 150px; display: flex; flex-direction: column; gap: 6px; }
.field-row .btn { flex: 0 0 auto; }
.form-foot { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; margin-top: 10px; }
.char-counter { font-family: var(--mono); font-size: 11px; color: var(--faint); }
.char-counter.near-limit { color: var(--warn); font-weight: 700; }
.hint { font-size: 12px; color: var(--faint); }
.warn-text { color: var(--warn); }

/* --- Бейджи, баннер --- */
.badge {
  display: inline-flex; align-items: center;
  padding: 3px 7px; border-radius: 3px;
  font-size: 10.5px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
}
.badge-ok { background: var(--ok-bg); color: var(--ok); }
.badge-danger { background: var(--danger-bg); color: var(--danger); }
.badge-warn { background: var(--warn-bg); color: var(--warn); }
.banner {
  display: flex; gap: 10px; align-items: flex-start;
  padding: 11px 14px; border-radius: var(--r-m);
  background: var(--warn-bg); color: var(--warn);
  border: 1px solid var(--warn);
  font-size: 13px; font-weight: 600;
}
.banner .icon { margin-top: 2px; }

/* --- Графики --- */
.charts-controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.charts-updated { font-family: var(--mono); font-size: 11px; color: var(--faint); white-space: nowrap; }
.charts-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 330px), 1fr)); gap: 14px; counter-reset: chart; }
.chart {
  margin: 0; padding: 10px;
  border: 1px solid var(--line); border-radius: var(--r-m);
  background: var(--surface);
  transition: border-color .12s ease;
}
.chart:hover { border-color: var(--line-strong); }
.chart figcaption {
  font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
  color: var(--muted); margin-bottom: 8px;
  counter-increment: chart;
}
.chart figcaption::before { content: counter(chart, decimal-leading-zero) " · "; color: var(--faint); }
.chart img { display: block; width: 100%; height: auto; border-radius: var(--r-s); background: var(--surface); min-height: 140px; cursor: zoom-in; }
.quick-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.lightbox {
  position: fixed; inset: 0; z-index: 200;
  background: rgba(19, 19, 17, .88);
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 24px; cursor: zoom-out;
}
.lightbox img { max-width: 96vw; max-height: 82vh; border-radius: var(--r-s); background: var(--surface); }
.lightbox-cap { color: #e9e7dc; margin-top: 10px; font-family: var(--mono); font-size: 12px; }

/* --- Модалка --- */
.modal-backdrop { position: fixed; inset: 0; z-index: 100; display: flex; align-items: center; justify-content: center; padding: 20px; background: rgba(19, 19, 17, .55); }
.modal-backdrop[hidden] { display: none; }
.modal { width: 100%; max-width: 400px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-l); box-shadow: var(--shadow-pop); padding: 20px; }
.modal-title { font-size: 14px; font-weight: 700; letter-spacing: .02em; margin-bottom: 8px; }
.modal-text { font-size: 13.5px; color: var(--muted); }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }
body.modal-open { overflow: hidden; }

/* --- Пустое состояние --- */
.empty { text-align: center; padding: 44px 20px; }
.empty .icon-big { display: block; width: 36px; height: 36px; margin: 0 auto 10px; color: var(--faint); stroke-width: 1.4; }
.empty h2 { margin: 0 0 4px; font-size: 15px; }
.empty p { color: var(--muted); font-size: 13px; margin-bottom: 16px; }

/* --- Вход --- */
.login-page { flex: 1; display: flex; align-items: center; justify-content: center; padding: 24px 16px; }
.login-card {
  width: 100%; max-width: 340px;
  background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
  box-shadow: var(--shadow-pop);
  padding: 30px 28px; text-align: center;
}
.login-logo { width: 46px; height: 46px; margin: 0 auto 16px; border-radius: var(--r-m); display: grid; place-items: center; background: var(--ink); color: var(--bg); }
.login-logo .icon { width: 24px; height: 24px; }
.login-card h1 { font-size: 16px; font-weight: 700; letter-spacing: .18em; text-transform: uppercase; }
.login-sub { margin: 6px 0 22px; font-family: var(--mono); font-size: 10.5px; letter-spacing: .06em; text-transform: uppercase; color: var(--faint); }
.login-form { text-align: left; }
.login-form label { display: block; margin-bottom: 6px; font-size: 10.5px; letter-spacing: .08em; text-transform: uppercase; }
.password-wrap { position: relative; }
.password-wrap input { padding-right: 40px; }
.pw-toggle {
  position: absolute; right: 4px; top: 50%; transform: translateY(-50%);
  display: grid; place-items: center; width: 30px; height: 30px;
  border: 0; border-radius: var(--r-s); background: transparent; color: var(--faint); cursor: pointer;
}
.pw-toggle:hover { color: var(--ink); background: var(--surface-2); }
.pw-toggle .icon { width: 16px; height: 16px; }
.pw-toggle .eye-off { display: none; }
.password-wrap.pw-visible .eye-off { display: block; }
.password-wrap.pw-visible .eye-on { display: none; }
.login-foot { margin-top: 18px; font-family: var(--mono); font-size: 10.5px; color: var(--faint); }

/* --- Мобильная версия --- */
@media (max-width: 920px) {
  .app { grid-template-columns: 1fr; }
  .sidebar { display: none; }
  .brand-m { display: inline-flex; align-items: center; gap: 8px; font-size: 12px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: var(--ink); text-decoration: none; }
  .brand-m .mark { width: 26px; height: 26px; border-radius: var(--r-s); display: grid; place-items: center; background: var(--ink); color: var(--bg); }
  .brand-m .mark .icon { width: 15px; height: 15px; }
  .topbar { padding: 10px 14px; }
  .topbar .btn-label { font-size: 11.5px; }
  .hide-sm { display: none; }
  .docknav {
    display: flex; position: fixed; left: 0; right: 0; bottom: 0; z-index: 60;
    background: var(--surface); border-top: 1px solid var(--line);
    padding: 5px 6px calc(5px + env(safe-area-inset-bottom));
  }
  .dock-link {
    flex: 1; position: relative;
    display: flex; flex-direction: column; align-items: center; gap: 3px;
    padding: 7px 2px 5px;
    color: var(--muted); text-decoration: none;
    font-size: 10px; font-weight: 600; letter-spacing: .04em;
  }
  .dock-link .icon { width: 19px; height: 19px; }
  .dock-link.active { color: var(--ink); }
  .dock-link.active::before { content: ""; position: absolute; top: -1px; left: 20%; right: 20%; height: 2px; background: var(--accent); }
  .main { padding: 16px 14px 100px; }
  .footer { padding: 12px 14px 96px; justify-content: center; text-align: center; }
  .page-head h1 { font-size: 21px; }
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
  .stat { padding: 12px; }
  .stat-value { font-size: 20px; }
  .card { padding: 14px 12px; }
  .table { font-size: 12.5px; }
  .table th, .table td { padding: 7px 9px; }
  .mono { font-size: 11.5px; }
  .num { font-size: 12px; }
  .table-tools { width: 100%; }
  .search-wrap { flex: 1; }
  .filter-input { width: 100%; }
  .charts-grid { grid-template-columns: 1fr; }
  .table-wrap { max-height: 70vh; }
  .cell-user { min-width: 170px; }
  .user-name { max-width: 140px; }
}
@media (max-width: 420px) {
  .chip-label { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition: none !important; }
}
'''

FILES["static/script.js"] = r'''
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
})();
'''


def main():
    root = os.path.expanduser(sys.argv[1]) if len(sys.argv) > 1 else "."
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        sys.exit("Ошибка: папка не существует: " + root)
    base = os.path.join(root, WEB_SUBDIR) if WEB_SUBDIR else root

    print("Установка админки v3 («инженерная бумага») в: " + base)
    total = 0
    for rel in sorted(FILES):
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        text = FILES[rel].lstrip("\n")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        n = len(text.encode("utf-8"))
        total += n
        print("  + {:<32s} {:>7d} байт".format(rel, n))

    print("")
    print("Готово: {} файлов, {} байт.".format(len(FILES), total))
    print("Перезапусти Flask. Патч TestV4.py для имён/трендов по-прежнему нужен.")


if __name__ == "__main__":
    main()
