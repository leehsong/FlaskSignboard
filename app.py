import os
from flask import Flask, jsonify, request, redirect, url_for, session
from config import Config
from extensions import init_extensions  # DB 풀/로거 등을 셋업하는 기존 함수


def register_error_handlers(app: Flask) -> None:
    """API 요청(/api/…)은 JSON 에러로, 그 외는 Flask 기본 에러 페이지로"""

    def _json_err(code: int, msg: str):
        return jsonify({"ok": False, "msg": msg, "code": code}), code

    @app.errorhandler(404)
    def _404(e):
        if request.path.startswith("/api/"):
            return _json_err(404, "not found")
        return e

    @app.errorhandler(405)
    def _405(e):
        if request.path.startswith("/api/"):
            return _json_err(405, "method not allowed")
        return e

    @app.errorhandler(500)
    def _500(e):
        if request.path.startswith("/api/"):
            return _json_err(500, "server error")
        return e

def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    # 1) 설정 로드
    app.config.from_object(Config)
    Config.ensure_dirs(app.config["__class__"] if "__class__" in app.config else Config)

    # 2) 확장 초기화 (DB 풀/로거/캐시 등)
    #    👉 init_extensions(app)은 내부에서 아래 키로 DB 풀을 넣어주도록 해주세요:
    #    app.config["META_POOL"], app.config["IMG_POOL"], app.config["VER_POOL"]
    init_extensions(app)

    @app.route("/")
    def root():
        if "reviewer_name" not in session:
            return redirect(url_for("core.start"))
        return redirect(url_for("core.home"))

    # 3) 블루프린트 등록
    from blueprints.core import core_bp
    from blueprints.company import company_bp
    from blueprints.sign import sign_bp
    from blueprints.illegal import illegal_bp
    from blueprints.review import review_bp
    from blueprints.upload import upload_bp
    from blueprints.mapurl import mapurl_bp

    app.register_blueprint(core_bp)                           # 화면 라우트(start/home 등)
    app.register_blueprint(company_bp, url_prefix="/api")     # /api/bunjis/..., /api/companies/...
    app.register_blueprint(sign_bp, url_prefix="/api/sign")
    app.register_blueprint(illegal_bp, url_prefix="/api/illegal")
    app.register_blueprint(review_bp, url_prefix="/api/review")
    app.register_blueprint(upload_bp, url_prefix="/upload")
    app.register_blueprint(mapurl_bp, url_prefix="/api/map")


    # 4) 에러 핸들러
    register_error_handlers(app)

    # 5) 부팅 로그 (URL Map 확인에 유용)
    with app.app_context():
        app.logger.info("URL Map:\n%s", app.url_map)

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=app.config.get("DEBUG", False))
