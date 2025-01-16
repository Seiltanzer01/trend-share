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
    "Форма не валидна. Проверьте введённые данные.": "The form is invalid. Please check the entered data.",
    "Сделка успешно обновлена.": "Trade successfully updated.",
    "Произошла ошибка при обновлении сделки.": "An error occurred while updating the trade.",
    "Изображение удалено.": "Image deleted.",
    "Ошибка при удалении изображения.": "Error deleting the image.",
    "Сделка успешно удалена.": "Trade successfully deleted.",
    "Произошла ошибка при удалении сделки.": "An error occurred while deleting the trade.",
    "У вас нет прав для редактирования этой сделки.": "You do not have permission to edit this trade.",
    "У вас нет прав для удаления этой сделки.": "You do not have permission to delete this trade.",
    "Форма не валидна. Проверьте введённые данные.": "The form is invalid. Please check the entered data.",
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

    # И так далее — добавляйте все русские фразы, которые видит пользователь
}
