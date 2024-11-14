// static/scripts.js

$(document).ready(function() {
    // Обработка Telegram Web App initData
    (function() {
        try {
            const tg = window.Telegram.WebApp;
            if (!tg) {
                console.error('Telegram WebApp не найден');
                alert('Telegram WebApp не найден');
                $('#debug').text('Telegram WebApp не найден');
                return;
            }

            const initData = tg.initData || tg.initDataUnsafe || '';

            console.log('initData:', initData);
            $('#debug').text('initData: ' + initData);
            if (initData === '') {
                // Инициализация Web App
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
                            initData: btoa(initData) // Base64-кодирование initData
                        })
                    })
                    .then(response => response.json())
                    .then(data => {
                        if(data.status === 'success') {
                            console.log('Авторизация успешна');
                            tg.close(); // Закрыть Web App после успешной авторизации
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
