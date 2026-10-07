"""
Configuration classes for Portable Sandbox Management System.
Supports development, testing, and production environments with portable relative paths.
"""

import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    """Base configuration with secure defaults."""
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-portable-sandbox-secret-key-change-in-production")
    DATABASE_PATH = str(BASE_DIR / "data" / "sandbox.db")
    SANDBOXES_ROOT = str(BASE_DIR / "sandboxes")
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False  # Set to True for HTTPS production
    JSON_SORT_KEYS = False


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True


class TestingConfig(Config):
    """Testing configuration with isolated test database."""
    TESTING = True
    DEBUG = True
    SECRET_KEY = "test-secret-key-for-automated-tests"
    SESSION_COOKIE_SECURE = False
