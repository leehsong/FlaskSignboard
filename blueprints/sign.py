from flask import Blueprint, request, jsonify, send_file, current_app, redirect
import io, os
import pathlib

sign_bp = Blueprint("sign", __name__)

def cfg():
    return current_app.config

def db_select(sql, params=(), pool="IMG_POOL"):
    pool = cfg()[pool]
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return rows
    finally:
        pool.putconn(conn)

def db_exec(sql, params=(), pool="IMG_POOL"):
    pool = cfg()[pool]
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        cur.close()
    finally:
        pool.putconn(conn)


# === 이미지 BLOB ===
@sign_bp.route("/image_blob/<ad_id>")
def api_image_blob(ad_id):
    pool = cfg()["IMG_POOL"]
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT b_img FROM T_X_IMG WHERE i_img=%s", (f"p_if_pk_{ad_id}",))
        row = cur.fetchone()
        cur.close()
        if row and row[0]:
            blob = row[0]
            if isinstance(blob, memoryview):
                blob = bytes(blob)
            return send_file(io.BytesIO(blob), mimetype="image/jpeg")
    finally:
        pool.putconn(conn)

    # fallback: SIGN_TABLE 내 컬럼들
    table = cfg()["SIGN_TABLE"]
    cand_cols = ["bns", "img_path", "image_path", "img_file", "img_url"]
    for col in cand_cols:
        try:
            rows = db_select(
                f"SELECT {col} FROM {table} WHERE {cfg()['COL_ADIDX']}=%s LIMIT 1",
                (ad_id,)
            )
            if rows and rows[0][0]:
                path = str(rows[0][0]).strip()
                if path.lower().startswith(("http://", "https://")):
                    return redirect(path, code=302)
                if os.path.exists(path):
                    with open(path, "rb") as f:
                        return send_file(io.BytesIO(f.read()), mimetype="image/jpeg")
        except Exception:
            continue

    return "이미지 없음", 404


# === 간판 상세 정보 ===
@sign_bp.route("/detail/<ad_id>")
def api_sign_detail(ad_id):
    c = cfg()
    sql = f"""
      SELECT s.{c['COL_ADIDX']} AS i_info,
             s.{c['COL_SBD']}   AS type,
             s.{c['COL_SBC']}   AS category,
             s.q_img_h, s.q_img_w,
             c.{c['COL_COMP']}  AS company_name
        FROM {c['SIGN_TABLE']} s
   LEFT JOIN {c['META_TABLE']} c
          ON c.{c['COL_ID']} = s.{c['COL_CP_IDX']}
       WHERE s.{c['COL_ADIDX']}=%s
       LIMIT 1
    """
    rows = db_select(sql, (ad_id,), pool="IMG_POOL")
    if not rows:
        return jsonify({"ok": False, "msg": "not found"}), 404
    i_info, typ, cat, h, w, comp = rows[0]
    return jsonify({
        "ok": True,
        "data": {
            "i_info": str(i_info),
            "type": typ,
            "category": cat,
            "width": w,
            "height": h,
            "company_name": comp
        }
    })


