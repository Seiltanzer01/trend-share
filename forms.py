# forms.py

from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, SelectField, FloatField, TextAreaField, DateField, FileField, SelectMultipleField, BooleanField
from wtforms.validators import DataRequired, Optional, NumberRange
from flask_wtf.file import FileAllowed

class TradeForm(FlaskForm):
    instrument = SelectField('Инструмент', coerce=int, validators=[DataRequired()])
    direction = SelectField('Направление', choices=[('Buy', 'Buy'), ('Sell', 'Sell')], validators=[DataRequired()])
    entry_price = FloatField('Цена входа', validators=[DataRequired()])
    exit_price = FloatField('Цена выхода', validators=[Optional()])
    trade_open_time = DateField('Дата открытия', format='%Y-%m-%d', validators=[DataRequired()])
    trade_close_time = DateField('Дата закрытия', format='%Y-%m-%d', validators=[Optional()])
    comment = TextAreaField('Комментарий', validators=[Optional()])
    setup_id = SelectField('Сетап', coerce=int, validators=[Optional()])
    criteria = SelectMultipleField('Критерии', coerce=int, validators=[Optional()])
    screenshot = FileField('Скриншот', validators=[Optional(), FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Только изображения!')])
    remove_image = BooleanField('Удалить текущее изображение')  # Новое поле
    submit = SubmitField('Сохранить')

class SetupForm(FlaskForm):
    setup_name = StringField('Название Сетапа', validators=[DataRequired()])
    description = TextAreaField('Описание', validators=[Optional()])
    criteria = SelectMultipleField('Критерии', coerce=int, validators=[Optional()])
    screenshot = FileField('Скриншот', validators=[Optional(), FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Только изображения!')])
    remove_image = BooleanField('Удалить текущее изображение')  # Новое поле
    submit = SubmitField('Сохранить')

# Новая форма для отправки предсказаний
class SubmitPredictionForm(FlaskForm):
    instrument = SelectField('Инструмент', coerce=int, validators=[DataRequired()])
    predicted_price = FloatField('Ожидаемая Цена', validators=[DataRequired(), NumberRange(min=0)])
    submit = SubmitField('Отправить Предсказание')
