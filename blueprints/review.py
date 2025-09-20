from flask import Blueprint, request, jsonify, session
from utils.db import db_execute, db_select_all

review_bp = Blueprint("review", __name__, url_prefix="/api/review")

@review_bp.route("/log", methods=["POST"])
def log_review():
    data = request.get_json(force=True, silent=True) or {}
    i_info = (data.get("i_info") or "").strip() or None
    i_cpn  = (data.get("i_cpn") or "").strip() or None
    action = (data.get("action") or "inspect").strip()
    comment= (data.get("comment") or "").strip()
    reviewer = session.get("reviewer_name","web-user")
    sql = """INSERT INTO T_X_REVIEW_LOG (i_info,i_cpn,`action`,comment,reviewer,created_at)
             VALUES(%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)"""
    db_execute(sql,(i_info,i_cpn,action,comment,reviewer))
    return jsonify({"ok":True})