# === 이미지 교체 ===
@sign_bp.route("/image_replace", methods=["POST"])
def api_sign_image_replace():
    """multipart/form-data: i_info, image"""
    i_info = (request.form.get("i_info") or "").strip()
    file = request.files.get("image")
    if not i_info or not file:
        return jsonify({"ok": False, "msg": "i_info and image required"}), 400

    from PIL import Image
    MAX_W, MAX_H = 800, 600

    try:
        # === 기존 이미지 히스토리 백업 ===
        pool = cfg()["IMG_POOL"]
        conn = pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT b_img FROM T_X_IMG WHERE i_img=%s", (f"p_if_pk_{i_info}",))
            row = cur.fetchone()
            if row and row[0]:
                blob = row[0]
                if isinstance(blob, memoryview):
                    blob = bytes(blob)
                # static/history 에 파일 저장
                import pathlib, datetime
                hist_dir = pathlib.Path(current_app.static_folder) / "history"
                hist_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                fname = hist_dir / f"{i_info}_{ts}.jpg"
                with open(fname, "wb") as f:
                    f.write(blob)

                # DB 히스토리 테이블에 기록 (있을 경우)
                try:
                    cur.execute(
                        "INSERT INTO T_X_IMG_HISTORY (i_info, i_img, b_img, created_at) VALUES (%s, %s, %s, now())",
                        (i_info, f"p_if_pk_{i_info}", blob)
                    )
                    conn.commit()
                except Exception as e:
                    current_app.logger.warning(f"이미지 히스토리 테이블 기록 실패: {e}")
            cur.close()
        finally:
            pool.putconn(conn)

        # === 새 이미지 처리 ===
        img = Image.open(file.stream).convert("RGB")
        orig_w, orig_h = img.size

        # 리사이즈
        img_to_store = img
        if orig_w > MAX_W or orig_h > MAX_H:
            img_to_store = img.copy()
            img_to_store.thumbnail((MAX_W, MAX_H), Image.LANCZOS)

        buf = io.BytesIO()
        img_to_store.save(buf, format="JPEG", quality=92)
        data = buf.getvalue()

        # 새 이미지 업서트
        pool = cfg()["IMG_POOL"]
        conn = pool.getconn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO T_X_IMG (i_img, b_img) VALUES (%s,%s) "
                    "ON CONFLICT (i_img) DO UPDATE SET b_img=EXCLUDED.b_img",
                    (f"p_if_pk_{i_info}", data)
                )
            except Exception:
                cur.execute(
                    "INSERT INTO T_X_IMG (i_img, b_img) VALUES (%s,%s) "
                    "ON DUPLICATE KEY UPDATE b_img=VALUES(b_img)",
                    (f"p_if_pk_{i_info}", data)
                )
            # 원본 크기 업데이트
            cur.execute(
                f"UPDATE {cfg()['SIGN_TABLE']} SET q_img_w=%s, q_img_h=%s WHERE {cfg()['COL_ADIDX']}=%s",
                (orig_w, orig_h, i_info)
            )
            conn.commit()
            cur.close()
        finally:
            pool.putconn(conn)

        return jsonify({"ok": True, "orig_w": orig_w, "orig_h": orig_h})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500



# === 간판 삭제 ===
@sign_bp.route("/delete", methods=["POST"])
def api_sign_delete():
    data = request.get_json(force=True, silent=True) or {}
    i_info = (data.get("i_info") or "").strip()
    if not i_info:
        return jsonify({"ok": False, "msg":"i_info required"}), 400
    sql = f"DELETE FROM {cfg()['SIGN_TABLE']} WHERE {cfg()['COL_ADIDX']}=%s"
    db_exec(sql, (i_info,), pool="IMG_POOL")
    return jsonify({"ok": True, "deleted": i_info})

# blueprints/sign.py

@sign_bp.route("/history/<i_info>")
def sign_history(i_info):
    """
    간판 이미지 교체 이력을 보여주는 페이지
    예: T_X_IMG_HISTORY 테이블이나 별도 로그 테이블 필요
    """
    rows = db_select(
        "SELECT id, i_img, created_at FROM T_X_IMG_HISTORY WHERE i_info=%s ORDER BY created_at DESC",
        (i_info,),
        pool="IMG_POOL"
    )
    return render_template("sign_history.html", rows=rows, i_info=i_info)

@sign_bp.route("/static_images")
def api_static_images():
    dong = (request.args.get("dong") or "").strip()
    bunji = (request.args.get("bunji") or "").strip()
    base = pathlib.Path(current_app.static_folder) / "images"

    if not dong or not bunji:
        return jsonify({"images": []})

    # 예: 파일명이 dong_bunji_*.jpg 로 저장되어 있다고 가정
    pattern = f"{dong}_{bunji}_*"
    files = list(base.glob(pattern + ".jpg")) + list(base.glob(pattern + ".png"))
    urls = [f"/static/images/{f.name}" for f in files]

    return jsonify({"images": urls})