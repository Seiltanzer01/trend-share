// static/scripts.js

$(document).ready(function() {
    console.log("scripts.js загружен"); // Отладочное сообщение

    // Инициализация FastClick для устранения задержки на мобильных устройствах
    if ('addEventListener' in document) {
        FastClick.attach(document.body);
    }

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
                        }
                    })
                    .catch(error => {
                        console.error('Ошибка при отправке initData:', error);
                        alert('Произошла ошибка при авторизации.');
                    });
                } else {
                    console.log('initData уже обработано.');
                    tg.ready(); // Уведомляем Telegram, что Web App готов
                }
            }
        } catch (error) {
            console.error('Ошибка при обработке initData:', error);
            alert('Ошибка при обработке initData: ' + error.message);
        }
    })();

    // Обработчик для кнопки "Показать/Скрыть Фильтры"
    $('#toggle-filters').on('click', function(){
        $('#filters').slideToggle();
        const button = $(this);
        if (button.text().includes('Показать')) {
            button.html('<i class="fas fa-filter"></i> Скрыть Фильтры');
        } else {
            button.html('<i class="fas fa-filter"></i> Показать Фильтры');
        }
    });

    // Обработчик для кнопок раскрытия критериев
    $(document).on('click', '.collapse-button', function(){
        $(this).next('.category-content, .subcategory-content').slideToggle();
        // Переключаем класс для вращения стрелки
        $(this).toggleClass('rotated');
    });

    // Анимация при наведении на строки таблиц
    $(document).on('mouseenter', 'table tbody tr', function() {
        $(this).css('background-color', '#F0F8FF'); // AliceBlue
    });

    $(document).on('mouseleave', 'table tbody tr', function() {
        $(this).css('background-color', '');
    });

    // Открытие модального окна при клике на изображение
    $(document).on('click', '.clickable-image', function() {
        $('#modal').fadeIn();
        $('#modal-img').attr('src', $(this).attr('src'));
    });

    // Закрытие модального окна
    $(document).on('click', '.close', function() {
        $('#modal').fadeOut();
    });

    // Закрытие модального окна при клике вне изображения
    $('#modal').on('click', function(event) {
        if (!$(event.target).is('#modal-img')) {
            $(this).fadeOut();
        }
    });

    // Инициализация datepickers с улучшенной производительностью
    $("#start_date, #end_date, #trade_open_time, #trade_close_time").datepicker({
        dateFormat: 'yy-mm-dd',
        changeMonth: true,
        changeYear: true,
        showAnim: "slideDown",
        showButtonPanel: true
    });

    // Инициализация DataTables для таблиц с классом 'datatable'
    $('table.datatable').DataTable({
        responsive: true,
        language: {
            "url": "//cdn.datatables.net/plug-ins/1.13.6/i18n/ru.json"
        },
        "pageLength": 10,
        "lengthChange": false,
        "ordering": true,
        "info": false,
        "autoWidth": false,
        "columnDefs": [
            { "orderable": false, "targets": [3,5] } // Скриншот и Действия не сортируются
        ],
        "deferRender": true, // Улучшает производительность при больших таблицах
        "processing": true, // Показывает индикатор обработки
        "serverSide": false // Можно переключить на true при необходимости
    });

    // Инициализация iCheck для всех чекбоксов
    $('input[type="checkbox"]').iCheck({
        checkboxClass: 'icheckbox_square-blue',
        increaseArea: '20%' // Увеличение области для удобства на мобильных
    });

    // Оптимизация производительности через Lazy Loading изображений с использованием Lazysizes
    // Добавление классов для Lazysizes
    $('img.clickable-image').each(function(){
        $(this).addClass('lazyload');
    });
});
