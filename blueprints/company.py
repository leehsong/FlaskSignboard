from flask import Blueprint, request, jsonify, url_for
from utils.db import db_select_all, db_execute, db_select_all_dict
from utils.geocode import geocode_kakao, kakao_get_dong, kakao_get_road
from extensions import logger

company_bp = Blueprint("company", __name__, url_prefix="/api/company")

META_TABLE = "public.t_b_cpn"
SIGN_TABLE = "public.t_sb_info"
COL_ID, COL_COMP, COL_DONG, COL_BUNJI, COL_CP_IDX = "i_cpn","t_cpn","t_add_3","t_add_num","i_cpn"
COL_COMP_FALLBACK = "i_cpn"

@company_bp.route("/update", methods=["POST"])
def update_company():
    data = request.get_json(force=True, silent=True) or {}
    i_cpn = (data.get("i_cpn") or "").strip()
    fields = data.get("fields") or {}
    if not i_cpn or not fields:
        return jsonify({"ok": False, "msg": "invalid payload"}), 400

    dong, road, bunji = fields.get("t_add_3"), fields.get("t_add_road"), fields.get("t_add_num")
    if road and bunji and not dong:
        lng, lat = geocode_kakao(f"{road} {bunji}")
        if lng and lat: fields["t_add_3"] = kakao_get_dong(lng, lat)
    if dong and bunji and not road:
        lng, lat = geocode_kakao(f"{dong} {bunji}")
        if lng and lat: fields["t_add_road"] = kakao_get_road(lng, lat)

    sets, params = [], []
    for k,v in fields.items():
        sets.append(f"{k}=%s"); params.append(v)
    sql = f"UPDATE {META_TABLE} SET {', '.join(sets)} WHERE {COL_ID}=%s"
    params.append(i_cpn)
    db_execute(sql, params)
    return jsonify({"ok": True, "fields": fields})

@company_bp.route("/delete", methods=["POST"])
def delete_company():
    data = request.get_json(force=True, silent=True) or {}
    i_cpn = (data.get("i_cpn") or "").strip()
    if not i_cpn:
        return jsonify({"ok": False, "msg":"i_cpn required"}), 400
    db_execute(f"DELETE FROM {META_TABLE} WHERE {COL_ID}=%s", (i_cpn,))
    return jsonify({"ok": True})

@company_bp.route("/detail")
def detail():
    i_cpn = (request.args.get("i_cpn") or "").strip()
    if not i_cpn:
        return jsonify({"ok": False, "msg": "i_cpn required"}), 400
    rows = db_select_all_dict(f"SELECT * FROM {META_TABLE} WHERE {COL_ID}=%s", (i_cpn,))
    return jsonify(rows[0] if rows else {"ok": False, "msg": "not found"})

@company_bp.route("/merge", endpoint="merge_page")
def merge_page():
    return render_template("merge.html", reviewer=session.get("reviewer_name",""))
