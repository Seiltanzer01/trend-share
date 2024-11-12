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
                alert('initData отсутствует. Убедитесь, что вы открываете приложение через Telegram.');
            } else {
                alert('initData получено: ' + initData);
            }

            if (initData && !sessionStorage.getItem('initDataProcessed')) {
                console.log('Processing initData...');
                alert('Processing initData...');
                // Перенаправляем на сервер с параметром initData
                const url = new URL(window.location.href);
                url.searchParams.set('initData', initData);
                sessionStorage.setItem('initDataProcessed', 'true'); // Флаг, чтобы избежать повторного перенаправления
                window.location.href = url.toString();
            } else {
                console.log('No initData or already processed.');
                if (initData) {
                    alert('initData уже обработано.');
                } else {
                    alert('initData отсутствует или уже обработано.');
                }
                tg.ready(); // Уведомляем Telegram, что Web App готов
            }
        } catch (error) {
            console.error('Ошибка при обработке initData:', error);
            alert('Ошибка при обработке initData: ' + error.message);
            $('#debug').text('Ошибка при обработке initData: ' + error.message);
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
