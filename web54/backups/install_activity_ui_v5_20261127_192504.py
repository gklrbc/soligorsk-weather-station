#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Инсталлятор страницы «Активность» — 3D-созвездия пользователей бота
для веб-админки домашней метеостанции «Солигорск».

Создаёт три файла:
    templates/activity.html  — страница (наследует base.html, блоки title/content)
    static/activity.css      — стили страницы (общий style.css не трогается)
    static/activity3d.js     — 3D-сцена на глобальном THREE r128
                                (свой bloom, шейдерное ядро, объёмные
                                 галактики, чёрная дыра с джетами,
                                 параллакс фона)

Использование:
    python3 install_activity_ui.py /путь/к/проекту/станции
"""

import os
import sys

FILES = {}

FILES["templates/activity.html"] = r'''{% extends "base.html" %}
{% block title %}Активность{% endblock %}
{% block content %}
<div class="activity-stage" id="activity-stage">
    <div class="activity-canvas" id="activity-canvas"></div>

    <header class="hud hud-title">
        <div class="hud-over">Солигорск · метеостанция</div>
        <h1 class="hud-h1">Созвездие активности</h1>
        <div class="hud-stats">
            <span><b id="stat-users">0</b>&nbsp;<span id="stat-users-word">пользователей</span></span>
            <span class="stat-sep"></span>
            <span><b id="stat-events">0</b>&nbsp;<span id="stat-events-word">событий</span>&nbsp;за 24 ч</span>
        </div>
        <div class="hud-stream"><i class="dot" id="stream-dot"></i><span id="stream-label">подключение…</span></div>
    </header>

    <nav class="hud hud-modes" aria-label="Раскладка созвездия">
        <div class="mode-switch">
            <button type="button" data-mode="orbits" aria-pressed="false">Орбиты</button>
            <button type="button" data-mode="sphere" aria-pressed="false">Сфера</button>
            <button type="button" data-mode="spiral" aria-pressed="false">Спираль</button>
            <button type="button" data-mode="galaxy" aria-pressed="false">Галактики</button>
        </div>
    </nav>

    <div class="hud hud-legend">
        <span class="legend-item"><i class="sw sw-live"></i>активный</span>
        <span class="legend-item"><i class="sw sw-blocked"></i>заблокирован</span>
        <span class="legend-item"><i class="sw sw-pulse"></i>сообщение</span>
    </div>

    <div class="hud hud-actions">
        <button type="button" class="icon-btn" id="view-reset" title="Сбросить вид" aria-label="Сбросить вид">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
                 stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M20 12a8 8 0 1 1-2.9-6.16"></path>
                <path d="M20 4v4.3h-4.3"></path>
            </svg>
        </button>
    </div>

    <div class="hud hud-hint">
        <span class="hint-desktop">Тяните — вращение · колесо — масштаб · двойной клик — сброс</span>
        <span class="hint-touch">Палец — вращение · щипок — масштаб · касание узла — детали</span>
    </div>

    <div class="activity-tooltip" id="activity-tooltip" hidden></div>

    <div class="activity-overlay is-loading" id="activity-overlay">
        <div class="overlay-inner">
            <div class="overlay-spinner" aria-hidden="true"></div>
            <p id="activity-overlay-text">Приём телеметрии…</p>
        </div>
    </div>
</div>

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Golos+Text:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{{ url_for('static', filename='activity.css') }}">
<script src="{{ url_for('static', filename='vendor/three.min.js') }}"></script>
<script src="{{ url_for('static', filename='activity3d.js') }}"></script>
{% endblock %}
'''

FILES["static/activity.css"] = r'''/* Страница «Активность»: портал-иллюминатор со сценой и HUD.
   Стили изолированы классом .activity-stage — общий style.css не затрагивается. */

.activity-stage {
    position: relative;
    width: 100%;
    height: calc(100vh - 150px);
    min-height: 430px;
    margin: 12px 0;
    border-radius: 18px;
    overflow: hidden;
    background: #04070a;
    border: 1px solid rgba(255, 255, 255, 0.10);
    box-shadow: 0 22px 60px rgba(0, 0, 0, 0.55), inset 0 0 0 1px rgba(255, 255, 255, 0.03);
    font-family: "Golos Text", "Segoe UI", -apple-system, sans-serif;
    color: #e8f3ee;
}

/* Мягкие скримы сверху и снизу — чтобы HUD читался поверх ярких звёзд */
.activity-stage::before,
.activity-stage::after {
    content: "";
    position: absolute; left: 0; right: 0; height: 130px;
    pointer-events: none; z-index: 2;
}
.activity-stage::before { top: 0;    background: linear-gradient(180deg, rgba(4, 7, 10, 0.55), rgba(4, 7, 10, 0)); }
.activity-stage::after  { bottom: 0; background: linear-gradient(0deg,   rgba(4, 7, 10, 0.5),  rgba(4, 7, 10, 0)); }

.activity-canvas { position: absolute; inset: 0; }
.activity-canvas canvas { display: block; cursor: grab; }

/* ---------- HUD ---------- */
.hud { position: absolute; z-index: 3; }

.hud-title {
    top: 16px; left: 18px;
    max-width: min(460px, calc(100% - 36px));
    pointer-events: none;
    text-shadow: 0 1px 18px rgba(0, 0, 0, 0.8), 0 0 2px rgba(0, 0, 0, 0.6);
}
.hud-over {
    font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase;
    color: rgba(232, 243, 238, 0.55);
}
.hud-h1 {
    margin: 3px 0 7px; font-size: 22px; font-weight: 600; letter-spacing: 0.01em;
    color: #f4fbf8;
}
.hud-stats {
    display: flex; align-items: center; gap: 10px;
    font-size: 13px; color: rgba(232, 243, 238, 0.78);
}
.hud-stats b {
    color: #ffd9a4; font-weight: 600; font-variant-numeric: tabular-nums;
}
.hud-stats b.flash { animation: stat-flash 0.9s ease-out; }
@keyframes stat-flash {
    0%   { color: #ffffff; text-shadow: 0 0 16px rgba(255, 190, 110, 0.95); }
    100% { color: #ffd9a4; text-shadow: none; }
}
.stat-sep { width: 1px; height: 12px; background: rgba(232, 243, 238, 0.25); }

.hud-stream {
    display: flex; align-items: center; gap: 7px; margin-top: 9px;
    font-size: 12px; color: rgba(232, 243, 238, 0.7);
}
.dot { width: 8px; height: 8px; border-radius: 50%; background: #8a9490; flex: none; }
.dot-live {
    background: #7fe7c1; box-shadow: 0 0 9px rgba(127, 231, 193, 0.95);
    animation: dot-breathe 2.4s ease-in-out infinite;
}
.dot-off { background: #e05252; animation: dot-blink 1.1s steps(2, start) infinite; }
@keyframes dot-breathe { 50% { opacity: 0.5; } }
@keyframes dot-blink   { 50% { opacity: 0.2; } }

/* Переключатель режимов */
.hud-modes { top: 18px; right: 18px; }
.mode-switch {
    display: flex; gap: 3px; padding: 4px; border-radius: 13px;
    background: rgba(6, 10, 14, 0.6);
    border: 1px solid rgba(255, 255, 255, 0.09);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
}
.mode-switch button {
    appearance: none; border: 0; background: transparent;
    color: rgba(232, 243, 238, 0.72);
    font: 500 13px/1 "Golos Text", "Segoe UI", sans-serif;
    padding: 9px 12px; border-radius: 9px; cursor: pointer;
    transition: color 0.18s ease, background 0.18s ease, box-shadow 0.18s ease;
}
.mode-switch button:hover { color: #ffffff; }
.mode-switch button:focus-visible { outline: 1px solid rgba(255, 169, 88, 0.7); outline-offset: 1px; }
.mode-switch button.active {
    color: #ffd9a4;
    background: rgba(255, 169, 88, 0.16);
    box-shadow: inset 0 0 0 1px rgba(255, 169, 88, 0.38), 0 0 18px rgba(255, 169, 88, 0.12);
}

/* Легенда, действия, подсказка */
.hud-legend {
    left: 18px; bottom: 16px;
    display: flex; flex-wrap: wrap; gap: 14px;
    padding: 8px 13px; border-radius: 12px;
    background: rgba(6, 10, 14, 0.58);
    border: 1px solid rgba(255, 255, 255, 0.08);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    font-size: 12px; color: rgba(232, 243, 238, 0.78);
}
.legend-item { display: flex; align-items: center; gap: 7px; }
.sw { width: 9px; height: 9px; display: inline-block; flex: none; }
.sw-live    { border-radius: 50%; background: #7fe7c1; box-shadow: 0 0 8px rgba(127, 231, 193, 0.9); }
.sw-blocked { border-radius: 50%; background: #c95454; opacity: 0.85; }
.sw-pulse   { background: #ffc16e; border-radius: 50% 0 50% 50%; transform: rotate(-45deg);
              box-shadow: 0 0 8px rgba(255, 193, 110, 0.9); }

.hud-actions { right: 18px; bottom: 16px; }
.icon-btn {
    display: flex; align-items: center; justify-content: center;
    width: 40px; height: 40px; border-radius: 12px;
    border: 1px solid rgba(255, 255, 255, 0.09);
    background: rgba(6, 10, 14, 0.6);
    color: rgba(232, 243, 238, 0.85); cursor: pointer;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    transition: color 0.18s ease, border-color 0.18s ease, transform 0.12s ease;
}
.icon-btn:active { transform: scale(0.94); }
.icon-btn:hover { color: #ffd9a4; border-color: rgba(255, 169, 88, 0.45); }
.icon-btn:focus-visible { outline: 1px solid rgba(255, 169, 88, 0.7); outline-offset: 1px; }
.icon-btn svg { width: 19px; height: 19px; }

.hud-hint {
    left: 50%; bottom: 20px; transform: translateX(-50%);
    font-size: 12px; color: rgba(232, 243, 238, 0.5);
    pointer-events: none; white-space: nowrap;
    text-shadow: 0 1px 10px rgba(0, 0, 0, 0.8);
}
.hint-touch { display: none; }
@media (hover: none) and (pointer: coarse) {
    .hint-desktop { display: none; }
    .hint-touch { display: inline; }
}

/* ---------- Тултип узла ---------- */
.activity-tooltip {
    position: absolute; z-index: 5; top: 0; left: 0;
    min-width: 200px; max-width: 260px;
    padding: 11px 13px; border-radius: 13px;
    background: rgba(7, 12, 16, 0.88);
    border: 1px solid rgba(255, 255, 255, 0.11);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    box-shadow: 0 14px 40px rgba(0, 0, 0, 0.6);
    pointer-events: none;
}
.activity-tooltip[hidden] { display: none; }
.tip-head { display: flex; align-items: center; gap: 8px; margin-bottom: 3px; }
.tip-name { font-weight: 600; font-size: 14px; color: #f2fbf7; }
.tip-badge {
    font-size: 10px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase;
    color: #ffb1b1; border: 1px solid rgba(224, 82, 82, 0.5);
    border-radius: 6px; padding: 2px 6px; white-space: nowrap;
}
.tip-sub { font-size: 11px; color: rgba(232, 243, 238, 0.55); margin-bottom: 8px; }
.tip-row {
    display: flex; justify-content: space-between; gap: 14px;
    font-size: 12px; color: rgba(232, 243, 238, 0.75); padding: 2px 0;
}
.tip-row b { color: #ffd9a4; font-weight: 600; font-variant-numeric: tabular-nums; }
.tip-cap {
    margin-top: 9px; font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase;
    color: rgba(232, 243, 238, 0.45);
}
.tip-chart { display: block; width: 224px; height: 44px; margin-top: 5px; }

/* ---------- Оверлей: загрузка / пустое состояние ---------- */
.activity-overlay {
    position: absolute; inset: 0; z-index: 4;
    display: flex; align-items: center; justify-content: center;
    background: rgba(4, 7, 10, 0.6);
}
.activity-overlay[hidden] { display: none; }
.overlay-inner {
    text-align: center; max-width: 330px; padding: 0 20px;
    color: rgba(232, 243, 238, 0.82); font-size: 14px; line-height: 1.55;
    text-shadow: 0 1px 12px rgba(0, 0, 0, 0.8);
}
.overlay-inner p { margin: 0; }
.overlay-spinner {
    width: 26px; height: 26px; margin: 0 auto 14px; border-radius: 50%;
    border: 2px solid rgba(255, 193, 110, 0.25); border-top-color: #ffc16e;
    animation: overlay-spin 0.9s linear infinite;
}
.activity-overlay:not(.is-loading) .overlay-spinner { display: none; }
@keyframes overlay-spin { to { transform: rotate(360deg); } }

/* ---------- Мобильная раскладка (~390 px) ---------- */
@media (max-width: 640px) {
    .activity-stage { height: calc(100vh - 110px); min-height: 360px; border-radius: 14px; }
    .hud-title { top: 13px; left: 12px; right: 12px; }
    .hud-h1 { font-size: 18px; }
    .hud-stats { font-size: 12px; gap: 8px; flex-wrap: wrap; }
    .hud-modes {
        top: auto; right: auto; left: 50%; bottom: 68px;
        transform: translateX(-50%);
    }
    .mode-switch button { padding: 8px 9px; font-size: 11.5px; }
    .hud-legend {
        left: 12px; right: 64px; bottom: 12px; gap: 10px;
        font-size: 11px; padding: 7px 10px;
    }
    .hud-actions { right: 12px; bottom: 12px; }
    .hud-hint { display: none; }
    .tip-chart { width: 200px; }
    .activity-tooltip { min-width: 180px; }
}
'''

FILES["static/activity3d.js"] = r'''/*
 * «Созвездие активности» — 3D-визуализация событий Telegram-бота
 * метеостанции «Солигорск». Vanilla JS поверх глобального THREE (r128).
 *
 * Контракт данных:
 *   GET /admin/activity/data   -> { ok, users: [{ uid, name, username, act, blocked, times }] }
 *   SSE /admin/activity/stream -> event: snapshot (тот же JSON) + безымянные
 *                                 data-события { uid, time }.
 *
 * Режим «Галактики»: в центре — чёрная дыра (горизонт событий, фотонное
 * кольцо, аккреционный диск с доплеровским бимингом, полярные джеты),
 * вокруг — приглушённая спиральная галактика «угол -> глубокий синий»,
 * пользователи — маленькие объёмные галактики из частиц.
 */
(function () {
    'use strict';

    // ------------------------------------------------------------------
    // Настройки
    // ------------------------------------------------------------------
    var DATA_URL   = '/admin/activity/data';
    var STREAM_URL = '/admin/activity/stream';
    var POLL_MS    = 15000;
    var LS_KEY     = 'activity.viewMode';

    var MODES = ['orbits', 'sphere', 'spiral', 'galaxy'];

    var ORBIT_RADII   = [8.5, 12.5, 16.5];
    var SPHERE_R      = 13.0;
    var DEFAULT_DIST  = 36;
    var INTRO_DIST    = 84;
    var MIN_DIST      = 15;
    var MAX_DIST      = 82;
    var TILT_DEFAULT  = 0.30;

    var COLOR = {
        core:   0xffb45e,
        hot:    0xfff3dc,
        pulse:  0xffc16e,
        guide:  0x8fe9cd
    };

    // ------------------------------------------------------------------
    // Утилиты
    // ------------------------------------------------------------------
    function clamp(v, a, b) { return v < a ? a : (v > b ? b : v); }
    function lerp(a, b, t) { return a + (b - a) * t; }

    function easeInQuad(t) { return t * t; }
    function easeOutCubic(t) { return 1 - Math.pow(1 - t, 3); }
    function easeOutBack(t) {
        var c = 1.70158, u = t - 1;
        return 1 + (c + 1) * u * u * u + c * u * u;
    }

    function hashUid(uid) {
        var h = 2166136261 >>> 0;
        var s = String(uid);
        for (var i = 0; i < s.length; i++) {
            h ^= s.charCodeAt(i);
            h = Math.imul(h, 16777619) >>> 0;
        }
        return h >>> 0;
    }
    function mulberry32(seed) {
        var a = seed >>> 0;
        return function () {
            a = (a + 0x6D2B79F5) | 0;
            var t = Math.imul(a ^ (a >>> 15), 1 | a);
            t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
        };
    }
    function gauss(rnd) {
        var u = Math.max(rnd(), 1e-7);
        var v = rnd();
        return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
    }

    function plural(n, forms) {
        var m10 = n % 10, m100 = n % 100;
        if (m10 === 1 && m100 !== 11) return forms[0];
        if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return forms[1];
        return forms[2];
    }

    function formatAct(act) {
        if (!act) return '—';
        var m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2})/.exec(act);
        return m ? (m[3] + '.' + m[2] + '.' + m[1] + ', ' + m[4]) : String(act);
    }

    function displayLabel(u) {
        if (u.name) return String(u.name);
        if (u.username) return '@' + u.username;
        return 'id ' + u.uid;
    }
    function shortLabel(text, max) {
        text = String(text);
        return text.length > max ? text.slice(0, max - 1) + '…' : text;
    }

    // ------------------------------------------------------------------
    // DOM и состояние
    // ------------------------------------------------------------------
    var stage       = document.getElementById('activity-stage');
    var canvasHost  = document.getElementById('activity-canvas');
    var tooltip     = document.getElementById('activity-tooltip');
    var overlay     = document.getElementById('activity-overlay');
    var overlayText = document.getElementById('activity-overlay-text');
    var statUsers   = document.getElementById('stat-users');
    var statUsersW  = document.getElementById('stat-users-word');
    var statEvents  = document.getElementById('stat-events');
    var statEventsW = document.getElementById('stat-events-word');
    var streamDot   = document.getElementById('stream-dot');
    var streamLabel = document.getElementById('stream-label');
    var modeButtons = Array.prototype.slice.call(document.querySelectorAll('.mode-switch button'));
    var resetBtn    = document.getElementById('view-reset');

    var state = {
        mode: 'orbits',
        loaded: false,
        live: null,
        userCount: 0,
        eventTotal: 0,
        hoveredUid: null,
        pinnedUid: null
    };

    // ------------------------------------------------------------------
    // Рендерер, сцена, группы
    // ------------------------------------------------------------------
    var renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(0x04070a, 1);
    canvasHost.appendChild(renderer.domElement);

    var scene  = new THREE.Scene();
    var camera = new THREE.PerspectiveCamera(55, 1, 0.1, 600);

    var bgGroup   = new THREE.Group();   // небо: вращается с параллаксом
    scene.add(bgGroup);
    var rootGroup  = new THREE.Group();  // вращается перетаскиванием
    scene.add(rootGroup);
    var nodesGroup = new THREE.Group();  // медленно вращается сам
    rootGroup.add(nodesGroup);
    var guides  = new THREE.Group();
    nodesGroup.add(guides);
    var fxGroup = new THREE.Group();
    nodesGroup.add(fxGroup);

    // ------------------------------------------------------------------
    // GLSL: общий 3D-шум (Ashima simplex, public domain)
    // ------------------------------------------------------------------
    var GLSL_NOISE = `
vec3 mod289(vec3 x){ return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 mod289(vec4 x){ return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 permute(vec4 x){ return mod289(((x * 34.0) + 1.0) * x); }
vec4 taylorInvSqrt(vec4 r){ return 1.79284291400159 - 0.85373472095314 * r; }
float snoise(vec3 v){
    const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
    const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
    vec3 i  = floor(v + dot(v, C.yyy));
    vec3 x0 = v - i + dot(i, C.xxx);
    vec3 g = step(x0.yzx, x0.xyz);
    vec3 l = 1.0 - g;
    vec3 i1 = min(g.xyz, l.zxy);
    vec3 i2 = max(g.xyz, l.zxy);
    vec3 x1 = x0 - i1 + C.xxx;
    vec3 x2 = x0 - i2 + C.yyy;
    vec3 x3 = x0 - D.yyy;
    i = mod289(i);
    vec4 p = permute(permute(permute(
              i.z + vec4(0.0, i1.z, i2.z, 1.0))
            + i.y + vec4(0.0, i1.y, i2.y, 1.0))
            + i.x + vec4(0.0, i1.x, i2.x, 1.0));
    float n_ = 0.142857142857;
    vec3 ns = n_ * D.wyz - D.xzx;
    vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
    vec4 x_ = floor(j * ns.z);
    vec4 y_ = floor(j - 7.0 * x_);
    vec4 x = x_ * ns.x + ns.yyyy;
    vec4 y = y_ * ns.x + ns.yyyy;
    vec4 h = 1.0 - abs(x) - abs(y);
    vec4 b0 = vec4(x.xy, y.xy);
    vec4 b1 = vec4(x.zw, y.zw);
    vec4 s0 = floor(b0) * 2.0 + 1.0;
    vec4 s1 = floor(b1) * 2.0 + 1.0;
    vec4 sh = -step(h, vec4(0.0));
    vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
    vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
    vec3 p0 = vec3(a0.xy, h.x);
    vec3 p1 = vec3(a0.zw, h.y);
    vec3 p2 = vec3(a1.xy, h.z);
    vec3 p3 = vec3(a1.zw, h.w);
    vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
    p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
    vec4 m = max(0.6 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
    m = m * m;
    return 42.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
}
`;

    // ------------------------------------------------------------------
    // Пост-процессинг: bloom + ACES + виньетка + зерно + хроматика
    // ------------------------------------------------------------------
    var FS_VERT = `
varying vec2 vUv;
void main(){
    vUv = uv;
    gl_Position = vec4(position.xy, 0.0, 1.0);
}`;

    var post = (function () {
        var canFloat = renderer.capabilities.isWebGL2 && renderer.extensions.has('EXT_color_buffer_float');
        var rtType = canFloat ? THREE.HalfFloatType : THREE.UnsignedByteType;

        var quadScene = new THREE.Scene();
        var quadCam   = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
        var quad      = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), null);
        quadScene.add(quad);

        var bright = new THREE.ShaderMaterial({
            uniforms: {
                tDiffuse:   { value: null },
                uThreshold: { value: 0.30 },
                uKnee:      { value: 0.45 }
            },
            vertexShader: FS_VERT,
            fragmentShader: `
uniform sampler2D tDiffuse;
uniform float uThreshold;
uniform float uKnee;
varying vec2 vUv;
void main(){
    vec4 c = texture2D(tDiffuse, vUv);
    float l = max(max(c.r, c.g), c.b);
    float s = clamp((l - uThreshold + uKnee) / (2.0 * uKnee), 0.0, 1.0);
    s = s * s * uKnee;
    float w = max(s, l - uThreshold) / max(l, 1e-4);
    gl_FragColor = vec4(c.rgb * w, 1.0);
}`,
            depthTest: false, depthWrite: false
        });

        var blur = new THREE.ShaderMaterial({
            uniforms: {
                tDiffuse: { value: null },
                uDir:     { value: new THREE.Vector2(1, 0) }
            },
            vertexShader: FS_VERT,
            fragmentShader: `
uniform sampler2D tDiffuse;
uniform vec2 uDir;
varying vec2 vUv;
void main(){
    vec3 s = texture2D(tDiffuse, vUv).rgb * 0.2270;
    s += texture2D(tDiffuse, vUv + uDir * 1.3846).rgb * 0.3162;
    s += texture2D(tDiffuse, vUv - uDir * 1.3846).rgb * 0.3162;
    s += texture2D(tDiffuse, vUv + uDir * 3.2308).rgb * 0.0703;
    s += texture2D(tDiffuse, vUv - uDir * 3.2308).rgb * 0.0703;
    gl_FragColor = vec4(s, 1.0);
}`,
            depthTest: false, depthWrite: false
        });

        var comp = new THREE.ShaderMaterial({
            uniforms: {
                tScene:    { value: null },
                tBloom:    { value: null },
                uTime:     { value: 0 },
                uRes:      { value: new THREE.Vector2(1, 1) },
                uBloom:    { value: 1.0 },
                uExposure: { value: 1.08 }
            },
            vertexShader: FS_VERT,
            fragmentShader: `
uniform sampler2D tScene;
uniform sampler2D tBloom;
uniform float uTime;
uniform vec2 uRes;
uniform float uBloom;
uniform float uExposure;
varying vec2 vUv;
vec3 aces(vec3 x){
    return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}
void main(){
    vec2 cc = vUv - 0.5;
    float r2 = dot(cc, cc);
    float ca = 0.014 * r2;
    vec3 base;
    base.r = texture2D(tScene, vUv + cc * ca).r;
    base.g = texture2D(tScene, vUv).g;
    base.b = texture2D(tScene, vUv - cc * ca).b;
    vec3 col = base + texture2D(tBloom, vUv).rgb * uBloom;
    col = aces(col * uExposure);
    float vig = 1.0 - smoothstep(0.16, 0.72, r2);
    col *= mix(0.60, 1.0, vig);
    float g = fract(sin(dot(vUv * uRes + vec2(uTime * 41.0), vec2(12.9898, 78.233))) * 43758.5453);
    col += (g - 0.5) * 0.03;
    gl_FragColor = vec4(col, 1.0);
}`,
            depthTest: false, depthWrite: false
        });

        var rtScene = null, rtBright = null, rtA = null, rtB = null;
        var api = { bw: 2, bh: 2, setSize: null, render: null };

        function makeRT(w, h, depth) {
            return new THREE.WebGLRenderTarget(w, h, {
                minFilter: THREE.LinearFilter,
                magFilter: THREE.LinearFilter,
                format: THREE.RGBAFormat,
                type: rtType,
                depthBuffer: !!depth
            });
        }

        function pass(mat, target) {
            quad.material = mat;
            renderer.setRenderTarget(target);
            renderer.render(quadScene, quadCam);
        }

        api.setSize = function (w, h) {
            var pr = renderer.getPixelRatio();
            var W = Math.max(2, Math.floor(w * pr));
            var H = Math.max(2, Math.floor(h * pr));
            var bw = Math.max(2, Math.floor(W / 2));
            var bh = Math.max(2, Math.floor(H / 2));
            if (rtScene) { rtScene.dispose(); rtBright.dispose(); rtA.dispose(); rtB.dispose(); }
            rtScene  = makeRT(W, H, true);
            rtBright = makeRT(bw, bh, false);
            rtA      = makeRT(bw, bh, false);
            rtB      = makeRT(bw, bh, false);
            api.bw = bw;
            api.bh = bh;
            comp.uniforms.uRes.value.set(W, H);
        };

        api.render = function (timeSec) {
            if (!rtScene) return;
            renderer.setRenderTarget(rtScene);
            renderer.render(scene, camera);

            bright.uniforms.tDiffuse.value = rtScene.texture;
            pass(bright, rtBright);

            var tx = 1 / api.bw, ty = 1 / api.bh;
            blur.uniforms.tDiffuse.value = rtBright.texture;
            blur.uniforms.uDir.value.set(tx, 0);
            pass(blur, rtA);
            blur.uniforms.tDiffuse.value = rtA.texture;
            blur.uniforms.uDir.value.set(0, ty);
            pass(blur, rtB);
            blur.uniforms.tDiffuse.value = rtB.texture;
            blur.uniforms.uDir.value.set(tx * 2.0, 0);
            pass(blur, rtA);
            blur.uniforms.tDiffuse.value = rtA.texture;
            blur.uniforms.uDir.value.set(0, ty * 2.0);
            pass(blur, rtB);

            comp.uniforms.tScene.value = rtScene.texture;
            comp.uniforms.tBloom.value = rtB.texture;
            comp.uniforms.uTime.value = timeSec;
            pass(comp, null);
        };

        return api;
    })();

    // ------------------------------------------------------------------
    // Общие canvas-текстуры
    // ------------------------------------------------------------------
    function radialTexture(size, stops) {
        var c = document.createElement('canvas');
        c.width = c.height = size;
        var ctx = c.getContext('2d');
        var g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
        for (var i = 0; i < stops.length; i++) g.addColorStop(stops[i][0], stops[i][1]);
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, size, size);
        var t = new THREE.CanvasTexture(c);
        t.minFilter = THREE.LinearFilter;
        return t;
    }

    var texGlow = radialTexture(128, [
        [0.00, 'rgba(255,255,255,1)'],
        [0.18, 'rgba(255,255,255,0.85)'],
        [0.45, 'rgba(255,255,255,0.22)'],
        [1.00, 'rgba(255,255,255,0)']
    ]);
    var texRing = radialTexture(256, [
        [0.00, 'rgba(255,255,255,0)'],
        [0.66, 'rgba(255,255,255,0)'],
        [0.80, 'rgba(255,255,255,0.9)'],
        [0.95, 'rgba(255,255,255,0)']
    ]);

    function raysTexture(size) {
        var c = document.createElement('canvas');
        c.width = c.height = size;
        var ctx = c.getContext('2d');
        ctx.translate(size / 2, size / 2);
        var rnd = mulberry32(777);
        var N = 20;
        for (var i = 0; i < N; i++) {
            var a = (i / N) * Math.PI * 2 + rnd() * 0.14;
            var len = size * 0.48 * (0.5 + rnd() * 0.5);
            var w = (0.35 + rnd() * 0.5) * (Math.PI / N) * 0.4;
            var g = ctx.createRadialGradient(0, 0, size * 0.04, 0, 0, len);
            g.addColorStop(0, 'rgba(255,224,178,0.5)');
            g.addColorStop(1, 'rgba(255,178,92,0)');
            ctx.fillStyle = g;
            ctx.beginPath();
            ctx.moveTo(0, 0);
            ctx.arc(0, 0, len, a - w, a + w);
            ctx.closePath();
            ctx.fill();
        }
        var t = new THREE.CanvasTexture(c);
        t.minFilter = THREE.LinearFilter;
        return t;
    }

    function nebulaTexture(seed, tintA, tintB) {
        var s = 512;
        var c = document.createElement('canvas');
        c.width = c.height = s;
        var ctx = c.getContext('2d');
        var rnd = mulberry32(seed);
        ctx.globalCompositeOperation = 'lighter';
        for (var i = 0; i < 46; i++) {
            var x = s * (0.5 + (rnd() - 0.5) * 0.7);
            var y = s * (0.5 + (rnd() - 0.5) * 0.7);
            var r = s * (0.05 + rnd() * 0.22);
            var g = ctx.createRadialGradient(x, y, 0, x, y, r);
            var col = rnd() < 0.5 ? tintA : tintB;
            g.addColorStop(0, 'rgba(' + col + ',' + (0.02 + rnd() * 0.05).toFixed(3) + ')');
            g.addColorStop(1, 'rgba(' + col + ',0)');
            ctx.fillStyle = g;
            ctx.fillRect(0, 0, s, s);
        }
        ctx.globalCompositeOperation = 'destination-in';
        var m = ctx.createRadialGradient(s / 2, s / 2, s * 0.08, s / 2, s / 2, s * 0.5);
        m.addColorStop(0, 'rgba(0,0,0,1)');
        m.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = m;
        ctx.fillRect(0, 0, s, s);
        var t = new THREE.CanvasTexture(c);
        t.minFilter = THREE.LinearFilter;
        return t;
    }

    // ------------------------------------------------------------------
    // Фон: туманности + два слоя звёзд (в bgGroup, параллакс при drag)
    // ------------------------------------------------------------------
    var nebulas = [];
    function addNebula(seed, tintA, tintB, x, y, z, scale, opacity, rotSpeed) {
        var mat = new THREE.SpriteMaterial({
            map: nebulaTexture(seed, tintA, tintB),
            transparent: true, opacity: opacity,
            blending: THREE.AdditiveBlending, depthWrite: false
        });
        mat.rotation = Math.random() * Math.PI * 2;
        var sp = new THREE.Sprite(mat);
        sp.position.set(x, y, z);
        sp.scale.set(scale, scale, 1);
        sp.renderOrder = 0;
        bgGroup.add(sp);
        nebulas.push({ mat: mat, rotSpeed: rotSpeed });
    }
    addNebula(11, '64,150,138',  '176,112,60',  -120,  40, -170, 280, 0.55,  0.010);
    addNebula(23, '70,92,124',   '64,150,138',   160, -60, -150, 320, 0.45, -0.008);
    addNebula(37, '176,112,60',  '70,92,124',    -50, -110, 130, 260, 0.38,  0.006);
    addNebula(51, '64,150,138',  '70,92,124',     100,  85, 160, 230, 0.32, -0.012);

    var starVert = `
attribute float aSize;
attribute float aPhase;
attribute vec3 aColor;
uniform float uTime;
uniform float uPR;
varying vec3 vColor;
varying float vPhase;
void main(){
    vColor = aColor;
    vPhase = aPhase;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = min(aSize * uPR * (300.0 / -mv.z), 48.0);
    gl_Position = projectionMatrix * mv;
}`;
    var starFrag = `
uniform float uTime;
varying vec3 vColor;
varying float vPhase;
void main(){
    vec2 c = gl_PointCoord - 0.5;
    float d = length(c);
    float a = smoothstep(0.5, 0.06, d);
    float tw = 0.55 + 0.45 * sin(uTime * (0.5 + vPhase) + vPhase * 6.2831);
    gl_FragColor = vec4(vColor * a * tw, 1.0);
}`;
    var starMat = new THREE.ShaderMaterial({
        uniforms: { uTime: { value: 0 }, uPR: { value: renderer.getPixelRatio() } },
        vertexShader: starVert,
        fragmentShader: starFrag,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending
    });

    function buildPoints(count, rMin, rMax, sMin, sMax, palette) {
        var geo = new THREE.BufferGeometry();
        var pos = new Float32Array(count * 3);
        var col = new Float32Array(count * 3);
        var siz = new Float32Array(count);
        var pha = new Float32Array(count);
        for (var i = 0; i < count; i++) {
            var u = Math.random(), v = Math.random();
            var th = u * Math.PI * 2, ph = Math.acos(2 * v - 1);
            var r = rMin + Math.random() * (rMax - rMin);
            pos[i * 3]     = r * Math.sin(ph) * Math.cos(th);
            pos[i * 3 + 1] = r * Math.cos(ph);
            pos[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th);
            var p = palette[Math.floor(Math.random() * palette.length)];
            col[i * 3] = p[0]; col[i * 3 + 1] = p[1]; col[i * 3 + 2] = p[2];
            siz[i] = sMin + Math.random() * (sMax - sMin);
            pha[i] = Math.random();
        }
        geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
        geo.setAttribute('aColor',   new THREE.Float32BufferAttribute(col, 3));
        geo.setAttribute('aSize',    new THREE.Float32BufferAttribute(siz, 1));
        geo.setAttribute('aPhase',   new THREE.Float32BufferAttribute(pha, 1));
        return new THREE.Points(geo, starMat);
    }

    var STAR_PALETTE = [[0.72, 0.80, 0.86], [0.98, 0.84, 0.62], [0.60, 0.88, 0.84], [0.85, 0.86, 0.9]];
    var DUST_PALETTE = [[0.55, 0.85, 0.75], [0.95, 0.75, 0.50], [0.70, 0.75, 0.80]];

    var starsNear = buildPoints(1000, 60, 150, 0.8, 2.0, STAR_PALETTE);
    var starsFar  = buildPoints(700, 150, 260, 1.2, 2.8, STAR_PALETTE);
    bgGroup.add(starsNear);
    bgGroup.add(starsFar);
    var dust = buildPoints(260, 5, 26, 0.12, 0.34, DUST_PALETTE);
    nodesGroup.add(dust);

    // ------------------------------------------------------------------
    // Ядро: шейдерная «кипящая» звезда + ободок + гало + корона
    // ------------------------------------------------------------------
    var coreGroup = new THREE.Group();
    rootGroup.add(coreGroup);

    var coreMat = new THREE.ShaderMaterial({
        uniforms: { uTime: { value: 0 }, uEnergy: { value: 0 } },
        vertexShader: `
uniform float uTime;
varying vec3 vN;
varying vec3 vV;
varying vec3 vON;
 ${GLSL_NOISE}
void main(){
    vON = normal;
    float n1 = snoise(normal * 2.4 + vec3(0.0, uTime * 0.20, uTime * 0.11));
    float n2 = snoise(normal * 6.5 - vec3(uTime * 0.33, 0.0, uTime * 0.19));
    vec3 p = position + normal * (n1 * 0.14 + n2 * 0.06);
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    vN = normalize(normalMatrix * normal);
    vV = -mv.xyz;
    gl_Position = projectionMatrix * mv;
}`,
        fragmentShader: `
uniform float uTime;
uniform float uEnergy;
varying vec3 vN;
varying vec3 vV;
varying vec3 vON;
 ${GLSL_NOISE}
void main(){
    vec3 n = normalize(vN);
    vec3 v = normalize(vV);
    float ndv = max(dot(n, v), 0.0);
    float t = uTime;
    float p1 = snoise(vON * 3.2 + vec3(0.0, t * 0.25, t * 0.12));
    float p2 = snoise(vON * 8.0 - vec3(t * 0.38, 0.0, t * 0.21));
    float plasma = 0.5 + 0.5 * (p1 * 0.65 + p2 * 0.35);
    vec3 deep = vec3(0.42, 0.10, 0.02);
    vec3 mid  = vec3(1.00, 0.44, 0.09);
    vec3 hot  = vec3(1.05, 0.86, 0.58);
    vec3 col = mix(deep, mid, smoothstep(0.12, 0.72, plasma));
    col = mix(col, hot, smoothstep(0.68, 0.97, plasma));
    float rim = pow(1.0 - ndv, 2.2);
    col += vec3(1.0, 0.5, 0.16) * rim * (0.9 + uEnergy * 0.8);
    col *= (1.15 + uEnergy * 1.1);
    gl_FragColor = vec4(col, 1.0);
}`
    });
    var coreMesh = new THREE.Mesh(new THREE.SphereGeometry(2.1, 96, 64), coreMat);
    coreGroup.add(coreMesh);

    var rimMat = new THREE.ShaderMaterial({
        uniforms: { uColor: { value: new THREE.Color(0xffa64d) }, uEnergy: { value: 0 } },
        vertexShader: `
varying vec3 vN;
varying vec3 vV;
void main(){
    vN = normalize(normalMatrix * normal);
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vV = -mv.xyz;
    gl_Position = projectionMatrix * mv;
}`,
        fragmentShader: `
uniform vec3 uColor;
uniform float uEnergy;
varying vec3 vN;
varying vec3 vV;
void main(){
    float a = pow(1.0 - abs(dot(normalize(vN), normalize(vV))), 3.0);
    gl_FragColor = vec4(uColor * (1.4 + uEnergy * 1.2), a);
}`,
        transparent: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false
    });
    var rimShell = new THREE.Mesh(new THREE.SphereGeometry(2.35, 48, 32), rimMat);
    coreGroup.add(rimShell);

    var glowIn = new THREE.Sprite(new THREE.SpriteMaterial({
        map: texGlow, color: COLOR.hot, transparent: true, opacity: 0.9,
        blending: THREE.AdditiveBlending, depthWrite: false
    }));
    glowIn.renderOrder = 3;
    coreGroup.add(glowIn);

    var glowOut = new THREE.Sprite(new THREE.SpriteMaterial({
        map: texGlow, color: COLOR.core, transparent: true, opacity: 0.42,
        blending: THREE.AdditiveBlending, depthWrite: false
    }));
    glowOut.renderOrder = 2;
    coreGroup.add(glowOut);

    var texRays = raysTexture(512);
    var raysA = new THREE.Sprite(new THREE.SpriteMaterial({
        map: texRays, color: 0xffcf94, transparent: true, opacity: 0.5,
        blending: THREE.AdditiveBlending, depthWrite: false
    }));
    raysA.scale.set(26, 26, 1);
    raysA.renderOrder = 1;
    coreGroup.add(raysA);
    var raysB = new THREE.Sprite(new THREE.SpriteMaterial({
        map: texRays, color: 0xff9d4d, transparent: true, opacity: 0.3,
        blending: THREE.AdditiveBlending, depthWrite: false
    }));
    raysB.scale.set(18, 18, 1);
    raysB.renderOrder = 1;
    coreGroup.add(raysB);

    function coronaArc(radius, thetaLength, tiltX, opacity) {
        var g = new THREE.Group();
        var arc = new THREE.Mesh(
            new THREE.RingGeometry(radius, radius + 0.09, 140, 1, 0, thetaLength),
            new THREE.MeshBasicMaterial({
                color: 0xffd9a0, transparent: true, opacity: opacity,
                side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false
            })
        );
        arc.rotation.x = -Math.PI / 2;
        g.add(arc);
        g.rotation.x = tiltX;
        coreGroup.add(g);
        return g;
    }
    var coronaA = coronaArc(3.4, 4.6, 0.45, 0.6);
    var coronaB = coronaArc(4.1, 3.4, -0.6, 0.4);

    var coreEnergy = 0;
    function coreBurst() { coreEnergy = Math.min(coreEnergy + 1.0, 2.6); }

    // ------------------------------------------------------------------
    // Объёмные галактики из частиц: приглушённая палитра
    // «тлеющий угол -> глубокий синий», тонкий диск, балдж, гало.
    // ------------------------------------------------------------------
    var galVert = `
attribute float aSize;
attribute float aPhase;
attribute vec3 aColor;
uniform float uPR;
varying vec3 vColor;
varying float vPhase;
void main(){
    vColor = aColor;
    vPhase = aPhase;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = min(aSize * uPR * (220.0 / -mv.z), 40.0);
    gl_Position = projectionMatrix * mv;
}`;
    var galFrag = `
uniform float uTime;
uniform float uOpacity;
uniform vec3 uTint;
varying vec3 vColor;
varying float vPhase;
void main(){
    vec2 c = gl_PointCoord - 0.5;
    float d = length(c);
    float a = smoothstep(0.5, 0.08, d);
    float tw = 0.78 + 0.22 * sin(uTime * (0.5 + vPhase) + vPhase * 6.2831);
    gl_FragColor = vec4(vColor * uTint * a * tw * uOpacity, 1.0);
}`;

    var galaxyMats = [];   // для обновления uPR при ресайзе

    function makeGalaxyMaterial(opacity) {
        var m = new THREE.ShaderMaterial({
            uniforms: {
                uTime:    { value: 0 },
                uPR:      { value: renderer.getPixelRatio() },
                uOpacity: { value: opacity },
                uTint:    { value: new THREE.Color(1, 1, 1) }
            },
            vertexShader: galVert,
            fragmentShader: galFrag,
            transparent: true,
            depthWrite: false,
            blending: THREE.AdditiveBlending
        });
        galaxyMats.push(m);
        return m;
    }

    // палитра: угол (внутри) -> глубокий синий (снаружи), как у референса
    function armColor(t, q, rnd, out) {
        var tt = clamp((t - 0.12) / 0.88, 0, 1);
        if (q < 0.015) {           // редкая яркая звезда
            out[0] = 1.0; out[1] = 0.98; out[2] = 0.95;
            out.dim = 1.0;
            return;
        }
        out[0] = lerp(1.0, 0.16, tt) * 0.82;
        out[1] = lerp(0.50, 0.28, tt) * 0.82;
        out[2] = lerp(0.24, 0.60, tt) * 0.82;
        out.dim = 1.0;
    }

    function buildGalaxyGeometry(opts) {
        var rnd = mulberry32(opts.seed);
        var count = opts.count;
        var R = opts.radius;
        var arms = opts.arms;
        var twist = opts.twist;
        var hole = opts.hole || 0;          // внутренняя «пустота» (для дыры в центре)
        var armSep = Math.PI * 2 / arms;

        var pos = new Float32Array(count * 3);
        var col = new Float32Array(count * 3);
        var siz = new Float32Array(count);
        var pha = new Float32Array(count);
        var c3 = [0, 0, 0];

        for (var i = 0; i < count; i++) {
            var x, y, z, r, g, b, s;
            var kind = rnd();

            if (kind < 0.14 && hole === 0) {
                // балдж: плотный угольный сфероид
                var br = R * 0.15 * Math.pow(rnd(), 0.7);
                var ba = rnd() * Math.PI * 2;
                x = Math.cos(ba) * br * (1 + (rnd() - 0.5) * 0.3);
                z = Math.sin(ba) * br * (1 + (rnd() - 0.5) * 0.3);
                y = gauss(rnd) * R * 0.05;
                r = 0.85; g = 0.42 + rnd() * 0.12; b = 0.20 + rnd() * 0.1;
                s = 0.7 + rnd() * 0.7;
            } else if (kind < 0.90) {
                // рукава
                var arm = i % arms;
                var t = Math.pow(rnd(), 0.62);
                var ar = hole + t * (R - hole);
                var aa = arm * armSep + t * twist;
                aa += gauss(rnd) * 0.42 * (1.25 - t);
                ar *= 1 + gauss(rnd) * (0.045 + t * 0.05);
                if (ar < hole) ar = hole * (1 + rnd() * 0.2);
                x = Math.cos(aa) * ar;
                z = Math.sin(aa) * ar;
                y = gauss(rnd) * R * 0.05 * (1 - t * 0.75);
                var q = rnd();
                armColor(t, q, rnd, c3);
                r = c3[0]; g = c3[1]; b = c3[2];
                s = (0.4 + rnd() * 0.7) * (1.1 - t * 0.35);
                if (q < 0.015) s *= 2.4;    // яркая звезда покрупнее
            } else {
                // гало: редкая холодная оболочка
                var ha = rnd() * Math.PI * 2;
                var hr = R * (0.2 + Math.pow(rnd(), 0.5) * 0.95);
                if (hr < hole) hr = hole + rnd() * R * 0.1;
                x = Math.cos(ha) * hr;
                z = Math.sin(ha) * hr;
                y = gauss(rnd) * R * 0.14 * (hr / R);
                r = 0.30; g = 0.36; b = 0.55;
                s = 0.25 + rnd() * 0.4;
            }

            pos[i * 3] = x; pos[i * 3 + 1] = y; pos[i * 3 + 2] = z;
            col[i * 3] = r; col[i * 3 + 1] = g; col[i * 3 + 2] = b;
            siz[i] = s;
            pha[i] = rnd();
        }

        var geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
        geo.setAttribute('aColor',   new THREE.Float32BufferAttribute(col, 3));
        geo.setAttribute('aSize',    new THREE.Float32BufferAttribute(siz, 1));
        geo.setAttribute('aPhase',   new THREE.Float32BufferAttribute(pha, 1));
        return geo;
    }

    // ------------------------------------------------------------------
    // ЧЁРНАЯ ДЫРА: горизонт событий, фотонное кольцо, аккреционный диск
    // с доплеровским бимингом и полярные джеты.
    // ------------------------------------------------------------------
    var diskVert = `
attribute float aSize;
attribute vec3 aColor;
uniform float uPR;
varying vec3 vColor;
void main(){
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    /* релятивистский биминг: приближающаяся сторона диска ярче.
       касательная к вращению вокруг Y в объектных координатах */
    vec3 tangentObj = normalize(vec3(position.z, 0.0, -position.x));
    vec3 tangentView = normalize((modelViewMatrix * vec4(tangentObj, 0.0)).xyz);
    float beam = 0.40 + 1.10 * max(0.0, dot(tangentView, normalize(-mv.xyz)));
    vColor = aColor * beam;
    gl_PointSize = min(aSize * uPR * (220.0 / -mv.z), 40.0);
    gl_Position = projectionMatrix * mv;
}`;
    var diskFrag = `
uniform float uOpacity;
varying vec3 vColor;
void main(){
    vec2 c = gl_PointCoord - 0.5;
    float d = length(c);
    float a = smoothstep(0.5, 0.1, d);
    gl_FragColor = vec4(vColor * a * uOpacity, 1.0);
}`;

    var heroGroup = new THREE.Group();
    heroGroup.rotation.set(-0.45, 0.2, 0);
    heroGroup.visible = false;
    rootGroup.add(heroGroup);

    var heroPoints = null, heroMat = null;
    var bhShadow = null, photonRing = null, bhGlow = null, bhInnerRing = null;
    var diskPoints = null, diskMat = null;
    var jetPoints = null, jetMat = null;
    var jetState = null;   // { pos, col, vel, dir, count, height }
    var JET_HEIGHT = 13;

    function buildBlackHole() {
        // горизонт событий: абсолютно чёрная сфера, реально перекрывает частицы
        bhShadow = new THREE.Mesh(
            new THREE.SphereGeometry(1.5, 48, 32),
            new THREE.MeshBasicMaterial({ color: 0x000000 })
        );
        heroGroup.add(bhShadow);

        // фотонное кольцо вокруг тени
        photonRing = new THREE.Sprite(new THREE.SpriteMaterial({
            map: texRing, color: 0xffedd2, transparent: true, opacity: 0.85,
            blending: THREE.AdditiveBlending, depthWrite: false
        }));
        photonRing.scale.set(5.2, 5.2, 1);
        photonRing.renderOrder = 3;
        heroGroup.add(photonRing);

        // тёплое свечение вокруг
        bhGlow = new THREE.Sprite(new THREE.SpriteMaterial({
            map: texGlow, color: 0xff8a30, transparent: true, opacity: 0.4,
            blending: THREE.AdditiveBlending, depthWrite: false
        }));
        bhGlow.scale.set(6.5, 6.5, 1);
        bhGlow.renderOrder = 2;
        heroGroup.add(bhGlow);

        // тонкое внутреннее кольцо-подложка диска
        bhInnerRing = new THREE.Mesh(
            new THREE.RingGeometry(1.9, 2.4, 96),
            new THREE.MeshBasicMaterial({
                color: 0xff8830, transparent: true, opacity: 0.16,
                side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false
            })
        );
        bhInnerRing.rotation.x = -Math.PI / 2;
        heroGroup.add(bhInnerRing);

        // аккреционный диск: белое каление -> оранжак -> тёмно-красный
        var count = 7000;
        var geo = new THREE.BufferGeometry();
        var pos = new Float32Array(count * 3);
        var col = new Float32Array(count * 3);
        var siz = new Float32Array(count);
        var rnd = mulberry32(9001);
        for (var i = 0; i < count; i++) {
            var t = Math.pow(rnd(), 1.4);
            var r = 1.9 + t * 2.1;
            var a = rnd() * Math.PI * 2;
            pos[i * 3]     = Math.cos(a) * r;
            pos[i * 3 + 1] = gauss(rnd) * 0.05;
            pos[i * 3 + 2] = Math.sin(a) * r;
            var heat = 1 - t;                       // горячее к центру
            col[i * 3]     = lerp(0.75, 1.0, heat);
            col[i * 3 + 1] = lerp(0.16, 0.92, Math.pow(heat, 1.6));
            col[i * 3 + 2] = lerp(0.04, 0.80, Math.pow(heat, 2.2));
            siz[i] = 0.5 + rnd() * 0.7;
        }
        geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
        geo.setAttribute('aColor',   new THREE.Float32BufferAttribute(col, 3));
        geo.setAttribute('aSize',    new THREE.Float32BufferAttribute(siz, 1));
        diskMat = new THREE.ShaderMaterial({
            uniforms: { uOpacity: { value: 0.9 }, uPR: { value: renderer.getPixelRatio() } },
            vertexShader: diskVert,
            fragmentShader: diskFrag,
            transparent: true,
            depthWrite: false,
            blending: THREE.AdditiveBlending
        });
        galaxyMats.push(diskMat);
        diskPoints = new THREE.Points(geo, diskMat);
        diskPoints.renderOrder = 2;
        heroGroup.add(diskPoints);
    }

    function jetSpawnAt(i, initial) {
        var js = jetState;
        var i3 = i * 3;
        var angle = Math.random() * Math.PI * 2;
        var r0 = Math.random() * 0.12;
        js.pos[i3]     = Math.cos(angle) * r0;
        js.pos[i3 + 2] = Math.sin(angle) * r0;
        js.pos[i3 + 1] = js.dir[i] * (initial ? (1.6 + Math.random() * (js.height - 2)) : 1.6);
        js.vel[i3]     = (Math.random() - 0.5) * 0.35;
        js.vel[i3 + 1] = js.dir[i] * (3.5 + Math.random() * 3.0);
        js.vel[i3 + 2] = (Math.random() - 0.5) * 0.35;
    }

    function buildJets() {
        var count = 3000;
        var geo = new THREE.BufferGeometry();
        var pos = new Float32Array(count * 3);
        var col = new Float32Array(count * 3);
        var siz = new Float32Array(count);
        var pha = new Float32Array(count);
        var vel = new Float32Array(count * 3);
        var dir = new Float32Array(count);
        jetState = { pos: pos, col: col, vel: vel, dir: dir, count: count, height: JET_HEIGHT };
        for (var i = 0; i < count; i++) {
            dir[i] = (i % 2 === 0) ? 1 : -1;
            siz[i] = 0.35 + Math.random() * 0.55;
            pha[i] = Math.random();
            jetSpawnAt(i, true);
        }
        geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
        geo.setAttribute('aColor',   new THREE.Float32BufferAttribute(col, 3));
        geo.setAttribute('aSize',    new THREE.Float32BufferAttribute(siz, 1));
        geo.setAttribute('aPhase',   new THREE.Float32BufferAttribute(pha, 1));
        jetMat = makeGalaxyMaterial(0.9);
        jetMat.uniforms.uTint.value.setHex(0xffffff);
        jetPoints = new THREE.Points(geo, jetMat);
        jetPoints.renderOrder = 3;
        heroGroup.add(jetPoints);
    }

    function updateJets(dt) {
        var js = jetState;
        if (!js || !jetPoints) return;
        var pos = js.pos, col = js.col, vel = js.vel, dir = js.dir;
        for (var i = 0; i < js.count; i++) {
            var i3 = i * 3;
            pos[i3]     += vel[i3] * dt + pos[i3] * 0.10 * dt;     // лёгкий конус
            pos[i3 + 1] += vel[i3 + 1] * dt;
            pos[i3 + 2] += vel[i3 + 2] * dt + pos[i3 + 2] * 0.10 * dt;
            var life = 1 - Math.abs(pos[i3 + 1]) / js.height;
            if (life < 0) life = 0;
            // белое ядро -> ледяной синий на затухании
            col[i3]     = 0.20 + 0.75 * life;
            col[i3 + 1] = 0.30 + 0.65 * life;
            col[i3 + 2] = 0.55 + 0.45 * life;
            if (Math.abs(pos[i3 + 1]) > js.height || Math.random() < 0.004) {
                jetSpawnAt(i, false);
            }
        }
        jetPoints.geometry.attributes.position.needsUpdate = true;
        jetPoints.geometry.attributes.aColor.needsUpdate = true;
    }

    // Центральный комплекс скопления (создаётся лениво)
    function ensureHeroGalaxy() {
        if (heroPoints) return;
        var geo = buildGalaxyGeometry({
            seed: 4242, count: 26000, radius: 9.5, arms: 3, twist: 2.4, hole: 4.2
        });
        heroMat = makeGalaxyMaterial(0.6);
        heroPoints = new THREE.Points(geo, heroMat);
        heroPoints.renderOrder = 1;
        heroGroup.add(heroPoints);
        buildBlackHole();
        buildJets();
    }

    // ------------------------------------------------------------------
    // Направляющие: пунктирные орбиты / меридианы / спираль / кольца скопления
    // ------------------------------------------------------------------
    function clearGuides() {
        for (var i = guides.children.length - 1; i >= 0; i--) {
            var o = guides.children[i];
            guides.remove(o);
            o.geometry.dispose();
            o.material.dispose();
        }
    }
    function ringPoints(radius, plane, segments) {
        var pts = [];
        for (var i = 0; i <= segments; i++) {
            var a = (i / segments) * Math.PI * 2;
            var c = Math.cos(a) * radius, s = Math.sin(a) * radius;
            if (plane === 'xy')      pts.push(new THREE.Vector3(c, s, 0));
            else if (plane === 'yz') pts.push(new THREE.Vector3(0, c, s));
            else                     pts.push(new THREE.Vector3(c, 0, s));
        }
        return pts;
    }
    function spiralPoint(s, out) {
        var a = s * Math.PI * 3.6 + 0.7;
        var r = 6.5 + s * 10.5;
        out.set(Math.cos(a) * r, (s - 0.5) * 13, Math.sin(a) * r);
        return out;
    }
    function guideLine(points, opacity, dash, gap) {
        var geo = new THREE.BufferGeometry().setFromPoints(points);
        var mat = new THREE.LineDashedMaterial({
            color: COLOR.guide, transparent: true, opacity: opacity,
            dashSize: dash, gapSize: gap,
            blending: THREE.AdditiveBlending, depthWrite: false
        });
        var line = new THREE.Line(geo, mat);
        line.computeLineDistances();
        guides.add(line);
    }
    function rebuildGuides(mode) {
        clearGuides();
        if (mode === 'orbits') {
            for (var i = 0; i < ORBIT_RADII.length; i++) {
                guideLine(ringPoints(ORBIT_RADII[i], 'xz', 160), 0.35, 0.9, 0.7);
            }
        } else if (mode === 'sphere') {
            guideLine(ringPoints(SPHERE_R, 'xz', 160), 0.32, 0.8, 0.8);
            guideLine(ringPoints(SPHERE_R, 'xy', 160), 0.20, 0.5, 0.9);
            guideLine(ringPoints(SPHERE_R, 'yz', 160), 0.20, 0.5, 0.9);
        } else if (mode === 'galaxy') {
            guideLine(ringPoints(13.5, 'xz', 180), 0.20, 1.2, 1.0);
            guideLine(ringPoints(19.5, 'xz', 200), 0.14, 1.4, 1.2);
        } else {
            var pts = [], v = new THREE.Vector3();
            for (var j = 0; j <= 200; j++) pts.push(spiralPoint(j / 200, v).clone());
            guideLine(pts, 0.4, 0.7, 0.6);
        }
    }

    // ------------------------------------------------------------------
    // Узлы-пользователи
    // ------------------------------------------------------------------
    var nodeVert = `
varying vec3 vN;
varying vec3 vV;
void main(){
    vN = normalize(normalMatrix * normal);
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vV = -mv.xyz;
    gl_Position = projectionMatrix * mv;
}`;
    var nodeFrag = `
uniform vec3 uColor;
uniform float uTime;
uniform float uFlash;
uniform float uHover;
uniform float uBlocked;
varying vec3 vN;
varying vec3 vV;
void main(){
    vec3 n = normalize(vN);
    vec3 v = normalize(vV);
    float ndv = max(dot(n, v), 0.0);
    float rim = pow(1.0 - ndv, 2.4);
    vec3 col = mix(uColor * 0.16, uColor * 0.55, ndv);
    col += uColor * rim * 1.7;
    col += vec3(1.0) * pow(ndv, 6.0) * (0.30 + 0.22 * sin(uTime * 2.1 + uHover * 3.0));
    col *= 1.0 + uFlash * 2.4;
    col *= 1.0 + uHover * 0.55;
    col *= mix(1.0, 0.55, uBlocked);
    gl_FragColor = vec4(col, 1.0);
}`;

    function makeNodeMaterial(hex, blocked) {
        return new THREE.ShaderMaterial({
            uniforms: {
                uColor:   { value: new THREE.Color(hex) },
                uTime:    { value: 0 },
                uFlash:   { value: 0 },
                uHover:   { value: 0 },
                uBlocked: { value: blocked ? 1 : 0 }
            },
            vertexShader: nodeVert,
            fragmentShader: nodeFrag
        });
    }

    var nodeGeo = new THREE.SphereGeometry(0.55, 28, 20);
    var hitGeo  = new THREE.SphereGeometry(1.05, 8, 6);
    var hitMat  = new THREE.MeshBasicMaterial({ visible: false });

    function colorHexFor(u) {
        var c = new THREE.Color();
        if (u.blocked) {
            c.setHSL(0.012, 0.62, 0.46);
        } else {
            var hue = 0.42 + ((hashUid(u.uid) % 360) / 360) * 0.09;
            c.setHSL(hue, 0.60, 0.60);
        }
        return c.getHex();
    }

    function positionForUid(uid, mode, out) {
        var rnd = mulberry32(hashUid(uid));
        if (mode === 'galaxy') {
            var gr = 11 + rnd() * 9;
            var ga = rnd() * Math.PI * 2;
            out.set(Math.cos(ga) * gr, (rnd() - 0.5) * 4, Math.sin(ga) * gr);
        } else if (mode === 'sphere') {
            var u = rnd(), v = rnd();
            var th = u * Math.PI * 2;
            var ph = Math.acos(2 * v - 1);
            out.set(
                SPHERE_R * Math.sin(ph) * Math.cos(th),
                SPHERE_R * Math.cos(ph),
                SPHERE_R * Math.sin(ph) * Math.sin(th)
            );
        } else if (mode === 'spiral') {
            spiralPoint(0.08 + rnd() * 0.84, out);
        } else {
            var ring = ORBIT_RADII[Math.floor(rnd() * ORBIT_RADII.length) % ORBIT_RADII.length];
            var a = rnd() * Math.PI * 2;
            out.set(Math.cos(a) * ring, (rnd() - 0.5) * 1.8, Math.sin(a) * ring);
        }
        return out;
    }

    var nodes = new Map();

    function roundRectPath(ctx, x, y, w, h, r) {
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.arcTo(x + w, y, x + w, y + h, r);
        ctx.arcTo(x + w, y + h, x, y + h, r);
        ctx.arcTo(x, y + h, x, y, r);
        ctx.arcTo(x, y, x + w, y, r);
        ctx.closePath();
    }

    function drawLabel(node) {
        var u = node.data || {};
        var text = shortLabel(displayLabel(u), 18);
        var font = '500 36px "Golos Text", "Segoe UI", sans-serif';
        var c = node.labelCanvas;
        var ctx = c.getContext('2d');
        ctx.font = font;
        var tw = Math.ceil(ctx.measureText(text).width);
        var padL = 54, padR = 26, H = 84;
        var W = tw + padL + padR;
        c.width = W;
        c.height = H;
        ctx = c.getContext('2d');

        roundRectPath(ctx, 2, 10, W - 4, H - 20, (H - 20) / 2);
        ctx.fillStyle = 'rgba(6, 11, 15, 0.74)';
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = u.blocked ? 'rgba(224, 110, 110, 0.5)' : 'rgba(180, 240, 220, 0.24)';
        ctx.stroke();

        var cx = 36, cy = H / 2;
        ctx.beginPath();
        ctx.arc(cx, cy, 15, 0, Math.PI * 2);
        ctx.fillStyle = u.blocked ? 'rgba(224, 82, 82, 0.20)' : 'rgba(127, 231, 193, 0.18)';
        ctx.fill();
        ctx.beginPath();
        ctx.arc(cx, cy, 8, 0, Math.PI * 2);
        ctx.fillStyle = u.blocked ? '#e05252' : '#7fe7c1';
        ctx.fill();

        ctx.font = font;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = u.blocked ? 'rgba(244, 205, 205, 0.92)' : 'rgba(236, 250, 245, 0.96)';
        ctx.fillText(text, padL, cy + 2);

        node.labelTex.needsUpdate = true;
        var hW = 0.9;
        node.label.scale.set(hW * (W / H), hW, 1);
    }

    function appearanceKey(u) {
        return displayLabel(u) + '|' + (u.blocked ? 1 : 0);
    }

    function applyNodeMode(n) {
        var gal = state.mode === 'galaxy';
        n.mesh.visible = !gal;
        n.galGroup.visible = gal;
        n.label.position.y = gal ? 2.9 : 1.9;
        n.hit.scale.setScalar(gal ? 1.9 : 1);
    }

    function ensureNodeGalaxy(n) {
        if (n.galaxy) return;
        var seed = hashUid(n.uid) ^ 0x51AB1E;
        var arms = 2 + (seed % 2);
        var geo = buildGalaxyGeometry({
            seed: seed,
            count: 1600,
            radius: n.galRadius,
            arms: arms,
            twist: 2.2 + ((seed >>> 8) % 100) / 100 * 1.6
        });
        n.galMat = makeGalaxyMaterial(0.7);
        n.galaxy = new THREE.Points(geo, n.galMat);
        n.galaxy.renderOrder = 2;
        n.galGeo = geo;
        n.galGroup.add(n.galaxy);
        n.galGlow = new THREE.Sprite(new THREE.SpriteMaterial({
            map: texGlow, color: 0xff9540, transparent: true, opacity: 0.55,
            blending: THREE.AdditiveBlending, depthWrite: false
        }));
        n.galGlow.scale.set(0.85, 0.85, 1);
        n.galGroup.add(n.galGlow);
        applyGalaxyTint(n);
    }

    function applyGalaxyTint(n) {
        if (!n.galMat) return;
        var blocked = n.data && n.data.blocked;
        n.galMat.uniforms.uTint.value.setHex(blocked ? 0x9c3d3d : 0xffffff);
        n.galGlow.material.color.setHex(blocked ? 0xd05050 : 0xff9540);
    }

    function createNode(u) {
        var group = new THREE.Group();
        var hex = colorHexFor(u);

        var mat = makeNodeMaterial(hex, u.blocked);
        var mesh = new THREE.Mesh(nodeGeo, mat);
        group.add(mesh);

        var hit = new THREE.Mesh(hitGeo, hitMat);
        hit.visible = false;
        hit.userData.uid = u.uid;
        group.add(hit);

        var haloMat = new THREE.SpriteMaterial({
            map: texGlow, color: hex, transparent: true, opacity: 0.5,
            blending: THREE.AdditiveBlending, depthWrite: false
        });
        var halo = new THREE.Sprite(haloMat);
        halo.scale.set(3.4, 3.4, 1);
        halo.renderOrder = 4;
        group.add(halo);

        var grng = mulberry32(hashUid(u.uid) ^ 0xB5297A4D);
        var galGroup = new THREE.Group();
        galGroup.rotation.set(grng() * Math.PI, grng() * Math.PI * 2, 0);
        galGroup.visible = false;
        group.add(galGroup);

        var labelCanvas = document.createElement('canvas');
        labelCanvas.width = 128;
        labelCanvas.height = 84;
        var labelTex = new THREE.CanvasTexture(labelCanvas);
        labelTex.minFilter = THREE.LinearFilter;
        var labelMat = new THREE.SpriteMaterial({
            map: labelTex, transparent: true, depthWrite: false, depthTest: false
        });
        var label = new THREE.Sprite(labelMat);
        label.position.y = 1.9;
        label.renderOrder = 10;
        group.add(label);

        var node = {
            uid: u.uid,
            group: group, mesh: mesh, mat: mat, hit: hit,
            halo: halo, haloMat: haloMat,
            galGroup: galGroup, galaxy: null, galMat: null, galGeo: null, galGlow: null,
            galRadius: 2.0 + grng() * 0.9,
            spinSpeed: (0.14 + grng() * 0.18) * (grng() < 0.5 ? -1 : 1),
            spinMul: u.blocked ? 0.15 : 1,
            label: label, labelMat: labelMat,
            labelCanvas: labelCanvas, labelTex: labelTex,
            basePos: new THREE.Vector3(),
            pos: new THREE.Vector3(),
            phase: (hashUid(u.uid) % 628) / 100,
            spawn: 0, dying: false, flash: 0, hoverMix: 0,
            appearanceKey: null,
            data: u
        };
        positionForUid(u.uid, state.mode, node.basePos);
        node.pos.copy(node.basePos);
        group.position.copy(node.pos);
        group.scale.setScalar(0.001);

        nodesGroup.add(group);
        nodes.set(u.uid, node);
        applyNodeData(node, u);
        applyNodeMode(node);
        if (state.mode === 'galaxy') ensureNodeGalaxy(node);
        return node;
    }

    function applyNodeData(node, u) {
        node.data = u;
        var key = appearanceKey(u);
        if (node.appearanceKey !== key) {
            node.appearanceKey = key;
            var hex = colorHexFor(u);
            node.mat.uniforms.uColor.value.setHex(hex);
            node.mat.uniforms.uBlocked.value = u.blocked ? 1 : 0;
            node.haloMat.color.setHex(hex);
            node.spinMul = u.blocked ? 0.15 : 1;
            applyGalaxyTint(node);
            drawLabel(node);
        }
    }

    function removeNode(node) { node.dying = true; }

    function disposeNode(node) {
        nodesGroup.remove(node.group);
        node.mat.dispose();
        if (node.galMat) {
            var idx = galaxyMats.indexOf(node.galMat);
            if (idx !== -1) galaxyMats.splice(idx, 1);
            node.galMat.dispose();
        }
        if (node.galGeo) node.galGeo.dispose();
        if (node.galGlow) node.galGlow.material.dispose();
        node.labelTex.dispose();
        node.labelMat.dispose();
        node.haloMat.dispose();
        if (state.hoveredUid === node.uid) state.hoveredUid = null;
        if (state.pinnedUid === node.uid) state.pinnedUid = null;
        tooltip.dataset.uid = '';
        nodes.delete(node.uid);
        updateTooltip();
    }

    // ------------------------------------------------------------------
    // Импульсы, волны, осколки
    // ------------------------------------------------------------------
    var pulses = [];
    var waves = [];
    var debris = [];

    function pulseDot(hex, scale, opacity, order) {
        var m = new THREE.SpriteMaterial({
            map: texGlow, color: hex, transparent: true, opacity: opacity,
            blending: THREE.AdditiveBlending, depthWrite: false
        });
        var s = new THREE.Sprite(m);
        s.scale.set(scale, scale, 1);
        s.renderOrder = order || 6;
        fxGroup.add(s);
        return s;
    }

    function spawnPulse(node) {
        var from = node.group.position.clone();
        var to = new THREE.Vector3(0, 0, 0);
        var mid = from.clone().add(to).multiplyScalar(0.5);
        var dir = from.clone().sub(to);
        var len = Math.max(dir.length(), 0.001);
        var up = new THREE.Vector3(0, 1, 0);
        var perp = new THREE.Vector3().crossVectors(dir, up);
        if (perp.lengthSq() < 0.0001) perp.set(1, 0, 0);
        perp.normalize().multiplyScalar(len * 0.22 * (Math.random() < 0.5 ? -1 : 1));
        mid.add(perp);
        mid.y += len * 0.10;
        var curve = new THREE.QuadraticBezierCurve3(from, mid, to);

        var headGlow = pulseDot(0xffb45e, 1.5, 0.95);
        var headCore = pulseDot(0xfff3dc, 0.55, 1.0, 7);
        var trail = [];
        for (var i = 0; i < 6; i++) trail.push(pulseDot(0xffc16e, 0.6 - i * 0.07, 0.55 - i * 0.07));

        pulses.push({ curve: curve, headGlow: headGlow, headCore: headCore, trail: trail, t0: performance.now(), dur: 1500 });
    }

    function disposePulse(pl) {
        fxGroup.remove(pl.headGlow);
        pl.headGlow.material.dispose();
        fxGroup.remove(pl.headCore);
        pl.headCore.material.dispose();
        for (var i = 0; i < pl.trail.length; i++) {
            fxGroup.remove(pl.trail[i]);
            pl.trail[i].material.dispose();
        }
    }

    function spawnDebris(origin, hex, count) {
        for (var i = 0; i < count; i++) {
            var s = pulseDot(hex, 0.35 + Math.random() * 0.4, 0.9, 7);
            s.position.copy(origin);
            var v = new THREE.Vector3(Math.random() - 0.5, Math.random() - 0.5, Math.random() - 0.5);
            if (v.lengthSq() < 1e-4) v.set(0, 1, 0);
            v.normalize().multiplyScalar(7 + Math.random() * 9);
            debris.push({ s: s, v: v, t0: performance.now(), dur: 600 + Math.random() * 450 });
        }
    }

    function updatePulses(now, dt) {
        for (var p = pulses.length - 1; p >= 0; p--) {
            var pl = pulses[p];
            var t = (now - pl.t0) / pl.dur;
            if (t >= 1) {
                coreBurst();
                spawnWave(new THREE.Vector3(0, 0, 0), 4.5, 17, 0.8, 1100, COLOR.core);
                spawnWave(new THREE.Vector3(0, 0, 0), 5.5, 26, 0.35, 1700, 0xff8a3d);
                spawnDebris(new THREE.Vector3(0, 0, 0), 0xffc06a, 12);
                disposePulse(pl);
                pulses.splice(p, 1);
                continue;
            }
            var e = easeInQuad(t);
            var pt = pl.curve.getPoint(e);
            pl.headGlow.position.copy(pt);
            pl.headCore.position.copy(pt);
            var fade = t > 0.82 ? 1 - (t - 0.82) / 0.18 : 1;
            for (var i = 0; i < pl.trail.length; i++) {
                var te = clamp(e - (i + 1) * 0.06, 0, 1);
                pl.trail[i].position.copy(pl.curve.getPoint(te));
                pl.trail[i].material.opacity = (0.55 - i * 0.07) * fade;
            }
        }

        for (var d = debris.length - 1; d >= 0; d--) {
            var db = debris[d];
            var td = (now - db.t0) / db.dur;
            if (td >= 1) {
                fxGroup.remove(db.s);
                db.s.material.dispose();
                debris.splice(d, 1);
                continue;
            }
            db.s.position.addScaledVector(db.v, dt);
            db.v.multiplyScalar(Math.exp(-2.6 * dt));
            db.s.material.opacity = 0.9 * (1 - td);
            var sc = 0.5 * (1 - td * 0.6);
            db.s.scale.set(sc, sc, 1);
        }
    }

    function spawnWave(pos, fromScale, toScale, opacity, dur, hex) {
        var m = new THREE.SpriteMaterial({
            map: texRing, color: hex, transparent: true, opacity: opacity,
            blending: THREE.AdditiveBlending, depthWrite: false
        });
        var s = new THREE.Sprite(m);
        s.position.copy(pos);
        s.scale.set(fromScale, fromScale, 1);
        s.renderOrder = 5;
        fxGroup.add(s);
        waves.push({ sprite: s, t0: performance.now(), dur: dur, from: fromScale, to: toScale, o0: opacity });
    }

    function updateWaves(now) {
        for (var i = waves.length - 1; i >= 0; i--) {
            var w = waves[i];
            var t = (now - w.t0) / w.dur;
            if (t >= 1) {
                fxGroup.remove(w.sprite);
                w.sprite.material.dispose();
                waves.splice(i, 1);
                continue;
            }
            var s = lerp(w.from, w.to, easeOutCubic(t));
            w.sprite.scale.set(s, s, 1);
            w.sprite.material.opacity = w.o0 * (1 - t);
        }
    }

    // ------------------------------------------------------------------
    // Данные: сверка списка, статистика, оверлей
    // ------------------------------------------------------------------
    function updateStats(userCount, eventTotal) {
        statUsers.textContent = String(userCount);
        statUsersW.textContent = plural(userCount, ['пользователь', 'пользователя', 'пользователей']);
        if (statEvents.textContent !== String(eventTotal)) {
            statEvents.textContent = String(eventTotal);
            statEvents.classList.remove('flash');
            void statEvents.offsetWidth;
            statEvents.classList.add('flash');
        }
        statEventsW.textContent = plural(eventTotal, ['событие', 'события', 'событий']);
    }

    function updateOverlay() {
        if (!state.loaded) {
            overlay.hidden = false;
            overlay.classList.add('is-loading');
            overlayText.textContent = 'Приём телеметрии…';
            return;
        }
        overlay.classList.remove('is-loading');
        if (state.userCount === 0) {
            overlay.hidden = false;
            overlayText.textContent = 'Тишина в эфире: за последние 24 часа никто не писал боту. Ядро станции ждёт сигнала.';
        } else {
            overlay.hidden = true;
        }
    }

    function handleUsers(list) {
        list = Array.isArray(list) ? list : [];
        state.loaded = true;
        var seen = new Set();
        var total = 0;
        for (var i = 0; i < list.length; i++) {
            var u = list[i];
            if (!u || u.uid == null) continue;
            seen.add(u.uid);
            if (Array.isArray(u.times)) total += u.times.length;
            var node = nodes.get(u.uid);
            if (!node) createNode(u);
            else {
                node.dying = false;
                applyNodeData(node, u);
            }
        }
        nodes.forEach(function (node) {
            if (!seen.has(node.uid) && !node.dying) removeNode(node);
        });
        state.userCount = list.length;
        state.eventTotal = total;
        updateStats(state.userCount, total);
        updateOverlay();
    }

    function onLiveEvent(ev) {
        if (!ev || ev.uid == null || !ev.time) return;
        var node = nodes.get(ev.uid);
        if (!node || node.dying) {
            fetchData();
            return;
        }
        if (!Array.isArray(node.data.times)) node.data.times = [];
        if (node.data.times.indexOf(ev.time) === -1) node.data.times.push(ev.time);
        state.eventTotal += 1;
        updateStats(state.userCount, state.eventTotal);
        if (!node.data.blocked) {
            node.flash = 1;
            spawnPulse(node);
            spawnWave(node.group.position.clone(), 0.7, 3.8, 0.6, 700, colorHexFor(node.data));
        }
        if (state.pinnedUid === node.uid || state.hoveredUid === node.uid) {
            tooltip.dataset.uid = '';
            updateTooltip();
        }
    }

    // ------------------------------------------------------------------
    // Сеть: первичная загрузка, SSE с ретраем, автообновление
    // ------------------------------------------------------------------
    function fetchData() {
        fetch(DATA_URL, { headers: { Accept: 'application/json' } })
            .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
            .then(function (json) {
                if (json && json.ok && Array.isArray(json.users)) handleUsers(json.users);
            })
            .catch(function () { /* тихо: SSE и следующий опрос поправят */ });
    }

    var es = null;
    var retryDelay = 2000;

    function setLive(on) {
        if (state.live === on) return;
        state.live = on;
        streamDot.className = 'dot ' + (on ? 'dot-live' : 'dot-off');
        streamLabel.textContent = on ? 'живой поток' : 'переподключение…';
    }

    function scheduleReconnect() {
        setTimeout(connectStream, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 30000);
    }

    function connectStream() {
        if (window.EventSource == null) { setLive(false); return; }
        try {
            es = new EventSource(STREAM_URL);
        } catch (e) {
            scheduleReconnect();
            return;
        }
        es.addEventListener('snapshot', function (e) {
            try {
                var json = JSON.parse(e.data);
                if (json && json.ok && Array.isArray(json.users)) handleUsers(json.users);
                setLive(true);
                retryDelay = 2000;
            } catch (err) { /* некорректный кадр */ }
        });
        es.onmessage = function (e) {
            try {
                onLiveEvent(JSON.parse(e.data));
                setLive(true);
            } catch (err) { /* некорректный кадр */ }
        };
        es.onerror = function () {
            if (es) { es.close(); es = null; }
            setLive(false);
            scheduleReconnect();
        };
    }

    // ------------------------------------------------------------------
    // Режимы отображения
    // ------------------------------------------------------------------
    function applyModeVisibility() {
        var gal = state.mode === 'galaxy';
        coreMesh.visible = !gal;
        rimShell.visible = !gal;
        coronaA.visible = !gal;
        coronaB.visible = !gal;
        raysA.visible = !gal;
        raysB.visible = !gal;
        heroGroup.visible = gal;
        nodes.forEach(applyNodeMode);
    }

    function setMode(mode, persist) {
        if (MODES.indexOf(mode) === -1) mode = 'orbits';
        state.mode = mode;
        if (mode === 'galaxy') {
            ensureHeroGalaxy();
            nodes.forEach(ensureNodeGalaxy);
        }
        if (persist !== false) {
            try { localStorage.setItem(LS_KEY, mode); } catch (e) { /* приватный режим */ }
        }
        modeButtons.forEach(function (b) {
            var on = b.getAttribute('data-mode') === mode;
            b.classList.toggle('active', on);
            b.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        rebuildGuides(mode);
        nodes.forEach(function (node) {
            positionForUid(node.uid, mode, node.basePos);
        });
        applyModeVisibility();
    }

    modeButtons.forEach(function (b) {
        b.addEventListener('click', function () { setMode(b.getAttribute('data-mode')); });
    });

    // ------------------------------------------------------------------
    // Управление камерой: drag, колесо/щипок, dblclick-сброс
    // ------------------------------------------------------------------
    var view = {
        rotX: TILT_DEFAULT, rotY: -0.7,
        tRotX: TILT_DEFAULT, tRotY: 0,
        dist: INTRO_DIST, tDist: DEFAULT_DIST
    };
    var pointers = new Map();
    var drag = { active: false, moved: 0, lastX: 0, lastY: 0 };
    var pinchDist = 0;

    var el = renderer.domElement;
    el.style.touchAction = 'none';

    el.addEventListener('pointerdown', function (e) {
        if (e.pointerType === 'mouse' && e.button !== 0) return;
        pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
        if (pointers.size === 1) {
            drag.active = true;
            drag.moved = 0;
            drag.lastX = e.clientX;
            drag.lastY = e.clientY;
            el.style.cursor = 'grabbing';
        } else if (pointers.size === 2) {
            var pts = Array.from(pointers.values());
            pinchDist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) || 1;
            drag.active = false;
        }
        try { el.setPointerCapture(e.pointerId); } catch (err) { /* не критично */ }
    });

    el.addEventListener('pointermove', function (e) {
        if (pointers.has(e.pointerId)) pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

        if (pointers.size === 2) {
            var pts = Array.from(pointers.values());
            var d = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) || 1;
            view.tDist = clamp(view.tDist * (pinchDist / d), MIN_DIST, MAX_DIST);
            pinchDist = d;
            return;
        }
        if (drag.active && pointers.size === 1) {
            var dx = e.clientX - drag.lastX;
            var dy = e.clientY - drag.lastY;
            drag.lastX = e.clientX;
            drag.lastY = e.clientY;
            drag.moved += Math.abs(dx) + Math.abs(dy);
            view.tRotY += dx * 0.005;
            view.tRotX = clamp(view.tRotX + dy * 0.005, -1.25, 1.35);
            if (drag.moved > 6) { state.hoveredUid = null; updateTooltip(); }
            return;
        }
        updateHover(e);
    });

    function endPointer(e) {
        var wasDrag = drag.active && drag.moved > 6;
        pointers.delete(e.pointerId);
        if (pointers.size === 0) {
            drag.active = false;
            el.style.cursor = 'grab';
            if (!wasDrag && e.type === 'pointerup') handleTap(e);
        }
    }
    el.addEventListener('pointerup', endPointer);
    el.addEventListener('pointercancel', endPointer);
    el.addEventListener('pointerleave', function () {
        if (pointers.size === 0) { state.hoveredUid = null; updateTooltip(); }
    });

    el.addEventListener('wheel', function (e) {
        e.preventDefault();
        view.tDist = clamp(view.tDist * (e.deltaY > 0 ? 1.12 : 0.89), MIN_DIST, MAX_DIST);
    }, { passive: false });

    el.addEventListener('dblclick', resetView);
    if (resetBtn) resetBtn.addEventListener('click', resetView);

    function resetView() {
        view.tRotX = TILT_DEFAULT;
        view.tRotY = 0;
        view.tDist = DEFAULT_DIST;
        state.pinnedUid = null;
        updateTooltip();
    }

    // ------------------------------------------------------------------
    // Наведение и тултип
    // ------------------------------------------------------------------
    var raycaster = new THREE.Raycaster();
    var ndc = new THREE.Vector2();

    function pickNode(clientX, clientY) {
        var targets = [];
        nodes.forEach(function (n) { if (!n.dying) targets.push(n.hit); });
        if (!targets.length) return null;
        var r = el.getBoundingClientRect();
        ndc.x = ((clientX - r.left) / r.width) * 2 - 1;
        ndc.y = -((clientY - r.top) / r.height) * 2 + 1;
        raycaster.setFromCamera(ndc, camera);
        var hits = raycaster.intersectObjects(targets, false);
        return hits.length ? nodes.get(hits[0].object.userData.uid) : null;
    }

    function updateHover(e) {
        var n = pickNode(e.clientX, e.clientY);
        state.hoveredUid = n ? n.uid : null;
        el.style.cursor = n ? 'pointer' : 'grab';
        updateTooltip();
    }

    function handleTap(e) {
        var n = pickNode(e.clientX, e.clientY);
        state.pinnedUid = n ? n.uid : null;
        updateTooltip();
    }

    function addRow(key, value) {
        var row = document.createElement('div');
        row.className = 'tip-row';
        var k = document.createElement('span');
        k.textContent = key;
        var v = document.createElement('b');
        v.textContent = value;
        row.appendChild(k);
        row.appendChild(v);
        tooltip.appendChild(row);
    }

    function buildHistogram(times) {
        var cv = document.createElement('canvas');
        var W = 224, H = 44;
        cv.width = W;
        cv.height = H;
        cv.className = 'tip-chart';
        var ctx = cv.getContext('2d');
        var buckets = new Array(24).fill(0);
        (times || []).forEach(function (t) {
            var h = parseInt(t, 10);
            if (h >= 0 && h < 24) buckets[h]++;
        });
        var max = 1;
        buckets.forEach(function (b) { if (b > max) max = b; });
        var bw = W / 24;
        for (var i = 0; i < 24; i++) {
            if (buckets[i]) {
                var bh = Math.max(3, (buckets[i] / max) * (H - 14));
                ctx.fillStyle = 'rgba(127, 231, 193, 0.85)';
                ctx.fillRect(i * bw + 1, H - bh, bw - 2, bh);
            } else {
                ctx.fillStyle = 'rgba(255, 255, 255, 0.07)';
                ctx.fillRect(i * bw + 1, H - 2, bw - 2, 2);
            }
        }
        ctx.fillStyle = 'rgba(232, 243, 238, 0.4)';
        ctx.font = '10px "Golos Text", sans-serif';
        ctx.fillText('00', 1, 9);
        ctx.fillText('12', W / 2 - 6, 9);
        ctx.fillText('24', W - 14, 9);
        return cv;
    }

    function buildTooltip(n) {
        var u = n.data || {};
        tooltip.dataset.uid = String(n.uid);
        tooltip.textContent = '';

        var head = document.createElement('div');
        head.className = 'tip-head';
        var name = document.createElement('span');
        name.className = 'tip-name';
        name.textContent = u.name ? u.name : (u.username ? '@' + u.username : 'Пользователь');
        head.appendChild(name);
        if (u.blocked) {
            var badge = document.createElement('span');
            badge.className = 'tip-badge';
            badge.textContent = 'заблокирован';
            head.appendChild(badge);
        }
        tooltip.appendChild(head);

        var sub = document.createElement('div');
        sub.className = 'tip-sub';
        var bits = [];
        if (u.name && u.username) bits.push('@' + u.username);
        bits.push('id ' + u.uid);
        sub.textContent = bits.join(' · ');
        tooltip.appendChild(sub);

        addRow('Событий за 24 ч', String(Array.isArray(u.times) ? u.times.length : 0));
        addRow('Последнее касание', formatAct(u.act));

        var cap = document.createElement('div');
        cap.className = 'tip-cap';
        cap.textContent = 'События по часам';
        tooltip.appendChild(cap);
        tooltip.appendChild(buildHistogram(u.times));
    }

    function updateTooltip() {
        var uid = state.pinnedUid != null ? state.pinnedUid : state.hoveredUid;
        var n = uid != null ? nodes.get(uid) : null;
        if (!n || n.dying) { tooltip.hidden = true; return; }
        if (tooltip.dataset.uid !== String(uid)) buildTooltip(n);
        tooltip.hidden = false;

        var v = n.group.getWorldPosition(new THREE.Vector3());
        v.y += 2.4;
        v.project(camera);
        var r = stage.getBoundingClientRect();
        var x = clamp((v.x * 0.5 + 0.5) * r.width, 100, Math.max(100, r.width - 100));
        var y = Math.max(96, (-v.y * 0.5 + 0.5) * r.height);
        tooltip.style.transform = 'translate(' + Math.round(x) + 'px,' + Math.round(y) + 'px) translate(-50%,-100%)';
    }

    // ------------------------------------------------------------------
    // Главный цикл
    // ------------------------------------------------------------------
    var prevT = performance.now();

    function animate(now) {
        requestAnimationFrame(animate);
        var dt = Math.min(0.05, (now - prevT) / 1000);
        prevT = now;
        var t = now / 1000;
        var gal = state.mode === 'galaxy';

        view.rotX += (view.tRotX - view.rotX) * 0.09;
        view.rotY += (view.tRotY - view.rotY) * 0.09;
        view.dist += (view.tDist - view.dist) * 0.06;
        rootGroup.rotation.x = view.rotX;
        rootGroup.rotation.y = view.rotY;

        bgGroup.rotation.x = view.rotX * 0.55;
        bgGroup.rotation.y = view.rotY * 0.55;

        camera.position.set(0, view.dist * 0.22, view.dist);
        camera.lookAt(0, 0, 0);

        nodesGroup.rotation.y += 0.05 * dt;
        starsNear.rotation.y += 0.008 * dt;
        starsFar.rotation.y -= 0.004 * dt;
        starMat.uniforms.uTime.value = t;
        for (var nb = 0; nb < nebulas.length; nb++) {
            nebulas[nb].mat.rotation += nebulas[nb].rotSpeed * dt;
        }

        // ядро-звезда (не в галактическом режиме)
        coreEnergy *= Math.exp(-2.6 * dt);
        var breath = 1 + 0.05 * Math.sin(t * 1.1);
        coreMesh.scale.setScalar(breath * (1 + 0.35 * coreEnergy));
        coreMat.uniforms.uTime.value = t;
        coreMat.uniforms.uEnergy.value = coreEnergy;
        rimMat.uniforms.uEnergy.value = coreEnergy;
        var nuc = gal ? 0.22 : 1;   // у дыры остаётся лишь малое тёплое гало
        var gs = (1 + 0.06 * Math.sin(t * 0.9)) * (1 + 0.55 * coreEnergy);
        glowIn.scale.set(6.2 * gs * nuc, 6.2 * gs * nuc, 1);
        glowIn.material.opacity = Math.min(1, (0.85 + 0.12 * Math.sin(t * 1.1)) * nuc + 0.4 * coreEnergy);
        glowOut.scale.set(16 * gs * nuc, 16 * gs * nuc, 1);
        glowOut.material.opacity = Math.min(1, (0.38 + 0.08 * Math.sin(t * 0.7 + 1)) * nuc + 0.3 * coreEnergy);
        raysA.material.rotation += (0.02 + coreEnergy * 0.12) * dt;
        raysB.material.rotation -= 0.033 * dt;
        coronaA.rotation.y += 0.25 * dt;
        coronaB.rotation.y -= 0.18 * dt;

        // галактический режим: дыра, диск, джеты, центральная галактика
        if (heroGroup.visible && heroPoints) {
            heroPoints.rotation.y += 0.02 * dt;
            heroMat.uniforms.uTime.value = t;
            var hsc = 1 + 0.02 * Math.sin(t * 0.9);
            heroPoints.scale.setScalar(hsc);

            diskPoints.rotation.y += 0.55 * dt;                       // вихрь диска
            diskMat.uniforms.uOpacity.value = 0.9 + 1.3 * coreEnergy; // вспышка на прилёте
            photonRing.material.opacity = Math.min(1, 0.8 + 0.15 * Math.sin(t * 2.2) + 0.5 * coreEnergy);
            bhGlow.material.opacity = Math.min(1, 0.38 + 0.06 * Math.sin(t * 1.3) + 0.4 * coreEnergy);
            jetMat.uniforms.uTime.value = t;
            jetMat.uniforms.uOpacity.value = Math.min(1.4, 0.85 + 0.5 * coreEnergy);
            updateJets(dt);
        }

        // узлы
        nodes.forEach(function (n) {
            if (n.dying) {
                n.spawn -= dt * 2.6;
                if (n.spawn <= 0) { disposeNode(n); return; }
            } else if (n.spawn < 1) {
                n.spawn = Math.min(1, n.spawn + dt * 1.5);
            }
            n.pos.lerp(n.basePos, 0.06);
            var bobY = Math.sin(t * 0.8 + n.phase) * 0.22;
            var bobX = Math.cos(t * 0.5 + n.phase) * 0.10;
            n.group.position.set(n.pos.x + bobX, n.pos.y + bobY, n.pos.z);

            var s = n.dying ? Math.max(0.001, n.spawn) : Math.max(0.001, easeOutBack(n.spawn));
            n.group.scale.setScalar(s);

            var wantHover = (state.hoveredUid === n.uid || state.pinnedUid === n.uid) ? 1 : 0;
            n.hoverMix += (wantHover - n.hoverMix) * Math.min(1, dt * 10);
            n.flash *= Math.exp(-3.2 * dt);

            var uni = n.mat.uniforms;
            uni.uTime.value = t;
            uni.uFlash.value = n.flash;
            uni.uHover.value = n.hoverMix;

            if (gal && n.galaxy) {
                n.galaxy.rotation.y += n.spinSpeed * n.spinMul * dt;
                var baseOp = (n.data && n.data.blocked) ? 0.4 : 0.7;   // приглушённо
                n.galMat.uniforms.uTime.value = t;
                n.galMat.uniforms.uOpacity.value = baseOp * (1 + 0.9 * n.flash);
                n.galGlow.material.opacity = Math.min(1, 0.5 * baseOp * (1 + 0.9 * n.flash));
                var gsc = 1 + 0.15 * n.flash;
                n.galaxy.scale.set(gsc, gsc, gsc);
            }

            var haloMul = gal ? 0.45 : 1;
            var base = (n.data && n.data.blocked) ? 0.20 : 0.46;
            n.haloMat.opacity = Math.min(1,
                base * haloMul * (0.8 + 0.2 * Math.sin(t * 1.4 + n.phase)) + 0.5 * n.flash + 0.25 * n.hoverMix);
            var hs = 3.4 * (gal ? 1.4 : 1) * (1 + 0.05 * Math.sin(t * 1.4 + n.phase)) * (1 + 0.8 * n.flash + 0.35 * n.hoverMix);
            n.halo.scale.set(hs, hs, 1);
            n.labelMat.opacity = Math.min(1, n.spawn * 1.4);
        });

        updatePulses(now, dt);
        updateWaves(now);

        if (state.pinnedUid != null || state.hoveredUid != null) updateTooltip();

        post.render(t);
    }

    // ------------------------------------------------------------------
    // Ресайз
    // ------------------------------------------------------------------
    function resize() {
        var w = stage.clientWidth, h = stage.clientHeight;
        if (!w || !h) return;
        renderer.setSize(w, h);
        post.setSize(w, h);
        var pr = renderer.getPixelRatio();
        starMat.uniforms.uPR.value = pr;
        for (var i = 0; i < galaxyMats.length; i++) galaxyMats[i].uniforms.uPR.value = pr;
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
    }
    window.addEventListener('resize', resize);

    // ------------------------------------------------------------------
    // Старт
    // ------------------------------------------------------------------
    var savedMode = null;
    try { savedMode = localStorage.getItem(LS_KEY); } catch (e) { /* приватный режим */ }
    setMode(savedMode && MODES.indexOf(savedMode) !== -1 ? savedMode : 'orbits', false);

    resize();
    updateOverlay();
    fetchData();
    setInterval(fetchData, POLL_MS);
    connectStream();

    function redrawLabels() {
        nodes.forEach(function (n) {
            n.appearanceKey = null;
            applyNodeData(n, n.data);
        });
    }
    if (document.fonts && document.fonts.load) {
        document.fonts.load('500 36px "Golos Text"').then(redrawLabels, function () {});
    }
    setTimeout(redrawLabels, 1500);

    requestAnimationFrame(animate);
})();
'''


def main():
    if len(sys.argv) != 2:
        print("Использование: python3 install_activity_ui.py <путь-к-проекту>")
        sys.exit(1)

    root = os.path.abspath(sys.argv[1])
    if not os.path.isdir(root):
        print("Ошибка: каталог проекта не найден: %s" % root)
        sys.exit(1)

    print("Устанавливаю интерфейс «Активность» в проект: %s" % root)
    for rel, content in FILES.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        print("  записан: %-28s (%d байт)" % (rel, len(content.encode("utf-8"))))

    print("Готово. Откройте страницу /admin/activity в админке станции.")


if __name__ == "__main__":
    main()
