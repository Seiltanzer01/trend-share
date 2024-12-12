
# extensions.py
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()  # Инициализация CSRFProtect без приложения
