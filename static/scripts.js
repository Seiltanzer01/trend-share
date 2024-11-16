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
                // Убедитесь, что элемент с id="debug" существует в webapp.html
                $('#debug').text('Telegram WebApp не найден');
                return;
            }

            const initData = tg.initData || tg.initDataUnsafe || '';

            console.log('initData:', initData);
            $('#debug').text('initData: ' + initData);
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
                            $('#debug').text('Ошибка авторизации: ' + data.message);
                        }
                    })
                    .catch(error => {
                        console.error('Ошибка при отправке initData:', error);
                        alert('Произошла ошибка при авторизации.');
                        $('#debug').text('Ошибка при отправке initData: ' + error.message);
                    });
                } else {
                    console.log('initData уже обработано.');
                    $('#debug').text('initData уже обработано.');
                    tg.ready(); // Уведомляем Telegram, что Web App готов
                }
            }
        } catch (error) {
            console.error('Ошибка при обработке initData:', error);
            alert('Ошибка при обработке initData: ' + error.message);
            $('#debug').text('Ошибка при обработке initData: ' + error.message);
        }
    })();

    // Остальные скрипты

    // Пример анимации при наведении на строки таблицы
    $('table tr').hover(
        function() {
            $(this).css('background-color', '#F0F8FF'); // AliceBlue
        },
        function() {
            $(this).css('background-color', '');
        }
    );

    // Открытие модального окна при клике на изображение
    $('.clickable-image').on('click', function() {
        $('#modal').css('display', 'block');
        $('#modal-img').attr('src', $(this).attr('src'));
    });

    // Закрытие модального окна
    $('.close').on('click', function() {
        $('#modal').css('display', 'none');
    });

    // Закрытие модального окна при клике вне изображения
    $('#modal').on('click', function(event) {
        if (!$(event.target).is('#modal-img')) {
            $(this).css('display', 'none');
        }
    });

    // Раскрывающиеся списки для категорий и подкатегорий
    $('.collapse-button').click(function(){
        $(this).next().toggle();
    });

    // Инициализация datepickers
    $("#start_date, #end_date, #trade_open_time, #trade_close_time").datepicker({
        dateFormat: 'yy-mm-dd',
        changeMonth: true,
        changeYear: true
    });

    // Блок для отображения отладочной информации
    $('#debug').css({
        'position': 'fixed',
        'bottom': '10px',
        'left': '10px',
        'background-color': 'rgba(255, 255, 255, 0.8)',
        'padding': '10px',
        'border': '1px solid #ccc',
        'border-radius': '5px',
        'max-width': '300px',
        'overflow': 'auto',
        'max-height': '200px'
    });
});
