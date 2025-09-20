from flask import Blueprint, request, jsonify
from utils.db import db_execute, db_select_all_dict
from extensions import logger

mapurl_bp = Blueprint("mapurl", __name__, url_prefix="/api/company")

@mapurl_bp.route("/mapurl", methods=["GET"])
def get_mapurl():
    i_cpn = (request.args.get("i_cpn") or "").strip()
    rows = db_select_all_dict(
        "SELECT i_cpn, navrv_url, addr_text, lng, lat, updated_at "
        "FROM public.t_x_company_mapurl WHERE i_cpn=%s",[i_cpn])
    return jsonify(rows[0] if rows else {"ok": False})
