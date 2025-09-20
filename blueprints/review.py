from flask import Blueprint, request, jsonify, render_template, session, send_file
from utils.db import db_select_all, db_execute
import datetime as dt
import pandas as pd
from io import BytesIO

review_bp = Blueprint("review", __name__)

# === 검수 요약 페이지 ===
@review_bp.route("/summary-page")
def review_summary_page():
    return render_template("summary.html", reviewer=session.get("reviewer_name", ""))


# === 검수 로그 기록 ===
@review_bp.route("/log", methods=["POST"])
def api_review_log():
    data = request.get_json(force=True, silent=True) or {}
    i_info   = (data.get("i_info") or "").strip() or None
    i_cpn    = (data.get("i_cpn") or "").strip() or None
    action   = (data.get("action") or "").strip()
    comment  = (data.get("comment") or "").strip() or None
    reviewer = (data.get("reviewer") or "").strip() or session.get("reviewer_name", "web-user")

    if not i_info and not i_cpn:
        return jsonify({"ok": False, "msg": "i_info 또는 i_cpn 중 하나는 필수입니다."}), 400
    if not action:
        action = "inspect" if i_info else "company_review"

    sql = """
      INSERT INTO T_X_REVIEW_LOG (i_info, i_cpn, `action`, comment, reviewer, created_at)
      VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
    """
    try:
        db_execute(sql, (i_info, i_cpn, action, comment, reviewer), use=VER_POOL)
        return jsonify({"ok": True})
    except Exception as e:
        print("[/api/review/log] ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500


# === 간판 단위 로그 조회 ===
@review_bp.route("/by_sign/<i_info>")
def api_review_by_sign(i_info):
    sql = """
      SELECT id,i_info,i_cpn,`action`,comment,reviewer,created_at
        FROM T_X_REVIEW_LOG
       WHERE i_info=%s
       ORDER BY created_at DESC
       LIMIT 200
    """
    try:
        rows = db_select_all(sql, (i_info,), use=VER_POOL)
        items = [{
            "id": r[0], "i_info": r[1], "i_cpn": r[2], "action": r[3],
            "comment": r[4], "reviewer": r[5],
            "created_at": r[6].isoformat() if r[6] else None
        } for r in rows]
        return jsonify({"ok": True, "items": items})
    except Exception as e:
        print("[/api/review/by_sign] ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500


# === 회사 단위 로그 조회 ===
@review_bp.route("/by_company/<i_cpn>")
def api_review_by_company(i_cpn):
    sql = """
      SELECT id,i_info,i_cpn,`action`,comment,reviewer,created_at
        FROM T_X_REVIEW_LOG
       WHERE i_cpn=%s
       ORDER BY created_at DESC
       LIMIT 500
    """
    try:
        rows = db_select_all(sql, (i_cpn,), use=VER_POOL)
        items = [{
            "id": r[0], "i_info": r[1], "i_cpn": r[2], "action": r[3],
            "comment": r[4], "reviewer": r[5],
            "created_at": r[6].isoformat() if r[6] else None
        } for r in rows]
        return jsonify({"ok": True, "items": items})
    except Exception as e:
        print("[/api/review/by_company] ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500


# === 검수 요약 조회 ===
@review_bp.route("/summary")
def api_review_summary():
    d_from = (request.args.get("from") or "").strip()
    d_to   = (request.args.get("to") or "").strip()
    dong_f = (request.args.get("dong") or "").strip()
    kind   = (request.args.get("kind") or "all").strip()
    limit  = int(request.args.get("limit") or 1000)

    where, params = [], []

    if d_from:
        where.append("created_at >= %s")
        params.append(d_from + " 00:00:00")
    else:
        since = (dt.date.today() - dt.timedelta(days=30)).strftime("%Y-%m-%d")
        where.append("created_at >= %s")
        params.append(since + " 00:00:00")

    if d_to:
        where.append("created_at <= %s")
        params.append(d_to + " 23:59:59")

    if kind == "inspect":
        where.append("`action` = %s"); params.append("inspect")
    elif kind == "company":
        where.append("`action` = %s"); params.append("company_review")

    sql_log = "SELECT id,i_info,i_cpn,`action`,comment,reviewer,created_at FROM T_X_REVIEW_LOG"
    if where:
        sql_log += " WHERE " + " AND ".join(where)
    sql_log += " ORDER BY created_at DESC LIMIT %s"
    params2 = params + [limit]

    try:
        rows_log = db_select_all(sql_log, params2, use=VER_POOL)
    except Exception as e:
        print("[/api/review/summary] log query ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500

    items = [{
        "i_info": r[1], "i_cpn": r[2], "action": r[3],
        "comment": r[4], "reviewer": r[5], "created_at": r[6]
    } for r in rows_log]

    return jsonify({"ok": True, "rows": items})


# === 검수 요약 Excel 다운로드 ===
@review_bp.route("/summary_export")
def api_review_summary_export():
    resp = api_review_summary()
    data = resp[0].get_json() if isinstance(resp, tuple) else resp.get_json()
    if not data.get("ok"):
        return jsonify(data), 500

    rows = data.get("rows", [])
    if not rows:
        df = pd.DataFrame(columns=["동","세부주소","회사명","간판ID","작업종류","검수내용","작업자","일시"])
    else:
        df = pd.DataFrame(rows).rename(columns={
            "dong":"동","addr":"세부주소","company_name":"회사명","i_info":"간판ID",
            "action":"작업종류","comment":"검수내용","reviewer":"작업자","created_at":"일시"
        })

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="검수요약")
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name="review_summary.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
