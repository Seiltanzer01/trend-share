// static/scripts.js

$(document).ready(function() {
    // Пример анимации при наведении на строки таблицы
    $('table tr').hover(
        function() {
            $(this).css('background-color', '#F0F8FF'); // AliceBlue
        },
        function() {
            $(this).css('background-color', '');
        }
    );

    // Дополнительные интерактивные функции можно добавить здесь

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
    $("#trade_open_time, #trade_close_time").datepicker({
        dateFormat: 'yy-mm-dd'
    });

    // Telegram WebApp взаимодействие
    if (window.Telegram.WebApp) {
        // Инициализация WebApp
        Telegram.WebApp.ready();

        // Отправка данных пользователя на сервер
        $.ajax({
            url: '/telegram_auth',
            method: 'POST',
            dataType: 'json',
            contentType: 'application/json',
            data: JSON.stringify(Telegram.WebApp.initDataUnsafe.user),
            success: function(response) {
                console.log('Пользователь авторизован через Telegram WebApp.');
                window.location.href = '/';
            },
            error: function(error) {
                console.log('Ошибка авторизации через Telegram WebApp.');
            }
        });
    }
});
