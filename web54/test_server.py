"""
Тестовый сервер админки GLM 5.4: полный бэкенд TestV3 (роуты, БД, графики),
но шаблоны и статика — из папки web54/. Порт 5003, чтобы не мешать рабочей
админке на 5002. Запуск из корня проекта:  python web54\\test_server.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'bot'))

import TestV3  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))

TestV3.app.template_folder = os.path.join(BASE, 'templates')
TestV3.app.static_folder = os.path.join(BASE, 'static')


# STAND-ONLY: пятый график web54-дашборда под V3-бэкендом (у V3 нет Open-Meteo).
# Отдаёт демо-заглушку, чтобы картинка не была битой в сравнивалке дизайнов.
@TestV3.app.route('/admin/chart/ref')
def _glm54_chart_ref():
    if not TestV3._web_is_admin():
        return 'Forbidden', 403
    rows = [(r[0], r[1], r[1]) for r in TestV3.get_test_chart_data('weekly')]
    buf = TestV3._create_chart_sync(rows, 'weekly', 'Сверка (стенд-заглушка V3)')
    return Response(buf.read(), mimetype='image/png')


# STAND-ONLY: шестой график web54-дашборда «Прогноз 24ч» под V3-бэкендом
# (у V3 нет ref_checks/прогноза) — демо-кривая, чтобы картинка не была битой.
@TestV3.app.route('/admin/chart/forecast')
def _glm54_chart_forecast():
    import datetime as _dt
    if not TestV3._web_is_admin():
        return 'Forbidden', 403
    rows = []
    now = _dt.datetime.now()
    for i in range(24):
        ts = now + _dt.timedelta(hours=1 + i)
        t = round(-2.0 + 4.0 * TestV3.math.sin(2 * TestV3.math.pi * (ts.hour - 9) / 24), 1)
        rows.append((ts.strftime('%d'), f"{ts.hour:02d}:00", t, 80, i))
    buf = TestV3._create_chart_sync(rows, 'daily', 'Прогноз 24ч (стенд-заглушка V3)')
    if not buf:
        return 'chart error', 500
    return Response(buf.read(), mimetype='image/png')


# STAND-ONLY: карточка «Погода рядом» под V3 — честно говорим, что нужен V4.
@TestV3.app.route('/admin/openmeteo/current')
def _glm54_om_current():
    if not TestV3._web_is_admin():
        return Response('{"ok":false,"error":"forbidden"}', mimetype='application/json', status=403)
    return Response('{"ok":false,"error":"официальная погода есть только в TestV4"}',
                    mimetype='application/json')


if __name__ == '__main__':
    print('GLM 5.4 admin UI: http://127.0.0.1:5003/admin  (пароль — из TestV3.ADMIN_PASS)')
    TestV3.app.run(host='127.0.0.1', port=5003, threaded=True,
                   debug=False, use_reloader=False)
