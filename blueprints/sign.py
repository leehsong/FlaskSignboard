from flask import Blueprint, request, jsonify, send_file
from utils.db import db_select_all, db_execute
from extensions import logger
from PIL import Image
import io, os, datetime, base64

sign_bp = Blueprint("sign", __name__, url_prefix="/api/sign")

# === 기본 설정 ===
SIGN_TABLE = "public.t_sb_info"
HISTORY_TABLE = "public.t_sb_img_history"
COL_ADIDX, COL_CP_IDX = "i_info", "i_cpn"

IMG_FOLDER = "./static/sign_images"
os.makedirs(os.path.join(IMG_FOLDER, "history"), exist_ok=True)
os.makedirs(os.path.join(IMG_FOLDER, "candidates"), exist_ok=True)


# === 도우미 함수 ===
def crop_to_4_3(img: Image.Image) -> Image.Image:
    """이미지를 중앙 기준으로 4:3 비율로 크롭"""
    w, h = img.size
    target_ratio = 4/3
    current_ratio = w/h
    if current_ratio > target_ratio:  # 가로가 더 긴 경우 → 좌우 크롭
        new_w = int(h * target_ratio); offset = (w - new_w) // 2
        return img.crop((offset, 0, offset + new_w, h))
    else:  # 세로가 더 긴 경우 → 위아래 크롭
        new_h = int(w / target_ratio); offset = (h - new_h) // 2
        return img.crop((0, offset, w, offset + new_h))


# === 이미지 업로드 & 교체 ===
@sign_bp.route("/upload_image", methods=["POST"])
def upload_image():
    """
    업로드된 이미지를 4:3 크롭 → 원본DB 업데이트
    이전 이미지는 History 테이블에 저장
    payload:
      - i_info: 간판 PK
      - file: multipart/form-data 업로드 or
      - image_base64: clipboard 붙여넣기
    """
    i_info = (request.form.get("i_info") or (request.json.get("i_info") if request.json else "")).strip()
    if not i_info:
        return jsonify({"ok": False, "msg": "i_info required"}), 400

    # 이미지 데이터 가져오기
    file = request.files.get("file")
    img_data = None
    if file:
        img_data = file.read()
    elif request.json and "image_base64" in request.json:
        img_data = base64.b64decode(request.json["image_base64"])
    else:
        return jsonify({"ok": False, "msg": "No image provided"}), 400

    try:
        img = Image.open(io.BytesIO(img_data)).convert("RGB")
        cropped = crop_to_4_3(img)

        # 1) 기존 이미지 → History에 저장
        now = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        hist_name = f"{i_info}_{now}.jpg"
        hist_path = os.path.join(IMG_FOLDER, "history", hist_name)
        cropped.save(hist_path, "JPEG", quality=90)

        db_execute(
            f"INSERT INTO {HISTORY_TABLE}(i_info, filename, created_at) VALUES (%s,%s,NOW())",
            (i_info, hist_name)
        )

        # 2) 신규 이미지 → 원본 DB 업데이트
        buf = io.BytesIO()
        cropped.save(buf, "JPEG", quality=90)
        db_execute(
            f"UPDATE {SIGN_TABLE} SET b_img=%s, q_img_w=%s, q_img_h=%s WHERE i_info=%s",
            (buf.getvalue(), cropped.size[0], cropped.size[1], i_info)
        )

        return jsonify({"ok": True, "i_info": i_info, "filename": hist_name})
    except Exception as e:
        logger.error(f"[upload_image] {e}")
        return jsonify({"ok": False, "msg": str(e)}), 500


# === 이미지 히스토리 목록 ===
@sign_bp.route("/image_history/<i_info>")
def image_history(i_info):
    rows = db_select_all(
        f"SELECT id, filename, created_at FROM {HISTORY_TABLE} WHERE i_info=%s ORDER BY created_at DESC",
        (i_info,)
    )
    return jsonify({
        "ok": True,
        "history": [{"id": r[0], "filename": r[1], "created_at": r[2].isoformat()} for r in rows]
    })


# === 후보 이미지 검색 (동/번지 기반) ===
@sign_bp.route("/image_candidates")
def image_candidates():
    dong = (request.args.get("dong") or "").strip()
    bunji = (request.args.get("bunji") or "").strip()
    folder = os.path.join(IMG_FOLDER, "candidates", dong, bunji)
    results = []
    if os.path.exists(folder):
        for f in os.listdir(folder):
            results.append({"file": f, "filename": f})
    return jsonify({"ok": True, "candidates": results})


# === 썸네일 API ===
@sign_bp.route("/thumbnail/<filename>")
def thumbnail(filename):
    # history 먼저 탐색
    path_hist = os.path.join(IMG_FOLDER, "history", filename)
    if os.path.exists(path_hist):
        img_path = path_hist
    else:
        # candidates 하위 폴더 전체 탐색
        img_path = None
        for root, dirs, files in os.walk(os.path.join(IMG_FOLDER, "candidates")):
            if filename in files:
                img_path = os.path.join(root, filename)
                break
    if not img_path or not os.path.exists(img_path):
        return "이미지 없음", 404

    img = Image.open(img_path)
    img.thumbnail((200, 150))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    buf.seek(0)
    return send_file(buf, mimetype="image/jpeg")


# === 원본 이미지 API ===
@sign_bp.route("/original/<filename>")
def original_image(filename):
    # history 먼저 탐색
    path_hist = os.path.join(IMG_FOLDER, "history", filename)
    if os.path.exists(path_hist):
        return send_file(path_hist, mimetype="image/jpeg")

    # candidates 하위 폴더 전체 탐색
    for root, dirs, files in os.walk(os.path.join(IMG_FOLDER, "candidates")):
        if filename in files:
            return send_file(os.path.join(root, filename), mimetype="image/jpeg")

    return "이미지 없음", 404
