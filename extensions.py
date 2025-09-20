import logging, sys, os
import mysql.connector.pooling, psycopg2.pool
import configparser
from config import Config

logger = logging.getLogger("signboard")
if not logger.handlers:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    logger.addHandler(h)

def init_extensions(app):
    level = logging.DEBUG if os.getenv("LOG_LEVEL","").upper()=="DEBUG" else logging.INFO
    logger.setLevel(level)

    ini = Config.DB_INI

    app.config["META_POOL"] = make_pool("meta_db", ini)
    app.config["IMG_POOL"]  = make_pool("image_db", ini)
    app.config["VER_POOL"]  = make_pool("verify_db", ini)


# DB 풀 생성 함수
def make_pool(section, ini_file):
    cfg = configparser.ConfigParser(inline_comment_prefixes=(';', '#'))
    cfg.read(ini_file, encoding="utf-8")
    p = cfg[section]; drv = p.get("driver","postgres").lower()
    if drv == "postgres":
        return psycopg2.pool.SimpleConnectionPool(
            1, int(p.get("pool_max",10)),
            host=p["host"], port=p["port"], dbname=p["dbname"],
            user=p["user"], password=p["password"])
    else:
        return mysql.connector.pooling.MySQLConnectionPool(
            pool_name=f"{section}_pool", pool_size=int(p.get("pool_max",10)),
            host=p["host"], port=int(p["port"]), database=p["dbname"],
            user=p["user"], password=p["password"], autocommit=True)
