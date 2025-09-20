import os
import pathlib


class Config:
    """환경 변수로 대부분 덮어쓸 수 있도록 구성한 기본 설정"""

    # --- Flask 기본 ---
    SECRET_KEY = os.getenv("FLASK_SECRET", "dev-secret")
    JSON_AS_ASCII = False
    TEMPLATES_AUTO_RELOAD = True
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"

    # --- 외부 설정 ---
    DB_INI = os.getenv("DB_INI", "db_config.ini")
    KAKAO_KEY = os.getenv("KAKAO_KEY", "YOUR_KAKAO_KEY")

    # --- 경로 ---
    ROOT_DIR = pathlib.Path(__file__).resolve().parent
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", str(ROOT_DIR / "uploads"))
    DATA_DIR = pathlib.Path(os.getenv("DATA_DIR", str(ROOT_DIR / "uploads_data")))

    # --- 이미지 리사이즈 한계 ---
    MAX_IMAGE_W = int(os.getenv("MAX_IMAGE_W", "800"))
    MAX_IMAGE_H = int(os.getenv("MAX_IMAGE_H", "600"))

    # --- DB 스키마(테이블/컬럼 상수) ---
    META_TABLE = os.getenv("META_TABLE", "public.t_b_cpn")
    SIGN_TABLE = os.getenv("SIGN_TABLE", "public.t_sb_info")

    COL_ID = os.getenv("COL_ID", "i_cpn")            # 회사 PK
    COL_COMP = os.getenv("COL_COMP", "t_cpn")        # 회사명
    COL_COMP_FALLBACK = os.getenv("COL_COMP_FALLBACK", "i_cpn")
    COL_DONG = os.getenv("COL_DONG", "t_add_3")
    COL_BUNJI = os.getenv("COL_BUNJI", "t_add_num")
    COL_BUNJI2 = os.getenv("COL_BUNJI2", "t_add_2")

    COL_ADIDX = os.getenv("COL_ADIDX", "i_info")     # 간판 PK
    COL_CP_IDX = os.getenv("COL_CP_IDX", "i_cpn")    # FK → 회사 PK
    COL_SBF = os.getenv("COL_SBF", "i_sc_sbf")
    COL_SBD = os.getenv("COL_SBD", "i_sc_sbd")
    COL_SBC = os.getenv("COL_SBC", "i_sc_sbc")

    SBF_ALLOWED = set(os.getenv(
        "SBF_ALLOWED",
        "SBF01,SBF02,SBF03,SBF04,SBF05,SBF06"
    ).split(","))

    @staticmethod
    def ensure_dirs(conf: "Config") -> None:
        """필요 디렉토리 생성"""
        pathlib.Path(conf.UPLOAD_FOLDER).mkdir(parents=True, exist_ok=True)
        conf.DATA_DIR.mkdir(parents=True, exist_ok=True)
