from flask import Blueprint, request, jsonify
from utils.db import db_select_all

illegal_bp = Blueprint("illegal", __name__, url_prefix="/api/illegal")

@illegal_bp.route("/dongs")
def illegal_dongs():
    sql = """
      SELECT DISTINCT c.t_add_3
        FROM public.t_b_cpn c
        JOIN public.t_sb_info s ON s.i_cpn=c.i_cpn
       WHERE TRIM(s.i_sc_sbf) IN ('SBF04','SBF06')
    """
    rows = db_select_all(sql)
    return jsonify({"dongs":[r[0] for r in rows]})
