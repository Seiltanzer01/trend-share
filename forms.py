# forms.py

from flask_wtf import FlaskForm
from wtforms import (
    StringField, SubmitField, SelectField, FloatField, 
    TextAreaField, DateField, FileField, SelectMultipleField, BooleanField
)
from wtforms.validators import DataRequired, Optional, NumberRange
from flask_wtf.file import FileAllowed

# Импортируем функцию translate_python из вашего app.py
from app import translate_python


class TradeForm(FlaskForm):
    # Изначально указываем «сырые» значения, не привязанные к переводу:
    instrument      = SelectField('instrument', coerce=int, validators=[DataRequired()])
    direction       = SelectField('direction', choices=[('Buy', 'Buy'), ('Sell', 'Sell')], validators=[DataRequired()])
    entry_price     = FloatField('entry_price', validators=[DataRequired()])
    exit_price      = FloatField('exit_price', validators=[Optional()])
    trade_open_time = DateField('trade_open_time', format='%Y-%m-%d', validators=[DataRequired()])
    trade_close_time= DateField('trade_close_time', format='%Y-%m-%d', validators=[Optional()])
    comment         = TextAreaField('comment', validators=[Optional()])
    setup_id        = SelectField('setup_id', coerce=int, validators=[Optional()])
    criteria        = SelectMultipleField('criteria', coerce=int, validators=[Optional()])
    screenshot      = FileField(
        'screenshot', 
        validators=[
            Optional(),
            FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'images only')
        ]
    )
    remove_image    = BooleanField('remove_image')
    submit          = SubmitField('submit')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Теперь можем «перевести» лейблы внутри request context
        self.instrument.label        = translate_python('Инструмент')
        self.direction.label         = translate_python('Направление')
        self.entry_price.label       = translate_python('Цена входа')
        self.exit_price.label        = translate_python('Цена выхода')
        self.trade_open_time.label   = translate_python('Дата открытия')
        self.trade_close_time.label  = translate_python('Дата закрытия')
        self.comment.label           = translate_python('Комментарий')
        self.setup_id.label          = translate_python('Сетап')
        self.criteria.label          = translate_python('Критерии')
        self.screenshot.label        = translate_python('Скриншот')
        self.remove_image.label      = translate_python('Удалить текущее изображение')
        self.submit.label            = translate_python('Сохранить')

        # Обновим валидаторы для поля screenshot, заменяя текст на перевод
        self.screenshot.validators = [
            Optional(),
            FileAllowed(['jpg', 'jpeg', 'png', 'gif'], translate_python('Только изображения!'))
        ]


class SetupForm(FlaskForm):
    setup_name  = StringField('setup_name', validators=[DataRequired()])
    description = TextAreaField('description', validators=[Optional()])
    criteria    = SelectMultipleField('criteria', coerce=int, validators=[Optional()])
    screenshot  = FileField(
        'screenshot',
        validators=[
            Optional(),
            FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'images only')
        ]
    )
    remove_image = BooleanField('remove_image')
    submit       = SubmitField('submit')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.setup_name.label       = translate_python('Название Сетапа')
        self.description.label      = translate_python('Описание')
        self.criteria.label         = translate_python('Критерии')
        self.screenshot.label       = translate_python('Скриншот')
        self.remove_image.label     = translate_python('Удалить текущее изображение')
        self.submit.label           = translate_python('Сохранить')

        # Аналогично меняем тексты валидаторов на переведённые
        self.screenshot.validators = [
            Optional(),
            FileAllowed(['jpg', 'jpeg', 'png', 'gif'], translate_python('Только изображения!'))
        ]


class SubmitPredictionForm(FlaskForm):
    instrument      = SelectField('instrument', coerce=int, validators=[DataRequired()])
    predicted_price = FloatField('predicted_price', validators=[DataRequired(), NumberRange(min=0)])
    submit          = SubmitField('submit')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.instrument.label      = translate_python('Инструмент')
        self.predicted_price.label = translate_python('Ожидаемая Цена')
        self.submit.label          = translate_python('Отправить Предсказание')
