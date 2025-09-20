import os, uuid
import pandas as pd
from flask import Blueprint, request, render_template, redirect, url_for, session, jsonify
from werkzeug.utils import secure_filename
from config import Config

upload_bp = Blueprint("upload", __name__)

# 내부 세션 데이터 저장
def _save_session_data(upload_id, rows, addr_full, reviewer):
    path = Config.DATA_DIR / f"{upload_id}.json"
    with path.open("w", encoding="utf-8") as f:
        import json
        json.dump({"rows": rows, "addr_full": addr_full, "reviewer": reviewer}, f, ensure_ascii=False)

def _load_session_data():
    upload_id = session.get("upload_id")
    if not upload_id:
        return None
    path = Config.DATA_DIR / f"{upload_id}.json"
    if not path.exists():
        return None
    import json
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# === XLS 업로드 페이지 ===
@upload_bp.route("/", methods=["GET", "POST"])
def upload_index():
    if "reviewer_name" not in session:
        return redirect(url_for("core.start"))

    if request.method == "POST":
        f = request.files.get("excel")
        if not f or f.filename == "":
            return render_template("index.html", error="엑셀 파일을 선택하세요.", reviewer=session["reviewer_name"])
        if not f.filename.lower().endswith((".xls", ".xlsx")):
            return render_template("index.html", error="허용되지 않는 파일 형식입니다.", reviewer=session["reviewer_name"])

        path = os.path.join(Config.UPLOAD_FOLDER, secure_filename(f.filename))
        f.save(path)

        try:
            df = pd.read_excel(path)
        except Exception as e:
            return render_template("index.html", error=f"엑셀 읽기 오류: {e}", reviewer=session["reviewer_name"])

        # 기본 컬럼
        base_cols = [COL_ADIDX, COL_COMP, COL_DONG, COL_BUNJI]
        for c in base_cols:
            if c not in df.columns:
                df[c] = ""

        # 확장 컬럼
        view_cols = base_cols + ["ad_specification", "ad_height", "ad_type"]
        for c in view_cols:
            if c not in df.columns:
                df[c] = ""

        rows_df = df[view_cols].fillna("")
        addr_full = df.get(COL_BUNJI2, pd.Series([""] * len(df))).fillna("").tolist()

        # 세션 데이터 저장
        upload_id = uuid.uuid4().hex
        _save_session_data(upload_id, rows_df.to_dict("records"), addr_full, session["reviewer_name"])
        session["upload_id"] = upload_id
        session["cursor"] = 0

        return redirect(url_for("review.review"))  # review 블루프린트와 연동

    return render_template("index.html", reviewer=session["reviewer_name"])


# === 업로드 상태 확인 ===
@upload_bp.route("/state")
def api_state():
    data = _load_session_data() or {"rows": []}
    idx = int(session.get("cursor", 0))
    return jsonify({"index": idx, "total": len(data["rows"])})
