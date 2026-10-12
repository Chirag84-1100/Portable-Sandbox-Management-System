"""
Flask Application Factory for Portable Sandbox Management System.
Demonstrates clean modular architecture, blueprint registration, and standardized error handling.
"""

from typing import Optional, Type
from flask import Flask, jsonify

from app.config import Config, DevelopmentConfig


def create_app(config_class: Optional[Type[Config]] = None) -> Flask:
    """
    Initializes and configures the Flask application.
    Supports dependency injection of custom configuration classes for testing.
    """
    app = Flask(__name__)

    if config_class is None:
        config_class = DevelopmentConfig

    app.config.from_object(config_class)

    # Register blueprints
    from app.api import api_bp
    app.register_blueprint(api_bp)

    from app.web import web_bp
    app.register_blueprint(web_bp)

    # Global JSON error handlers
    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({
            "success": False,
            "error": {
                "code": "BAD_REQUEST",
                "message": getattr(error, "description", "Bad Request")
            }
        }), 400

    @app.errorhandler(401)
    def unauthorized(error):
        return jsonify({
            "success": False,
            "error": {
                "code": "UNAUTHORIZED",
                "message": getattr(error, "description", "Authentication required")
            }
        }), 401

    @app.errorhandler(403)
    def forbidden(error):
        return jsonify({
            "success": False,
            "error": {
                "code": "FORBIDDEN",
                "message": getattr(error, "description", "Access denied")
            }
        }), 403

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({
            "success": False,
            "error": {
                "code": "NOT_FOUND",
                "message": getattr(error, "description", "Requested resource not found")
            }
        }), 404

    @app.errorhandler(405)
    def method_not_allowed(error):
        return jsonify({
            "success": False,
            "error": {
                "code": "METHOD_NOT_ALLOWED",
                "message": "HTTP method not allowed for this endpoint"
            }
        }), 405

    @app.errorhandler(500)
    def internal_server_error(error):
        return jsonify({
            "success": False,
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected internal server error occurred"
            }
        }), 500

    return app
