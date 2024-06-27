import os
import logging  # Ensure logging is imported
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY')
    FOOTBALL_DATA_API_KEY = os.getenv('FOOTBALL_DATA_API_KEY')
    DEBUG = False
    TESTING = False
    WTF_CSRF_ENABLED = False  # Disable CSRF protection
    LOG_LEVEL = logging.INFO  # Default log level


class ProductionConfig(Config):
    DEBUG = False
    LOG_LEVEL = logging.WARNING


class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = True
    LOG_LEVEL = logging.DEBUG  # Development log level


class TestingConfig(Config):
    DEBUG = True
    TESTING = True
    LOG_LEVEL = logging.DEBUG  # Testing log level
