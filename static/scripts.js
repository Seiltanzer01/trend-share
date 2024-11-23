// static/scripts.js

$(document).ready(function() {
    // Обработка Telegram Web App initData
    (function() {
        try {
            const tg = window.Telegram.WebApp;
            if (!tg) {
                alert('Telegram WebApp не найден');
                return;
            }

            const initData = tg.initData || tg.initDataUnsafe || '';

            if (initData === '') {
                // Инициализация Web App
                tg.ready(); // Уведомляем Telegram, что Web App готов
            } else {
                // Отправка initData на сервер через AJAX POST запрос
                if (!sessionStorage.getItem('initDataProcessed')) {
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
                    .then(response => response.json())
                    .then(data => {
                        if(data.status === 'success') {
                            // Автоматическое перенаправление на главную страницу
                            window.location.href = '/';
                        } else {
                            alert('Ошибка авторизации: ' + data.message);
                        }
                    })
                    .catch(() => {
                        alert('Произошла ошибка при авторизации.');
                    });
                } else {
                    tg.ready(); // Уведомляем Telegram, что Web App готов
                }
            }
        } catch (error) {
            alert('Ошибка при обработке initData: ' + error.message);
        }
    })();

    // Обработчик для кнопки "Показать/Скрыть Фильтры"
    $('#toggle-filters').click(function(){
        $('#filters').slideToggle();
        const button = $(this);
        if (button.text().includes('Показать')) {
            button.html('<i class="fas fa-filter"></i> Скрыть Фильтры');
        } else {
            button.html('<i class="fas fa-filter"></i> Показать Фильтры');
        }
    });

    // Обработчик для кнопок раскрытия критериев
    $('.collapse-button').click(function(){
        $(this).next('.category-content, .subcategory-content').slideToggle();
        // Переключаем класс для вращения стрелки
        $(this).toggleClass('rotated');
    });

    // Анимация при наведении на строки таблиц
    $('table tbody').on('mouseenter', 'tr', function() {
        $(this).css('background-color', '#F0F8FF'); // AliceBlue
    }).on('mouseleave', 'tr', function() {
        $(this).css('background-color', '');
    });

    // Открытие модального окна при клике на изображение
    $('.clickable-image').on('click', function() {
        $('#modal').fadeIn();
        $('#modal-img').attr('src', $(this).attr('src'));
    });

    // Закрытие модального окна
    $('.close').on('click', function() {
        $('#modal').fadeOut();
    });

    // Закрытие модального окна при клике вне изображения
    $('#modal').on('click', function(event) {
        if (!$(event.target).is('#modal-img')) {
            $(this).fadeOut();
        }
    });

    // Инициализация datepickers
    $("#start_date, #end_date, #trade_open_time, #trade_close_time").datepicker({
        dateFormat: 'yy-mm-dd',
        changeMonth: true,
        changeYear: true,
        showAnim: "slideDown",
        showButtonPanel: true
    });
});
