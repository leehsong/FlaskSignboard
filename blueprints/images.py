# blueprints/images.py
import os, base64
from datetime import datetime
from flask import Blueprint, current_app, request, render_template, jsonify, send_from_directory
from PIL import Image
import io as _io

# Flask Blueprint
images_bp = Blueprint("images", __name__, url_prefix="/images")

# 업로드 디렉토리 설정
def upload_folder():
    root = os.path.join(os.path.dirname(__file__), "..", "uploads")
    os.makedirs(root, exist_ok=True)
    return os.path.abspath(root)

# MariaDB 연결 (app.py에서 import해서 주입할 예정)
mysql_pool = None
def get_maria():
    if mysql_pool is None:
        raise RuntimeError("mysql_pool not set in images.py")
    return mysql_pool.get_connection()

def is_aspect_4_3(w, h, tol=0.02):
    return abs((w/h) - (4/3)) <= tol

def save_pil(img: Image.Image, subdir: str, stem: str):
    d = os.path.join(upload_folder(), subdir)
    os.makedirs(d, exist_ok=True)
    fname = f"{stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    fpath = os.path.join(d, fname)
    img.convert("RGB").save(fpath, quality=90)
    rel = os.path.relpath(fpath, upload_folder()).replace("\\","/")
    return rel, fpath

# ----------- 라우트들 예시 -----------
@images_bp.route("")
def page_images():
    conn = get_maria(); cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, sigungu, eupmyeondong, bunji, road_addr FROM sb_address LIMIT 50")
    addrs = cur.fetchall()
    cur.execute("SELECT id, filename FROM sb_image ORDER BY updated_at DESC LIMIT 50")
    imgs = cur.fetchall()
    cur.close(); conn.close()
    return render_template("images.html", addrs=addrs, imgs=imgs)

@images_bp.route("/upload", methods=["POST"])
def images_upload():
    if "file" not in request.files:
        return jsonify(ok=False, error="No file"), 400
    f = request.files["file"]
    img = Image.open(f.stream)
    rel, _ = save_pil(img, "originals", "img")
    return jsonify(ok=True, relpath=rel)

@images_bp.route("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(upload_folder(), filename)


# blueprints/images.py
mysql_pool = None

def set_mysql_pool(pool):
    global mysql_pool
    mysql_pool = pool