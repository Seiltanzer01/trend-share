// static/scripts.js

$(document).ready(function() {
    console.log("scripts.js loaded"); // Debug message

    // Debug message to check window.config
    console.log("Window config:", window.config); 

    // Initialize FastClick to remove the 300ms delay on mobile devices
    if ('addEventListener' in document) {
        FastClick.attach(document.body);
    }

    // Handler for "Show/Hide Filters" button
    $('#toggle-filters').on('click', function(){
        $('#filters').slideToggle();
        const button = $(this);
        // Switch the text in English
        if (button.text().includes('Show')) {
            button.html('<i class="fas fa-filter"></i> Hide Filters');
        } else {
            button.html('<i class="fas fa-filter"></i> Show Filters');
        }
    });

    // Handler for collapsible criteria buttons
    $(document).on('click', '.collapse-button', function(){
        $(this).next('.category-content, .subcategory-content').slideToggle();
        $(this).toggleClass('rotated');
    });

    // Row hover animation in tables
    $(document).on('mouseenter', 'table tbody tr', function() {
        $(this).css('background-color', '#F0F8FF'); // AliceBlue
    });
    $(document).on('mouseleave', 'table tbody tr', function() {
        $(this).css('background-color', '');
    });

// ***** Модальное окно – реализация через переключение CSS-класса *****
let modalJustClosed = false;

// Функция открытия модального окна
function openModal(src) {
    if (modalJustClosed) return; // Если окно только что закрыли, не открываем его повторно
    $('#modal-img').attr('src', src);
    $('#modal').addClass('open'); // Добавляем класс, который покажет окно (см. CSS)
}

// Функция закрытия модального окна
function closeModal() {
    modalJustClosed = true;
    $('#modal').removeClass('open'); // Убираем класс, который показывает окно
    $('#modal-img').attr('src', '');  // Очищаем изображение
    // Блокировка повторного открытия на 300 мс (время перехода opacity)
    setTimeout(function() {
        modalJustClosed = false;
    }, 300);
}

// Обработчики событий (учитываем click, touchend и pointerup)
$(document).on('click touchend pointerup', '.clickable-image', function(e) {
    e.preventDefault();
    openModal($(this).attr('src'));
});

$(document).on('click touchend pointerup', '.close', function(e) {
    e.preventDefault();
    e.stopPropagation();
    closeModal();
});

// Закрытие окна при клике/касании вне изображения и крестика
$('#modal').on('click touchend pointerup', function(e) {
    if (!$(e.target).is('#modal-img') && !$(e.target).is('.close')) {
        closeModal();
    }
});
// ***** Конец блока модального окна *****

    // Initializing datepickers with improved performance
    $("#start_date, #end_date, #trade_open_time, #trade_close_time").datepicker({
        dateFormat: 'yy-mm-dd',
        changeMonth: true,
        changeYear: true,
        showAnim: "slideDown",
        showButtonPanel: true
    });

    // Initializing DataTables for Setup Table
    $('#setup-table').DataTable({
        responsive: true,
        language: {
            // You can replace with an English i18n file if needed
            "url": "//cdn.datatables.net/plug-ins/1.13.6/i18n/en-GB.json"
        },
        "pageLength": 10,
        "lengthChange": false,
        "ordering": true,
        "info": false,
        "autoWidth": false,
        "columnDefs": [
            { "orderable": false, "targets": [3,5] }
        ],
        "deferRender": true,
        "processing": true,
        "serverSide": false
    });

    // Initializing DataTables for Trade Table
    $('#trade-table').DataTable({
        responsive: true,
        language: {
            // You can replace with an English i18n file if needed
            "url": "//cdn.datatables.net/plug-ins/1.13.6/i18n/en-GB.json"
        },
        "pageLength": 10,
        "lengthChange": false,
        "ordering": true,
        "info": false,
        "autoWidth": false,
        "columnDefs": [
            { "orderable": false, "targets": [1,12] }
        ],
        "deferRender": true,
        "processing": true,
        "serverSide": false
    });

    // Initializing iCheck for all checkboxes
    $('input[type="checkbox"]').iCheck({
        checkboxClass: 'icheckbox_square-blue',
        increaseArea: '20%' // Increase area for convenience on mobile
    });

    // Initializing Lazysizes for images with class clickable-image
    $('img.clickable-image').each(function(){
        $(this).addClass('lazyload');
    });

    // ** Handlers for "Uncle John" Assistant **

    let chatHistory = [];
    const assistantForm = document.getElementById('assistant-form');
    const chartForm = document.getElementById('chart-analysis-form');
    const chatHistoryDiv = document.getElementById('chat-history');
    const assistantQuestionInput = document.getElementById('assistant-question');
    const chartAnalysisResult = document.getElementById('chart-analysis-result');
    const analysisChartDiv = document.getElementById('analysis-chart');
    const clearChatButton = document.getElementById('clear-chat');

    function updateChatHistoryDisplay() {
        chatHistoryDiv.innerHTML = '';
        chatHistory.forEach(message => {
            const msgDiv = document.createElement('div');
            msgDiv.className = message.role === 'user' ? 'nes-balloon from-right' : 'nes-balloon from-left is-dark';
            const content = (typeof message.content === 'object') ? JSON.stringify(message.content, null, 2) : message.content;
            msgDiv.textContent = content;
            chatHistoryDiv.appendChild(msgDiv);
        });
        chatHistoryDiv.scrollTop = chatHistoryDiv.scrollHeight;
    }

    async function loadChatHistory() {
        try {
            const response = await fetch('/get_chat_history');
            const data = await response.json();
            console.log('Chat History:', data);
            if (data.chat_history) {
                chatHistory = data.chat_history;
                updateChatHistoryDisplay();
            }
        } catch (error) {
            console.error('Error loading chat history:', error);
        }
    }

    function getCSRFToken() {
        return window.config.CSRF_TOKEN;
    }

    // Submit Handler for assistant question
    if (assistantForm) {
        assistantForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            const question = assistantQuestionInput.value.trim();
            if (!question) return;
            chatHistory.push({ role: 'user', content: question });
            updateChatHistoryDisplay();

            try {
                const response = await fetch('/assistant/chat', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ question: question })
                });
                const data = await response.json();
                console.log('Chat Response:', data);
                if (data.response) {
                    const assistantContent = (typeof data.response === 'object') 
                        ? JSON.stringify(data.response, null, 2) 
                        : data.response;
                    chatHistory.push({ role: 'assistant', content: assistantContent });
                    updateChatHistoryDisplay();
                } else if (data.error) {
                    const errorMsg = `Error: ${data.error}`;
                    chatHistory.push({ role: 'assistant', content: errorMsg });
                    updateChatHistoryDisplay();
                }
            } catch (error) {
                console.error('Error sending request:', error);
                const errorMsg = 'An error occurred while sending your request.';
                chatHistory.push({ role: 'assistant', content: errorMsg });
                updateChatHistoryDisplay();
            }
            assistantQuestionInput.value = '';
        });
    }

    // Handler for chart analysis form
    if (chartForm) {
        chartForm.addEventListener('submit', async function(e){
            e.preventDefault();
            const imageInput = document.getElementById('chart-image');
            const file = imageInput.files[0];
            if (!file) {
                alert('Please select an image.');
                return;
            }
            chartAnalysisResult.textContent = 'Analyzing...';
            analysisChartDiv.innerHTML = '';
            const formData = new FormData();
            formData.append('image', file);
            try {
                const response = await fetch('/assistant/analyze_chart', {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                console.log('Chart Analysis Response:', data);
                if (data.result && data.result.trend_prediction) {
                    chartAnalysisResult.innerHTML = `<pre>${data.result.trend_prediction}</pre>`;
                    analysisChartDiv.innerHTML = '';
                } else if (data.error) {
                    const errorMsg = `Error: ${data.error}`;
                    chartAnalysisResult.innerHTML = `<p class="nes-text is-error">${errorMsg}</p>`;
                    analysisChartDiv.innerHTML = '';
                }
            } catch (error) {
                console.error('Error analyzing chart:', error);
                chartAnalysisResult.innerHTML = '<p class="nes-text is-error">An error occurred while analyzing the chart.</p>';
                analysisChartDiv.innerHTML = '';
            }
            imageInput.value = '';
        });
    }

    // Handler for clearing the chat
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
                console.error('Error clearing chat:', error);
            }
        });
    }

    // ** New functions for unique wallets and staking **

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
            console.error("Error loading balances:", error);
            $('#ethBalance').text('Error');
            $('#wethBalance').text('Error');
            $('#ujoBalance').text('Error');
        }
    }

    loadBalances();

    // Handler for exchange form
    $('#exchangeForm').on('submit', async function(e){
        e.preventDefault();
        const amountWETH = parseFloat($('#exchangeAmount').val());
        if(isNaN(amountWETH) || amountWETH <= 0){
            alert('Please enter a valid amount of WETH to exchange.');
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
                alert('Exchange successful! You received ' + data.ujo_received.toFixed(4) + ' UJO.');
                loadBalances();
            } else{
                alert('Error: ' + data.error);
            }
        } catch(error){
            console.error("Error exchanging tokens:", error);
            alert("An error occurred during the exchange.");
        }
    });

    // Handler for confirm staking form
    $('#confirmStakeForm').on('submit', async function(e){
        e.preventDefault();
        const txHash = $('#tx_hash').val().trim();
        if(!txHash){
            alert('Please enter a transaction hash.');
            return;
        }
        if(!/^0x([A-Fa-f0-9]{64})$/.test(txHash)){
            alert('Invalid transaction hash format.');
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
                alert('Staking successfully confirmed!');
                loadStaking();
                loadBalances();
            } else{
                alert('Error: ' + data.error);
            }
        } catch(error){
            console.error("Error confirming staking:", error);
            alert("An error occurred while confirming staking.");
        }
    });

    if(document.getElementById('stakeButton')){
        document.getElementById('stakeButton').addEventListener('click', function(){
            alert('To stake, please prepare $25 in UJO tokens.');
        });
    }

    // Function to load user's stakings
    async function loadStaking() {
        try {
            const resp = await fetch('/staking/get_user_stakes');
            const data = await resp.json();
            if(data.error) {
                $('#stakingArea').html('<p>'+data.error+'</p>');
                $('#claimRewardsBtn').hide();
                $('#unstakeBtn').hide();
                return;
            }
            const stakes = data.stakes;
            if(!stakes.length) {
                $('#stakingArea').html('<p>You have no staking.</p>');
                $('#claimRewardsBtn').hide();
                $('#unstakeBtn').hide();
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
            $('#stakingArea').html(html);
            $('#claimRewardsBtn').show();
            $('#unstakeBtn').show();
        } catch (error) {
            console.error('Error loading staking data:', error);
            $('#stakingArea').html('<p>An error occurred while loading staking info.</p>');
            $('#claimRewardsBtn').hide();
            $('#unstakeBtn').hide();
        }
    }

    // Handler for "Claim Rewards" button
    $('#claimRewardsBtn').on('click', async function(){
        try {
            const csrfToken = window.config.CSRF_TOKEN;
            const response = await fetch('/staking/claim_staking_rewards',{
                method:'POST',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'Content-Type': 'application/json'
                }
            });
            const data = await response.json();
            if(data.error) alert(data.error);
            else {
                alert(data.message);
                loadStaking();
                loadBalances();
            }
        } catch (error) {
            alert('An error occurred while claiming rewards: ' + error);
        }
    });

    // Handler for "Unstake" button
    $('#unstakeBtn').on('click', async function(){
        try {
            const csrfToken = window.config.CSRF_TOKEN;
            const response = await fetch('/staking/unstake_staking',{
                method:'POST',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'Content-Type': 'application/json'
                }
            });
            const data = await response.json();
            if(data.error) alert(data.error);
            else {
                alert(data.message);
                loadStaking();
                loadBalances();
            }
        } catch (error) {
            alert('An error occurred while unstaking: ' + error);
        }
    });

    // Load staking data after the page is loaded
    document.addEventListener('DOMContentLoaded', () => {
        loadStaking();
    });
});
