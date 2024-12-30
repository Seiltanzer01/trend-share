// static/scripts.js

$(document).ready(function() {
    console.log("scripts.js загружен"); // Отладочное сообщение

    // Инициализация FastClick для устранения задержки на мобильных устройствах
    if ('addEventListener' in document) {
        FastClick.attach(document.body);
    }

    // **Удален блок обработки Telegram WebApp initData**
    // Теперь авторизация через Telegram WebApp обрабатывается только на странице webapp.html

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

    // Инициализация DataTables для таблицы Setup
    $('#setup-table').DataTable({
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

    // Инициализация DataTables для таблицы Trade
    $('#trade-table').DataTable({
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
            { "orderable": false, "targets": [1,12] } // Скриншот и Действия не сортируются
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

    // **Обработчики для Ассистента "Дядя Джон"**

    // Массив для хранения истории чата
    let chatHistory = [];

    const assistantForm = document.getElementById('assistant-form');
    const chartForm = document.getElementById('chart-analysis-form');
    const chatHistoryDiv = document.getElementById('chat-history');
    const assistantQuestionInput = document.getElementById('assistant-question');
    const chartAnalysisResult = document.getElementById('chart-analysis-result');
    const analysisChartDiv = document.getElementById('analysis-chart');
    const clearChatButton = document.getElementById('clear-chat');

    // Функция для обновления отображения истории чата
    function updateChatHistoryDisplay() {
        chatHistoryDiv.innerHTML = ''; // Очистка текущего содержимого

        chatHistory.forEach(message => {
            const msgDiv = document.createElement('div');
            msgDiv.className = message.role === 'user' ? 'nes-balloon from-right' : 'nes-balloon from-left is-dark';
            // Если содержимое — объект, преобразуем его в строку
            const content = (typeof message.content === 'object') ? JSON.stringify(message.content, null, 2) : message.content;
            msgDiv.textContent = content;
            chatHistoryDiv.appendChild(msgDiv);
        });

        // Прокрутка вниз
        chatHistoryDiv.scrollTop = chatHistoryDiv.scrollHeight;
    }

    // Функция для загрузки истории чата с сервера (если необходимо)
    async function loadChatHistory() {
        try {
            const response = await fetch('/get_chat_history');
            const data = await response.json();
            console.log('Chat History:', data); // Для отладки
            if (data.chat_history) {
                chatHistory = data.chat_history;
                updateChatHistoryDisplay();
            }
        } catch (error) {
            console.error('Ошибка при загрузке истории чата:', error);
        }
    }

    // Загрузка истории чата при загрузке страницы (если необходимо)
    // loadChatHistory(); // Раскомментируйте, если есть такая необходимость

    // Обработка отправки формы чата
    if (assistantForm) {
        assistantForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            const question = assistantQuestionInput.value.trim();
            if (!question) return;

            // Добавление сообщения пользователя в историю
            chatHistory.push({ role: 'user', content: question });
            updateChatHistoryDisplay();

            // Отправка запроса на сервер
            try {
                const response = await fetch('/assistant/chat', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ question: question })
                });

                const data = await response.json();
                console.log('Chat Response:', data); // Для отладки
                if (data.response) {
                    // Добавление ответа ассистента в историю
                    const assistantContent = (typeof data.response === 'object') ? JSON.stringify(data.response, null, 2) : data.response;
                    chatHistory.push({ role: 'assistant', content: assistantContent });
                    updateChatHistoryDisplay();
                } else if (data.error) {
                    // Обработка ошибок
                    const errorMsg = `Ошибка: ${data.error}`;
                    chatHistory.push({ role: 'assistant', content: errorMsg });
                    updateChatHistoryDisplay();
                }
            } catch (error) {
                console.error('Ошибка при отправке запроса:', error);
                const errorMsg = 'Произошла ошибка при отправке вашего запроса.';
                chatHistory.push({ role: 'assistant', content: errorMsg });
                updateChatHistoryDisplay();
            }

            // Очистка поля ввода
            assistantQuestionInput.value = '';
        });
    }

    // Обработка отправки формы анализа графика
    if (chartForm) {
        chartForm.addEventListener('submit', async function(e){
            e.preventDefault();
            const imageInput = document.getElementById('chart-image');
            const file = imageInput.files[0];
            if (!file) {
                alert('Пожалуйста, выберите изображение.');
                return;
            }

            // Отображение индикатора загрузки
            chartAnalysisResult.textContent = 'Идет анализ...';
            analysisChartDiv.innerHTML = '';

            const formData = new FormData();
            formData.append('image', file);

            try {
                const response = await fetch('/assistant/analyze_chart', {
                    method: 'POST',
                    body: formData
                });

                const data = await response.json();
                console.log('Chart Analysis Response:', data); // Для отладки
                if (data.result && data.result.trend_prediction) {
                    // Отображение прогноза тренда
                    chartAnalysisResult.innerHTML = `<pre>${data.result.trend_prediction}</pre>`;
                    // Если вы хотите отображать график, убедитесь, что бэкенд возвращает chart_url
                    // В текущем случае этого нет, поэтому оставляем пустым
                    analysisChartDiv.innerHTML = '';
                } else if (data.error) {
                    // Обработка ошибок
                    const errorMsg = `Ошибка: ${data.error}`;
                    chartAnalysisResult.innerHTML = `<p class="nes-text is-error">${errorMsg}</p>`;
                    analysisChartDiv.innerHTML = '';
                }
            } catch (error) {
                console.error('Ошибка при анализе графика:', error);
                chartAnalysisResult.innerHTML = '<p class="nes-text is-error">Произошла ошибка при анализе графика.</p>';
                analysisChartDiv.innerHTML = '';
            }

            // Очистка поля ввода файла
            imageInput.value = '';
        });
    }

    // Обработка кнопки очистки чата
    if (clearChatButton) {
        clearChatButton.addEventListener('click', async function() {
            try {
                const response = await fetch('/clear_chat_history', {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': getCSRFToken()
                    }
                });
                const data = await response.json();
                if (data.status === 'success') {
                    chatHistory = [];
                    updateChatHistoryDisplay();
                }
            } catch (error) {
                console.error('Ошибка при очистке чата:', error);
            }
        });
    }

    // Функция для получения CSRF-токена из cookie
    function getCSRFToken() {
        const name = 'csrf_token=';
        const decodedCookie = decodeURIComponent(document.cookie);
        const ca = decodedCookie.split(';');
        for(let i = 0; i < ca.length; i++) {
            let c = ca[i];
            while (c.charAt(0) === ' ') {
                c = c.substring(1);
            }
            if (c.indexOf(name) === 0) {
                return c.substring(name.length, c.length);
            }
        }
        return "";
    }

    // Добавление обработчика для формы подтверждения стейкинга
    const confirmStakeForm = document.getElementById('confirmStakeForm');
    if(confirmStakeForm){
        confirmStakeForm.addEventListener('submit', async function(e){
            e.preventDefault();
            const txHashInput = document.getElementById('tx_hash');
            const txHash = txHashInput.value.trim();
            if(!txHash){
                alert('Пожалуйста, введите хэш транзакции.');
                return;
            }

            // Получение CSRF-токена
            const csrfToken = getCSRFToken();

            try {
                const response = await fetch('/staking/confirm', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken
                    },
                    body: JSON.stringify({ txHash: txHash })
                });

                const data = await response.json();
                if(data.status === 'success'){
                    alert('Стейкинг успешно подтверждён!');
                    // Очистка формы
                    txHashInput.value = '';
                    // Обновление списка стейков
                    loadStaking();
                } else {
                    alert('Ошибка: ' + (data.error || 'Неизвестная ошибка.'));
                }
            } catch(e){
                alert('Произошла ошибка при подтверждении стейкинга: ' + e);
            }
        });
    }

    // Функция для загрузки и отображения стейков пользователя
    async function loadStaking() {
        const resp = await fetch('/staking/get_user_stakes');
        const data = await resp.json();
        if(data.error) {
            document.getElementById('stakingArea').innerHTML = '<p>'+data.error+'</p>';
            document.getElementById('claimRewardsBtn').style.display='none';
            document.getElementById('unstakeBtn').style.display='none';
            return;
        }
        const stakes = data.stakes;
        if(!stakes.length) {
            document.getElementById('stakingArea').innerHTML = '<p>У вас нет стейка.</p>';
            document.getElementById('claimRewardsBtn').style.display='none';
            document.getElementById('unstakeBtn').style.display='none';
            return;
        }
        let html='';
        for(let s of stakes) {
            html += `<div class="nes-container is-rounded" style="margin-bottom:1rem;">
              <p><b>TX Hash:</b> ${s.tx_hash}</p>
              <p>Staked: ${s.staked_amount} UJO (~${s.staked_usd}$)</p>
              <p>Pending Rewards: ${s.pending_rewards} UJO</p>
              <p>Unlocked At: ${new Date(s.unlocked_at).toLocaleString()}</p>
            </div>`;
        }
        document.getElementById('stakingArea').innerHTML = html;
        document.getElementById('claimRewardsBtn').style.display='inline-block';
        document.getElementById('unstakeBtn').style.display='inline-block';
    }

    // Инициализация подключения кошелька и загрузка стейкинговых данных
    document.addEventListener('DOMContentLoaded', ()=> {
        const btnConn = document.getElementById('connectWalletBtn');
        if(btnConn) btnConn.addEventListener('click', connectWallet);

        loadStaking();

        // Обработчик кнопки "Claim Rewards"
        const claimRewardsBtn = document.getElementById('claimRewardsBtn');
        if(claimRewardsBtn){
            claimRewardsBtn.addEventListener('click', async()=> {
                // Получение CSRF-токена
                const csrfToken = getCSRFToken();

                const resp = await fetch('/staking/claim_staking_rewards',{
                    method:'POST',
                    headers: {
                        'X-CSRFToken': csrfToken
                    }
                });
                const data = await resp.json();
                if(data.error) alert(data.error);
                else {
                    alert(data.message);
                    loadStaking();
                }
            });
        }

        // Обработчик кнопки "Unstake"
        const unstakeBtn = document.getElementById('unstakeBtn');
        if(unstakeBtn){
            unstakeBtn.addEventListener('click', async()=>{
                // Получение CSRF-токена
                const csrfToken = getCSRFToken();

                const resp = await fetch('/staking/unstake_staking',{
                    method:'POST',
                    headers: {
                        'X-CSRFToken': csrfToken
                    }
                });
                const data = await resp.json();
                if(data.error) alert(data.error);
                else {
                    alert(data.message);
                    loadStaking();
                }
            });
        }
    });
});
