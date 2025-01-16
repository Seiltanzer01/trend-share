# forms.py

from flask_wtf import FlaskForm
from wtforms import (
    StringField, SubmitField, SelectField, FloatField, TextAreaField, 
    DateField, FileField, SelectMultipleField, BooleanField
)
from wtforms.validators import DataRequired, Optional, NumberRange
from flask_wtf.file import FileAllowed

# Импортируем функцию для перевода (предположим, что она есть в app.py)
from app import translate_python

class TradeForm(FlaskForm):
    instrument = SelectField(
        translate_python('Инструмент'), 
        coerce=int, 
        validators=[DataRequired()]
    )
    direction = SelectField(
        translate_python('Направление'), 
        choices=[('Buy', 'Buy'), ('Sell', 'Sell')], 
        validators=[DataRequired()]
    )
    entry_price = FloatField(
        translate_python('Цена входа'), 
        validators=[DataRequired()]
    )
    exit_price = FloatField(
        translate_python('Цена выхода'), 
        validators=[Optional()]
    )
    trade_open_time = DateField(
        translate_python('Дата открытия'), 
        format='%Y-%m-%d', 
        validators=[DataRequired()]
    )
    trade_close_time = DateField(
        translate_python('Дата закрытия'), 
        format='%Y-%m-%d', 
        validators=[Optional()]
    )
    comment = TextAreaField(
        translate_python('Комментарий'), 
        validators=[Optional()]
    )
    setup_id = SelectField(
        translate_python('Сетап'), 
        coerce=int, 
        validators=[Optional()]
    )
    criteria = SelectMultipleField(
        translate_python('Критерии'), 
        coerce=int, 
        validators=[Optional()]
    )
    screenshot = FileField(
        translate_python('Скриншот'),
        validators=[
            Optional(), 
            FileAllowed(['jpg', 'jpeg', 'png', 'gif'], translate_python('Только изображения!'))
        ]
    )
    remove_image = BooleanField(
        translate_python('Удалить текущее изображение')  # Новое поле
    )
    submit = SubmitField(translate_python('Сохранить'))


class SetupForm(FlaskForm):
    setup_name = StringField(
        translate_python('Название Сетапа'), 
        validators=[DataRequired()]
    )
    description = TextAreaField(
        translate_python('Описание'), 
        validators=[Optional()]
    )
    criteria = SelectMultipleField(
        translate_python('Критерии'), 
        coerce=int, 
        validators=[Optional()]
    )
    screenshot = FileField(
        translate_python('Скриншот'),
        validators=[
            Optional(), 
            FileAllowed(['jpg', 'jpeg', 'png', 'gif'], translate_python('Только изображения!'))
        ]
    )
    remove_image = BooleanField(
        translate_python('Удалить текущее изображение')  # Новое поле
    )
    submit = SubmitField(translate_python('Сохранить'))


class SubmitPredictionForm(FlaskForm):
    instrument = SelectField(
        translate_python('Инструмент'), 
        coerce=int, 
        validators=[DataRequired()]
    )
    predicted_price = FloatField(
        translate_python('Ожидаемая Цена'), 
        validators=[DataRequired(), NumberRange(min=0)]
    )
    submit = SubmitField(translate_python('Отправить Предсказание'))
