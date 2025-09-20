import os, pathlib

class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET", "dev-secret")
    DB_INI     = os.getenv("DB_INI", "db_config.ini")
    KAKAO_KEY  = os.getenv("KAKAO_KEY", "YOUR_KAKAO_KEY")
    UPLOAD_FOLDER = "./uploads"
    DATA_DIR   = pathlib.Path("./uploads_data")
