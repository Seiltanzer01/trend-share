# extensions.py
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect  # Импортируем CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()  # Создаём экземпляр CSRFProtect
