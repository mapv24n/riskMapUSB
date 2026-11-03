"""Creación y configuración del portal riskMapUSB."""

import os
import secrets
from flask import Flask, session
from .constants import ETIQUETAS_ROL


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

    from .routes.auth import bp as auth_bp
    from .routes.main import bp as main_bp
    from .routes.admin import bp as admin_bp
    from .routes.docente import bp as docente_bp
    from .cli import crear_admin

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(docente_bp)
    app.cli.add_command(crear_admin)

    @app.context_processor
    def contexto_plantillas():
        return {"usuario": session.get("usuario"), "roles": ETIQUETAS_ROL}

    return app
