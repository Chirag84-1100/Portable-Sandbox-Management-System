"""
Development Server Runner for Portable Sandbox Management System.
Runs the Flask application with portable configuration.
"""

import os
from app import create_app
from app.config import DevelopmentConfig

app = create_app(DevelopmentConfig)

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "True").lower() in ("true", "1")
    print(f"Starting Portable Sandbox Management System on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)
