# translations.py

TRANSLATIONS_RU_TO_EN = {
    # ----- forms.py -----
    # TradeForm
    "Инструмент": "Instrument",
    "Направление": "Direction",
    "Цена входа": "Entry Price",
    "Цена выхода": "Exit Price",
    "Дата открытия": "Open Date",
    "Дата закрытия": "Close Date",
    "Комментарий": "Comment",
    "Сетап": "Setup",
    "Критерии": "Criteria",
    "Скриншот": "Screenshot",
    "Удалить текущее изображение": "Remove current image",
    "Сохранить": "Save",

    # SetupForm
    "Название Сетапа": "Setup Name",
    "Описание": "Description",

    # SubmitPredictionForm
    "Ожидаемая Цена": "Expected Price",
    "Отправить Предсказание": "Send Prediction",

    # Значения в ChoiceField (не забудьте, если нужно):
    "Выберите сетап": "Select Setup",

    # ----- routes.py (Flash messages, user-facing strings) -----
    # Часто встречающиеся фразы (вы можете расширять словарь):
    "Пожалуйста, войдите в систему для участия в голосовании.": "Please log in to participate in voting.",
    "Сейчас голосование отключено.": "Voting is currently disabled.",
    "Сейчас нет активного голосования.": "There is currently no active voting.",
    "Вы уже голосовали для этого инструмента в этом опросе.": "You have already voted for this instrument in this poll.",
    "Форма не валидна. Проверьте введённые данные.": "The form is invalid. Please check the entered data.",
    "Произошла ошибка при сохранении вашего предсказания.": "An error occurred while saving your prediction.",
    "Предсказанная цена должна быть в диапазоне от": "The predicted price must be in the range of",
    "Выбранный инструмент не существует.": "The selected instrument does not exist.",
    "Не удалось получить текущую реальную цену для выбранного инструмента. Попробуйте позже.": "Could not get the current real price for the selected instrument. Please try again later.",
    "Сделка успешно добавлена.": "Trade successfully added.",
    "Ошибка при загрузке скриншота.": "Error uploading screenshot.",
    "Произошла ошибка при добавлении сделки.": "An error occurred while adding the trade.",
    "Сделка успешно обновлена.": "Trade successfully updated.",
    "Произошла ошибка при обновлении сделки.": "An error occurred while updating the trade.",
    "Изображение удалено.": "Image deleted.",
    "Ошибка при удалении изображения.": "Error deleting the image.",
    "Сделка успешно удалена.": "Trade successfully deleted.",
    "Произошла ошибка при удалении сделки.": "An error occurred while deleting the trade.",
    "У вас нет прав для редактирования этой сделки.": "You do not have permission to edit this trade.",
    "У вас нет прав для удаления этой сделки.": "You do not have permission to delete this trade.",
    "Сетап успешно добавлен.": "Setup successfully added.",
    "Произошла ошибка при добавлении сетапа.": "An error occurred while adding the setup.",
    "Сетап успешно обновлён.": "Setup successfully updated.",
    "Произошла ошибка при обновлении сетапа.": "An error occurred while updating the setup.",
    "Сетап успешно удалён.": "Setup successfully deleted.",
    "Произошла ошибка при удалении сетапа.": "An error occurred while deleting the setup.",
    "У вас нет прав для редактирования этого сетапа.": "You do not have permission to edit this setup.",
    "У вас нет прав для удаления этого сетапа.": "You do not have permission to delete this setup.",
    "У вас нет прав для просмотра этого сетапа.": "You do not have permission to view this setup.",
    "Вы не можете отправлять предсказания менее чем за 2 минуты до закрытия голосования.": "You cannot submit predictions less than 2 minutes before the voting ends.",

    # Прочие flash-сообщения из routes.py
    "Вы успешно вышли из системы.": "You have successfully logged out.",
    "Сначала войдите.": "Please log in first.",
    "Оплата успешно завершена. Спасибо за покупку!": "Payment successfully completed. Thank you for your purchase!",
    "Оплата не была завершена. Пожалуйста, попробуйте снова.": "Payment was not completed. Please try again.",
    "Ваша подписка активирована.": "Your subscription is activated.",
    "Доступ к ассистенту доступен только по подписке.": "Access to the assistant is only available by subscription.",
    "Пожалуйста, войдите в систему для доступа к ассистенту.": "Please log in to access the assistant.",
    "Сейчас нет активного голосования.": "There is currently no active voting.",

    # Переводы категорий инструментов
    "Форекс": "Forex",
    "Индексы": "Indexes",
    "Товары": "Commodities",
    "Криптовалюты": "Cryptocurrencies",

    # Переводы категорий критериев
    "Смарт-мани": "Smart Money",
    "Технический анализ": "Technical Analysis",
    "Волны Эллиота": "Elliott Waves",
    "Price Action": "Price Action",
    "Индикаторы": "Indicators",
    "Психология": "Psychology",

    # Подкатегории для Смарт-мани
    "Имбалансы и дисбалансы": "Imbalances and Disequilibria",
    "Ликвидность и зоны концентрации": "Liquidity and Concentration Zones",
    "Ордер-блоки": "Order Blocks",
    "Анализ ордер-флоу": "Order Flow Analysis",
    "Уровни структурной ликвидности": "Structural Liquidity Levels",
    "Инструменты Smart Money": "Smart Money Tools",

    # Подкатегории для Технический анализ
    "Графические модели": "Chart Patterns",
    "Динамика ценового движения": "Price Movement Dynamics",
    "Свечные паттерны": "Candle Patterns",
    "Уровни и трендовые линии": "Levels and Trend Lines",
    "Объёмно-ценовые взаимодействия": "Volume-Price Interactions",

    # Подкатегории для Волны Эллиота
    "Импульсные и коррекционные структуры": "Impulse and Corrective Structures",
    "Коррекционные модели": "Corrective Models",
    "Фибоначчи в волновой теории": "Fibonacci in Wave Theory",
    "Границы и завершение волн": "Wave Boundaries and Completion",
    "Модели и структуры волн": "Wave Models and Structures",
    "Интерпретация волновых соотношений": "Interpretation of Wave Ratios",

    # Подкатегории для Price Action
    "Ключевые свечные модели": "Key Candle Models",
    "Динамика ценового поведения": "Price Behavior Dynamics",
    "Структуры поддержки/сопротивления": "Support/Resistance Structures",
    "Брейк-аут и фальшивые пробои": "Breakouts and False Breakouts",
    "Интервальные и мультифрейм модели": "Interval and Multi-timeframe Models",
    "Комплексный Price Action анализ": "Comprehensive Price Action Analysis",

    # Подкатегории для Индикаторы
    "Осцилляторы моментума": "Momentum Oscillators",
    "Объёмные индикаторы": "Volume Indicators",
    "Индикаторы волатильности": "Volatility Indicators",
    "Скользящие средние": "Moving Averages",
    "Сигнальные системы": "Signal Systems",
    "Индикаторы настроения рынка": "Market Sentiment Indicators",

    # Подкатегории для Психология
    "Эмоциональное восприятие рынка": "Emotional Market Perception",
    "Торговая дисциплина": "Trading Discipline",
    "Психология толпы": "Crowd Psychology",
    "Когнитивные искажения": "Cognitive Biases",
    "Самоанализ и адаптация": "Self-Analysis and Adaptation",
    "Мотивация и целеполагание": "Motivation and Goal Setting",

    # Шаблоны
    "Вы уверены, что хотите удалить этот сетап?": "Are you sure you want to delete this setup?",
    "Название": "Name",
    "Действия": "Actions",
    "Текущее изображение:": "Current image:",
    "Подтверждение уровней по ордер-флоу": "Confirmation of levels by order flow",
    "Зоны высокого ордерного давления": "High Order Pressure Zones",
    "Ликвидные барьеры": "Liquidity Barriers",
    "Сквозное ликвидное покрытие": "Through Liquidity Coverage",
    "Проверка iceberg-ордеров": "Iceberg Order Verification",
    "Фигуры разворота (Голова и плечи, двойная вершина/дно)": "Reversal Patterns (Head and Shoulders, Double Top/Bottom)",
    "Формации продолжения (флаги, вымпелы, клинья)": "Continuation Formations (Flags, Pennants, Wedges)",
    "Треугольники (симметричные, восходящие, нисходящие)": "Triangles (Symmetrical, Ascending, Descending)",
    "Консолидации и боковые движения": "Consolidations and Sideways Movements",
    "Композитный анализ фигур": "Composite Pattern Analysis",
    "Разрывы уровней (gap analysis)": "Gap Analysis",
    "Анализ фейковых пробоев": "Fake Breakout Analysis",
    "Консолидация с импульсом": "Consolidation with Momentum",
    "Резкие скачки и коррекции": "Sharp Spikes and Corrections",
    "Импульсные изменения цены": "Impulse Price Changes",
    "Разворотные модели (пин-бары, доджи)": "Reversal Models (Pin Bars, Doji)",
    "Поглощения (бычьи/медвежьи)": "Engulfing Patterns (Bullish/Bearish)",
    "Многофазное поведение свечей": "Multi-phase Candle Behavior",
    "Комбинированные свечные сигналы": "Combined Candle Signals",
    "Точки разворота по свечам": "Candle Reversal Points",
    "Горизонтальные уровни поддержки/сопротивления": "Horizontal Support/Resistance Levels",
    "Динамические трендовые линии": "Dynamic Trend Lines",
    "Каналы тренда": "Trend Channels",
    "Зоны консолидации": "Consolidation Zones",
    "Многоступенчатая структура уровней": "Multi-level Structure of Levels",
    "Профиль объёма в зоне входа": "Volume Profile in Entry Zone",
    "Согласование объёма и цены": "Volume and Price Alignment",
    "Объёмные аномалии при пробое": "Volume Anomalies on Breakout",
    "Кластеризация объёмных скачков": "Volume Spike Clustering",
    "Объёмное подтверждение тренда": "Volume Confirmation of Trend",
    "Импульсные волны (1, 3, 5)": "Impulse Waves (1, 3, 5)",
    "Коррекционные волны (2, 4)": "Corrective Waves (2, 4)",
    "Фрактальность волн": "Wave Fractality",
    "Начало и конец волны": "Wave Start and End",
    "Временные интервалы волн": "Wave Timeframes",
    "Модель \"Зигзаг\"": "Zigzag Model",
    "Площадки для разворота": "Reversal Zones",
    "Треугольное сжатие": "Triangular Compression",
    "Коррекционные параллелограммы": "Corrective Parallelograms",
    "Смешанные коррекции": "Mixed Corrections",
    "Фибоначчи-откаты для входа": "Fibonacci Retracements for Entry",
    "Соотношения волн по Фибоначчи": "Fibonacci Wave Ratios",
    "Расширения и ретрейсы": "Extensions and Retraces",
    "Фибоначчи уровни для SL/TP": "Fibonacci Levels for SL/TP",
    "Согласование с Фибоначчи": "Fibonacci Alignment",
    "Точки разворота волны": "Wave Reversal Points",
    "Соотношение длин волн": "Wave Length Ratios",
    "Зоны ослабления импульса": "Impulse Weakening Zones",
    "Временные параметры волн": "Wave Time Parameters",
    "Завершение импульса": "Completion of Impulse",
    "Классическая модель Эллиота": "Classic Elliott Wave Model",
    "Подмодели импульсных волн": "Submodels of Impulse Waves",
    "Многофрактальные модели": "Multifractal Models",
    "Анализ на разных таймфреймах": "Multi-timeframe Analysis",
    "Синхронизация с основным трендом": "Synchronization with Main Trend",
    "Пропорции волн": "Wave Proportions",
    "Сравнение длительности и амплитуды": "Comparison of Duration and Amplitude",
    "Корреляция с объёмом": "Volume Correlation",
    "Сравнение импульсных и коррекционных волн": "Comparison of Impulse and Corrective Waves",
    "Прогноз на основе волновой структуры": "Forecast Based on Wave Structure",
    "Пин-бары как сигнал разворота": "Pin Bars as Reversal Signals",
    "Свечные поглощения": "Candle Engulfings",
    "Доджи для ожидания разворота": "Doji for Anticipating Reversal",
    "Модель \"Харами\"": "Harami Model",
    "Свечи с длинными тенями": "Candles with Long Shadows",
    "Формирование локальных экстремумов": "Formation of Local Extremes",
    "Консолидация с мощным прорывом": "Consolidation with Strong Breakout",
    "Отказы от ключевых уровней": "Rejections of Key Levels",
    "Фиксация откатов": "Retracement Fixation",
    "Дивергенция цены и объёма": "Price and Volume Divergence",
    "Устойчивые уровни поддержки/сопротивления": "Stable Support/Resistance Levels",
    "Реверсия цены от ключевых зон": "Price Reversion from Key Zones",
    "Фиксированные и динамические барьеры": "Fixed and Dynamic Barriers",
    "Реакция на исторические уровни": "Reaction to Historical Levels",
    "Пробой с откатом": "Breakout with Retracement",
    "Истинные пробои уровней": "True Level Breakouts",
    "Фильтрация ложных пробоев": "False Breakout Filtering",
    "Закрытие свечи у пробитого уровня": "Candle Close at Broken Level",
    "Контакт с уровнем перед пробоем": "Contact with Level Before Breakout",
    "Откаты после пробоя": "Retracements After Breakout",
    "Согласование уровней и свечей": "Alignment of Levels and Candles",
    "Интеграция ценовых аномалий и объёма": "Integration of Price Anomalies and Volume",
    "Контекстный рыночный анализ": "Contextual Market Analysis",
    "Мультифрейм проверка сигнала": "Multi-timeframe Signal Verification",
    "Интеграция сигналов для оптимального входа": "Signal Integration for Optimal Entry",
    "RSI для перекупленности/перепроданности": "RSI for Overbought/Oversold",
    "Stochastic для разворотов": "Stochastic for Reversals",
    "CCI для измерения импульса": "CCI for Momentum Measurement",
    "Williams %R для экстремумов": "Williams %R for Extremes",
    "ROC для динамики цены": "ROC for Price Dynamics",
    "OBV для подтверждения тренда": "OBV for Trend Confirmation",
    "Accumulation/Distribution для оценки покупки/продажи": "Accumulation/Distribution for Buy/Sell Assessment",
    "MFI для денежного потока": "MFI for Money Flow",
    "Volume Oscillator для объёмных аномалий": "Volume Oscillator for Volume Anomalies",
    "CMF для давления покупателей/продавцов": "CMF for Buyer/Seller Pressure",
    "Bollinger Bands для зон перекупленности/перепроданности": "Bollinger Bands for Overbought/Oversold Zones",
    "ATR для стоп-лоссов": "ATR for Stop-Losses",
    "Keltner Channels для трендовых зон": "Keltner Channels for Trend Zones",
    "Donchian Channels для экстремумов": "Donchian Channels for Extremes",
    "Standard Deviation для изменчивости": "Standard Deviation for Volatility",
    "SMA для базового тренда": "SMA for Base Trend",
    "EMA для оперативного отслеживания": "EMA for Responsive Tracking",
    "WMA для точного расчёта": "WMA for Precise Calculation",
    "HMA для сглаживания шума": "HMA for Noise Smoothing",
    "TEMA для быстрого входа": "TEMA for Quick Entry",
    "MACD для смены тренда": "MACD for Trend Changes",
    "Пересечение скользящих для входа": "Moving Averages Crossover for Entry",
    "Дивергенция осцилляторов": "Oscillator Divergence",
    "Осцилляторы разворота в комбинации": "Reversal Oscillators in Combination",
    "Автоматические сигналы": "Automatic Signals",
    "VIX для неопределённости": "VIX for Uncertainty",
    "Индекс оптимизма": "Optimism Index",
    "Рыночный консенсус": "Market Consensus",
    "Сентиментальные линии": "Sentiment Lines",
    "Индикаторы общественного настроения": "Public Sentiment Indicators",
    "Анализ страха как сигнала": "Fear Analysis as Signal",
    "Оценка жадности и разворота": "Greed and Reversal Assessment",
    "Паника как возможность": "Panic as Opportunity",
    "Эйфория и коррективы": "Euphoria and Corrections",
    "Нерешительность и риск": "Indecision and Risk",
    "Строгое следование плану": "Strict Plan Adherence",
    "Контроль риска и мани-менеджмент": "Risk Control and Money Management",
    "Ведение торгового журнала": "Keeping a Trading Journal",
    "Самодисциплина": "Self-Discipline",
    "Стратегия управления позицией": "Position Management Strategy",
    "Анализ FOMO": "FOMO Analysis",
    "Отслеживание массовых эмоций": "Tracking Mass Emotions",
    "Эффект стадного мышления": "Herding Effect",
    "Реакция рынка на новости": "Market Reaction to News",
    "Контртренд под давлением толпы": "Countertrend Under Crowd Pressure",
    "Осознание подтверждения ожиданий": "Awareness of Expectation Confirmation",
    "Анализ переоценки возможностей": "Overvaluation Opportunity Analysis",
    "Контроль самоуверенности": "Overconfidence Control",
    "Избежание ошибки выжившего": "Avoiding Survivor Bias",
    "Внимание к упущенным рискам": "Attention to Missed Risks",
    "Пересмотр входов для выявления ошибок": "Reviewing Entries to Identify Mistakes",
    "Анализ успешных и неудачных сделок": "Analyzing Successful and Unsuccessful Trades",
    "Корректировка стратегии": "Strategy Adjustment",
    "Оценка эмоционального состояния": "Emotional State Assessment",
    "Постоянное обучение": "Continuous Learning",
    "Ясные краткосрочные цели": "Clear Short-term Goals",
    "Фокус на долгосрочной стратегии": "Focus on Long-term Strategy",
    "Визуализация успеха": "Visualization of Success",
    "Позитивный настрой": "Positive Attitude",
    "Поиск возможностей для роста": "Seeking Growth Opportunities",
    "Вы уверены, что хотите удалить эту сделку?": "Are you sure you want to delete this transaction?",
    "Критерии:": "Criteria:",
}
