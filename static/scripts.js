// static/scripts.js

$(document).ready(function() {
    console.log("scripts.js загружен"); // Отладочное сообщение

    // Добавляем отладочное сообщение для проверки window.config
    console.log("Window config:", window.config); 

    // Инициализация FastClick для устранения задержки на мобильных устройствах
    if ('addEventListener' in document) {
        FastClick.attach(document.body);
    }

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

    // Функция для получения CSRF-токена из window.config
    function getCSRFToken() {
        return window.config.CSRF_TOKEN;
    }

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
                const csrfToken = getCSRFToken();
                const response = await fetch('/clear_chat_history', {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': csrfToken
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

    // **Новые функции для уникальных кошельков и стейкинга**
    // Эти обработчики удалены, чтобы избежать дублирования после объединения шаблонов.

    // Функция для загрузки и отображения балансов
    async function loadBalances(){
        try{
            const response = await fetch('/staking/api/get_balances', {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            const data = await response.json();
            if(data.error){
                $('#ethBalance').text('Error');
                $('#wethBalance').text('Error');
                $('#ujoBalance').text('Error');
            } else{
                $('#ethBalance').text(data.balances.eth.toFixed(4));
                $('#wethBalance').text(data.balances.weth.toFixed(4));
                $('#ujoBalance').text(data.balances.ujo.toFixed(4));
            }
        } catch(error){
            console.error("Ошибка при загрузке балансов:", error);
            $('#ethBalance').text('Error');
            $('#wethBalance').text('Error');
            $('#ujoBalance').text('Error');
        }
    }

    // Вызов загрузки балансов при загрузке страницы
    loadBalances();

    // Обработчик формы обмена WETH на UJO
    $('#exchangeForm').on('submit', async function(e){
        e.preventDefault();
        const amountWETH = parseFloat($('#exchangeAmount').val());
        if(isNaN(amountWETH) || amountWETH <= 0){
            alert('Пожалуйста, введите корректное количество WETH для обмена.');
            return;
        }

        try{
            const csrfToken = window.config.CSRF_TOKEN;
            const response = await fetch('/staking/exchange_weth_to_ujo', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ amount_weth: amountWETH })
            });

            const data = await response.json();
            if(data.status === 'success'){
                alert('Обмен успешно выполнен! Вы получили ' + data.ujo_received.toFixed(4) + ' UJO.');
                loadBalances();
            } else{
                alert('Ошибка: ' + data.error);
            }
        } catch(error){
            console.error("Ошибка при обмене:", error);
            alert("Произошла ошибка при обмене.");
        }
    });

    // Обработчик формы подтверждения стейкинга
    $('#confirmStakeForm').on('submit', async function(e){
        e.preventDefault();
        const txHash = $('#tx_hash').val().trim();
        if(!txHash){
            alert('Пожалуйста, введите хэш транзакции.');
            return;
        }

        // Простейшая валидация формата txHash
        if(!/^0x([A-Fa-f0-9]{64})$/.test(txHash)){
            alert('Некорректный формат хэша транзакции.');
            return;
        }

        try{
            const csrfToken = window.config.CSRF_TOKEN;
            const response = await fetch('/staking/confirm', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ txHash: txHash })
            });

            const data = await response.json();
            if(data.status === 'success'){
                alert('Стейкинг успешно подтверждён!');
                loadStaking();
                loadBalances();
            } else{
                alert('Ошибка: ' + data.error);
            }
        } catch(error){
            console.error("Ошибка при подтверждении стейкинга:", error);
            alert("Произошла ошибка при подтверждении стейкинга.");
        }
    });

    // Обработчик кнопки "Stake" - чтобы показать инструкцию
    if(document.getElementById('stakeButton')){
        document.getElementById('stakeButton').addEventListener('click', function(){
            // Инструкции для пользователя
            alert('Чтобы застейкать, отправьте 25$ (примерно) UJO на ваш уникальный кошелёк. После отправки подтвердите транзакцию, введя её хэш ниже.');
        });
    }

    // Функция для загрузки и отображения стейков пользователя
    async function loadStaking() {
        try {
            const resp = await fetch('/staking/get_user_stakes')
            const data = await resp.json()
            if(data.error) {
                $('#stakingArea').html('<p>'+data.error+'</p>')
                $('#claimRewardsBtn').hide()
                $('#unstakeBtn').hide()
                return
            }
            const stakes = data.stakes
            if(!stakes.length) {
                $('#stakingArea').html('<p>У вас нет стейкинга.</p>')
                $('#claimRewardsBtn').hide()
                $('#unstakeBtn').hide()
                return
            }
            let html=''
            for(let s of stakes) {
                html += `<div class="nes-container is-rounded" style="margin-bottom:1rem;">
                  <p><b>TX Hash:</b> ${s.tx_hash}</p>
                  <p>Staked: ${s.staked_amount} UJO (~${s.staked_usd}$)</p>
                  <p>Pending Rewards: ${s.pending_rewards} UJO</p>
                  <p>Unlocked At: ${new Date(s.unlocked_at).toLocaleString()}</p>
                </div>`
            }
            $('#stakingArea').html(html)
            $('#claimRewardsBtn').show()
            $('#unstakeBtn').show()
        } catch (error) {
            console.error('Ошибка при загрузке стейков:', error)
            $('#stakingArea').html('<p>Произошла ошибка при загрузке стейков.</p>')
            $('#claimRewardsBtn').hide()
            $('#unstakeBtn').hide()
        }
    }

    // Обработчик кнопки "Claim Rewards"
    $('#claimRewardsBtn').on('click', async function(){
        try {
            const csrfToken = window.config.CSRF_TOKEN;
            const response = await fetch('/staking/claim_staking_rewards',{
                method:'POST',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'Content-Type': 'application/json'
                }
            })
            const data = await response.json()
            if(data.error) alert(data.error)
            else {
                alert(data.message)
                loadStaking()
                loadBalances()
            }
        } catch (error) {
            alert('Произошла ошибка при клейме наград: ' + error)
        }
    });

    // Обработчик кнопки "Unstake"
    $('#unstakeBtn').on('click', async function(){
        try {
            const csrfToken = window.config.CSRF_TOKEN;
            const response = await fetch('/staking/unstake_staking',{
                method:'POST',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'Content-Type': 'application/json'
                }
            })
            const data = await response.json()
            if(data.error) alert(data.error)
            else {
                alert(data.message)
                loadStaking()
                loadBalances()
            }
        } catch (error) {
            alert('Произошла ошибка при unstake: ' + error)
        }
    });

    // Инициализация подключения кошелька и загрузка стейкинговых данных
    document.addEventListener('DOMContentLoaded', ()=> {
        loadStaking()
    });

    // Удалены все Thirdweb-интеграции, а также Telegram WebView интеграция

});
