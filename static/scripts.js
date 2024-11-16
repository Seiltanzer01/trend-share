// static/scripts.js

$(document).ready(function() {
    console.log("scripts.js загружен"); // Отладочное сообщение

    // Обработка Telegram Web App initData
    (function() {
        try {
            const tg = window.Telegram.WebApp;
            if (!tg) {
                console.error('Telegram WebApp не найден');
                alert('Telegram WebApp не найден');
                return;
            }

            const initData = tg.initData || tg.initDataUnsafe || '';
            console.log('initData:', initData);

            if (initData === '') {
                // Инициализация Web App
                console.log('initData пустое, вызываем tg.ready()');
                tg.ready(); // Уведомляем Telegram, что Web App готов
            } else {
                // Отправка initData на сервер через AJAX POST запрос
                if (!sessionStorage.getItem('initDataProcessed')) {
                    console.log('Отправка initData на сервер...');
                    sessionStorage.setItem('initDataProcessed', 'true'); // Флаг, чтобы избежать повторной отправки

                    fetch('/init', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            initData: initData // Отправляем без Base64-кодирования
                        }),
                        credentials: 'include' // Включает куки в запрос
                    })
                    .then(response => {
                        console.log('Получен ответ от сервера:', response);
                        return response.json();
                    })
                    .then(data => {
                        console.log('Данные от сервера:', data);
                        if(data.status === 'success') {
                            console.log('Авторизация успешна');
                            // Автоматическое перенаправление на главную страницу
                            window.location.href = '/';
                        } else {
                            console.error('Ошибка авторизации:', data.message);
                            alert('Ошибка авторизации: ' + data.message);
                            tg.close(); // Закрыть Web App в случае ошибки
                        }
                    })
                    .catch(error => {
                        console.error('Ошибка при отправке initData:', error);
                        alert('Произошла ошибка при авторизации.');
                        tg.close(); // Закрыть Web App в случае ошибки
                    });
                } else {
                    console.log('initData уже обработано.');
                    tg.ready(); // Уведомляем Telegram, что Web App готов
                }
            }
        } catch (error) {
            console.error('Ошибка при обработке initData:', error);
            alert('Ошибка при обработке initData: ' + error.message);
            tg.close(); // Закрыть Web App в случае ошибки
        }
    })();

    // Остальные скрипты (если необходимо)
});
