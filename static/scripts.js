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

    // **Интеграция с Thirdweb**

    // Инициализация Thirdweb SDK
    const sdk = new thirdweb.ThirdwebSDK("base"); // Используем сеть Base. Убедитесь, что вы выбрали правильную сеть.

    let wallet;

    // Функция для подключения кошелька через Thirdweb
    async function connectWalletThirdweb() {
        try {
            wallet = await sdk.wallet.connect("injected"); // Используем подключение через браузерный кошелёк (например, MetaMask)

            const address = wallet.address;
            console.log("Подключённый адрес:", address);

            // Отправка адреса кошелька на сервер
            const formData = new FormData();
            formData.append('wallet_address', address);

            const resp = await fetch('/staking/set_wallet', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-CSRFToken': window.config.CSRF_TOKEN
                }
            });

            const data = await resp.json();
            if (data.status === 'success') {
                alert('Кошелёк успешно подключён!');
                window.location.reload();
            } else {
                alert('Ошибка при установке адреса кошелька: ' + (data.error || 'Неизвестная ошибка.'));
            }
        } catch (error) {
            console.error("Ошибка при подключении кошелька через Thirdweb:", error);
            alert("Произошла ошибка при подключении кошелька.");
        }
    }

    // Функция для подключения кошелька через WalletConnect с использованием Thirdweb
    async function connectWalletConnectThirdweb() {
        try {
            wallet = await sdk.wallet.connect("walletConnect"); // Подключение через WalletConnect

            const address = wallet.address;
            console.log("Подключённый адрес через WalletConnect:", address);

            // Отправка адреса кошелька на сервер
            const formData = new FormData();
            formData.append('wallet_address', address);

            const resp = await fetch('/staking/set_wallet', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-CSRFToken': window.config.CSRF_TOKEN
                }
            });

            const data = await resp.json();
            if (data.status === 'success') {
                alert('Кошелёк успешно подключён через WalletConnect!');
                window.location.reload();
            } else {
                alert('Ошибка при установке адреса кошелька: ' + (data.error || 'Неизвестная ошибка.'));
            }
        } catch (error) {
            console.error("Ошибка при подключении через WalletConnect через Thirdweb:", error);
            alert("Произошла ошибка при подключении кошелька через WalletConnect.");
        }
    }

    // Обработчик кнопки "Connect Wallet"
    if (document.getElementById('connectWalletBtn')) {
        document.getElementById('connectWalletBtn').addEventListener('click', connectWalletThirdweb);
    }

    // Обработчик кнопки "Reconnect Wallet"
    if (document.getElementById('reconnectWalletBtn')) {
        document.getElementById('reconnectWalletBtn').addEventListener('click', connectWalletThirdweb);
    }

    // Обработчик кнопки "Connect with MetaMask" через Thirdweb
    if (document.getElementById('connectMetaMask')) {
        document.getElementById('connectMetaMask').addEventListener('click', connectWalletThirdweb);
    }

    // Обработчик кнопки "Connect with WalletConnect" через Thirdweb
    if (document.getElementById('connectWalletConnect')) {
        document.getElementById('connectWalletConnect').addEventListener('click', connectWalletConnectThirdweb);
    }

    // Функция для проведения стейкинга через Thirdweb
    async function stakeTokens() {
        if (!wallet) {
            alert('Кошелёк не подключён. Пожалуйста, подключитесь через кошелёк.');
            return;
        }

        try {
            const contract = await sdk.getContractFromAbi(window.config.TOKEN_CONTRACT_ADDRESS, [
                {
                    "inputs": [
                        {
                            "internalType": "address",
                            "name": "_to",
                            "type": "address"
                        },
                        {
                            "internalType": "uint256",
                            "name": "_value",
                            "type": "uint256"
                        }
                    ],
                    "name": "transfer",
                    "outputs": [
                        {
                            "internalType": "bool",
                            "name": "",
                            "type": "bool"
                        }
                    ],
                    "stateMutability": "nonpayable",
                    "type": "function"
                }
            ]);

            // Отправка токенов на адрес контракта
            const tx = await contract.call("transfer", window.config.MY_WALLET_ADDRESS, window.config.TOKEN_AMOUNT_WEI, {
                gasLimit: 100000 // Установите подходящий лимит газа
            });

            alert('Транзакция отправлена! Хэш транзакции: ' + tx.receipt.transactionHash);
            console.log("Транзакция отправлена:", tx.receipt.transactionHash);

            // Отправка события в Telegram WebView
            if (window.Telegram && window.Telegram.WebView) {
                window.Telegram.WebView.postEvent('stake_initiated', JSON.stringify({ txHash: tx.receipt.transactionHash }));
            }

        } catch (error) {
            console.error("Ошибка при стейкинге через Thirdweb:", error);
            alert("Произошла ошибка при проведении стейкинга.");
        }
    }

    // Обработчик кнопки "Stake"
    if(document.getElementById('stakeButton')){
        document.getElementById('stakeButton').addEventListener('click', stakeTokens);
    }

    // Функция для загрузки и отображения стейков пользователя
    async function loadStaking() {
        try {
            const resp = await fetch('/staking/get_user_stakes')
            const data = await resp.json()
            if(data.error) {
                document.getElementById('stakingArea').innerHTML = '<p>'+data.error+'</p>'
                document.getElementById('claimRewardsBtn').style.display='none'
                document.getElementById('unstakeBtn').style.display='none'
                return
            }
            const stakes = data.stakes
            if(!stakes.length) {
                document.getElementById('stakingArea').innerHTML = '<p>У вас нет стейка.</p>'
                document.getElementById('claimRewardsBtn').style.display='none'
                document.getElementById('unstakeBtn').style.display='none'
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
            document.getElementById('stakingArea').innerHTML = html
            document.getElementById('claimRewardsBtn').style.display='inline-block'
            document.getElementById('unstakeBtn').style.display='inline-block'
        } catch (error) {
            console.error('Ошибка при загрузке стейков:', error)
            document.getElementById('stakingArea').innerHTML = '<p>Произошла ошибка при загрузке стейков.</p>'
            document.getElementById('claimRewardsBtn').style.display='none'
            document.getElementById('unstakeBtn').style.display='none'
        }
    }

    // Обработчик кнопки "Claim Rewards"
    if(document.getElementById('claimRewardsBtn')){
        document.getElementById('claimRewardsBtn').addEventListener('click', async()=> {
            try {
                const csrfToken = window.config.CSRF_TOKEN;
                const resp = await fetch('/staking/claim_staking_rewards',{
                    method:'POST',
                    headers: {
                        'X-CSRFToken': csrfToken
                    }
                })
                const data = await resp.json()
                if(data.error) alert(data.error)
                else {
                    alert(data.message)
                    loadStaking()
                    // Отправка события в Telegram WebView
                    if (window.Telegram && window.Telegram.WebView) {
                        window.Telegram.WebView.postEvent('rewards_claimed', JSON.stringify({ message: data.message }));
                    }
                }
            } catch (error) {
                alert('Произошла ошибка при клейме наград: ' + error)
            }
        });
    }

    // Обработчик кнопки "Unstake"
    if(document.getElementById('unstakeBtn')){
        document.getElementById('unstakeBtn').addEventListener('click', async()=>{
            try {
                const csrfToken = window.config.CSRF_TOKEN;
                const resp = await fetch('/staking/unstake_staking',{
                    method:'POST',
                    headers: {
                        'X-CSRFToken': csrfToken
                    }
                })
                const data = await resp.json()
                if(data.error) alert(data.error)
                else {
                    alert(data.message)
                    loadStaking()
                    // Отправка события в Telegram WebView
                    if (window.Telegram && window.Telegram.WebView) {
                        window.Telegram.WebView.postEvent('unstaked', JSON.stringify({ message: data.message }));
                    }
                }
            } catch (error) {
                alert('Произошла ошибка при unstake: ' + error)
            }
        });
    }

    // Инициализация подключения кошелька и загрузка стейкинговых данных
    document.addEventListener('DOMContentLoaded', ()=> {
        loadStaking()
    });

    // Интеграция с Telegram WebView для получения событий от нативного приложения
    if (window.Telegram && window.Telegram.WebView) {
        window.Telegram.WebView.onEvent = function(eventType, eventData) {
            console.log(`Получено событие от Telegram: ${eventType}`, eventData);
            // Обработка событий от нативного приложения, если необходимо
            // Например, обновление UI после определённых действий
        };
    }
});
