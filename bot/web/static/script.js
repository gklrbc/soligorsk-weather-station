// Веб-админка «Солигорск»: подтверждения, автообновление графиков, фильтры таблиц

// Подтверждение опасных действий (блокировка, удаление, рассылка, бэкап, тест-режим)
document.querySelectorAll('form[data-confirm], button[data-confirm], [data-confirm]').forEach(el => {
    const handler = (e) => {
        if (!confirm(el.dataset.confirm)) {
            e.preventDefault();
            e.stopPropagation();
        }
    };
    if (el.tagName === 'FORM') {
        el.addEventListener('submit', handler);
    } else {
        el.closest('form')?.addEventListener('submit', handler);
    }
});

// Автообновление графиков раз в минуту (без перезагрузки страницы).
// Пока картинка перезагружается — приглушаем её, чтобы обновление читалось как состояние
setInterval(() => {
    document.querySelectorAll('img[data-autorefresh]').forEach(img => {
        img.classList.add('refreshing');
        img.onload = () => img.classList.remove('refreshing');
        img.onerror = () => img.classList.remove('refreshing');
        // Сохраняем параметры (demo и т.п.), меняя только метку версии
        const url = new URL(img.src, location.href);
        url.searchParams.set('v', Date.now());
        img.src = url.toString();
    });
}, 60000);

// Живой фильтр таблиц: input[data-filter="#table-id"]
document.querySelectorAll('[data-filter]').forEach(input => {
    const table = document.querySelector(input.dataset.filter);
    if (!table) return;
    input.addEventListener('input', () => {
        const q = input.value.trim().toLowerCase();
        table.querySelectorAll('tbody tr, tr').forEach(tr => {
            if (tr.querySelector('th')) return; // шапку не трогаем
            tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';
        });
    });
});
