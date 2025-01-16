# forms.py

from flask_wtf import FlaskForm
from wtforms import (
    StringField, SubmitField, SelectField, FloatField, 
    TextAreaField, DateField, FileField, SelectMultipleField, BooleanField
)
from wtforms.validators import DataRequired, Optional, NumberRange
from flask_wtf.file import FileAllowed

# Не вызываем translate_python на уровне импорта полей!
# Импортируем саму функцию (допустим, она у нас в app.py):
from app import translate_python


class TradeForm(FlaskForm):
    # Указываем «сырые» значения, чтобы не обращаться к session во время импорта
    instrument     = SelectField('instrument', coerce=int, validators=[DataRequired()])
    direction      = SelectField('direction',  choices=[('Buy', 'Buy'), ('Sell', 'Sell')], validators=[DataRequired()])
    entry_price    = FloatField('entry_price', validators=[DataRequired()])
    exit_price     = FloatField('exit_price',  validators=[Optional()])
    trade_open_time  = DateField('trade_open_time',  format='%Y-%m-%d', validators=[DataRequired()])
    trade_close_time = DateField('trade_close_time', format='%Y-%m-%d', validators=[Optional()])
    comment        = TextAreaField('comment', validators=[Optional()])
    setup_id       = SelectField('setup_id', coerce=int, validators=[Optional()])
    criteria       = SelectMultipleField('criteria', coerce=int, validators=[Optional()])
    screenshot     = FileField(
        'screenshot', 
        validators=[
            Optional(), 
            FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'images only')
        ]
    )
    remove_image   = BooleanField('remove_image')
    submit         = SubmitField('submit')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Здесь уже доступен request context, значит session и translate_python тоже доступны:
        self.instrument.label        = translate_python('Инструмент')
        self.direction.label         = translate_python('Направление')
        # Здесь не забываем, что choices=('Buy','Buy') — это не переводы, а значение поля (можно оставить как есть)
        self.entry_price.label       = translate_python('Цена входа')
        self.exit_price.label        = translate_python('Цена выхода')
        self.trade_open_time.label   = translate_python('Дата открытия')
        self.trade_close_time.label  = translate_python('Дата закрытия')
        self.comment.label           = translate_python('Комментарий')
        self.setup_id.label          = translate_python('Сетап')
        self.criteria.label          = translate_python('Критерии')
        self.screenshot.label        = translate_python('Скриншот')
        # Текст в FileAllowed меняем тоже через translate, если надо:
        self.screenshot.kwargs['validators'] = [
            Optional(),
            FileAllowed(['jpg','jpeg','png','gif'], translate_python('Только изображения!'))
        ]
        self.remove_image.label      = translate_python('Удалить текущее изображение')
        self.submit.label            = translate_python('Сохранить')


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

        self.setup_name.label  = translate_python('Название Сетапа')
        self.description.label = translate_python('Описание')
        self.criteria.label    = translate_python('Критерии')
        self.screenshot.label  = translate_python('Скриншот')
        self.screenshot.kwargs['validators'] = [
            Optional(),
            FileAllowed(['jpg','jpeg','png','gif'], translate_python('Только изображения!'))
        ]
        self.remove_image.label = translate_python('Удалить текущее изображение')
        self.submit.label       = translate_python('Сохранить')


class SubmitPredictionForm(FlaskForm):
    instrument      = SelectField('instrument', coerce=int, validators=[DataRequired()])
    predicted_price = FloatField('predicted_price', validators=[DataRequired(), NumberRange(min=0)])
    submit          = SubmitField('submit')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.instrument.label      = translate_python('Инструмент')
        self.predicted_price.label = translate_python('Ожидаемая Цена')
        self.submit.label          = translate_python('Отправить Предсказание')
