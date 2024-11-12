// static/scripts.js

$(document).ready(function() {
    // Обработка Telegram Web App initData
    (function() {
        const tg = window.Telegram.WebApp;
        const initData = tg.initData || tg.initDataUnsafe || '';

        console.log('initData:', initData);
        $('#debug').text('initData: ' + initData);

        if (initData && !sessionStorage.getItem('initDataProcessed')) {
            console.log('Processing initData...');
            // Перенаправляем на сервер с параметром initData
            const url = new URL(window.location.href);
            url.searchParams.set('initData', initData);
            sessionStorage.setItem('initDataProcessed', 'true'); // Флаг, чтобы избежать повторного перенаправления
            window.location.href = url.toString();
        } else {
            console.log('No initData or already processed.');
            tg.ready(); // Уведомляем Telegram, что Web App готов
        }
    })();

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
    $("#start_date, #end_date").datepicker({
        dateFormat: 'yy-mm-dd',
        changeMonth: true,
        changeYear: true
    });

    // Если у вас есть другие интерактивные элементы, их можно добавить здесь
});
