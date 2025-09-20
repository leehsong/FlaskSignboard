from flask import Flask
from config import Config
from extensions import init_extensions
from blueprints.core import core_bp
from blueprints.company import company_bp
from blueprints.sign import sign_bp
from blueprints.illegal import illegal_bp
from blueprints.review import review_bp
from blueprints.upload import upload_bp
from blueprints.mapurl import mapurl_bp

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    init_extensions(app)

    # 블루프린트 등록
    app.register_blueprint(core_bp)
    app.register_blueprint(company_bp)
    app.register_blueprint(sign_bp)
    app.register_blueprint(illegal_bp)
    app.register_blueprint(review_bp)
    app.register_blueprint(upload_bp)
    app.register_blueprint(mapurl_bp)

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=26000, debug=True)
