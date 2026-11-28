# -*- coding: utf-8 -*-
"""Смоук страницы «Активность» (GLM 5.4) против TestV4 через Flask test client."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'bot'))
import TestV4  # noqa: E402

app = TestV4.app
c = app.test_client()

ok = True

def check(name, cond, extra=''):
    global ok
    print(('PASS' if cond else 'FAIL'), name, extra)
    if not cond:
        ok = False

# 1. Без авторизации /admin/activity/data — 403
r = c.get('/admin/activity/data')
check('data без авторизации -> 403', r.status_code == 403, str(r.status_code))

# 2. Страница без авторизации -> редирект на /admin
r = c.get('/admin/activity')
check('страница без авторизации -> редирект', r.status_code == 302, str(r.status_code))

# 3. Логин
r = c.post('/admin', data={'password': TestV4.ADMIN_PASS})
check('логин -> 302', r.status_code == 302, str(r.status_code))

# 4. Страница активности
r = c.get('/admin/activity')
body = r.get_data(as_text=True)
check('страница -> 200', r.status_code == 200, str(r.status_code))
check('шаблон GLM (Созвездие активности)', 'Созвездие активности' in body)
check('three.min.js подключён', '/static/vendor/three.min.js' in body)
check('activity.css подключён', '/static/activity.css' in body)
check('activity3d.js подключён', '/static/activity3d.js' in body)
check('текст унаследовал base.html (nav)', ('Активность' in body))

# 5. Статика
for url in ('/static/activity.css', '/static/activity3d.js', '/static/vendor/three.min.js'):
    r = c.get(url)
    check('%s -> 200' % url, r.status_code == 200, '%d, %d байт' % (r.status_code, len(r.get_data())))

# 6. JSON снапшот
r = c.get('/admin/activity/data')
check('data -> 200', r.status_code == 200, str(r.status_code))
snap = json.loads(r.get_data(as_text=True))
check('data ok:true', snap.get('ok') is True)
users = snap.get('users', [])
check('data: пользователи есть', len(users) >= 1, 'users=%d' % len(users))
need = {'uid', 'name', 'username', 'act', 'blocked', 'times'}
check('поля пользователей ровно по контракту', all(need <= set(u) for u in users))
names = [u.get('name') or u.get('username') or str(u.get('uid')) for u in users]
print('     пользователи:', ', '.join(names), '| событий за 24ч:',
      sum(len(u.get('times', [])) for u in users))
for u in users:
    check('times — список строк HH:MM (%s)' % (u.get('name') or u['uid']),
          isinstance(u['times'], list) and all(isinstance(t, str) and len(t) == 5 for t in u['times']))

print()
print('ИТОГ:', 'OK' if ok else 'ЕСТЬ ПРОВАЛЫ')
sys.exit(0 if ok else 1)
