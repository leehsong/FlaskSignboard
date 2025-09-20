from flask import Blueprint, request, jsonify, render_template, session
from utils.db import db_select_all

illegal_bp = Blueprint("illegal", __name__)

# === 불법/신고 간판 페이지 ===
@illegal_bp.route("/")
def illegal_page():
    return render_template("illegal.html", reviewer=session.get("reviewer_name", ""))


# === 불법/신고 간판 존재하는 동 목록 ===
@illegal_bp.route("/dongs")
def api_illegal_dongs():
    sql = f"""
      SELECT DISTINCT c.{COL_DONG}
        FROM {META_TABLE} c
        JOIN {SIGN_TABLE} s ON s.{COL_CP_IDX}=c.{COL_ID}
       WHERE TRIM(s.{COL_SBF}) IN ('SBF04','SBF06')
         AND c.{COL_DONG} IS NOT NULL AND c.{COL_DONG}<>''
       ORDER BY c.{COL_DONG}
    """
    rows = db_select_all(sql)
    return jsonify({"dongs": [r[0] for r in rows]})


# === 특정 동 내 불법/신고 간판 회사 목록 ===
@illegal_bp.route("/companies")
def api_illegal_companies():
    dong = (request.args.get("dong") or "").strip()
    if not dong:
        return jsonify({"companies": []})
    sql = f"""
      SELECT c.{COL_ID} AS i_cpn,
             COALESCE(c.{COL_COMP}, c.{COL_COMP_FALLBACK}) AS company_name,
             COUNT(*) AS sign_count
        FROM {META_TABLE} c
        JOIN {SIGN_TABLE} s ON s.{COL_CP_IDX}=c.{COL_ID}
       WHERE c.{COL_DONG}=%s
         AND TRIM(s.{COL_SBF}) IN ('SBF04','SBF06')
       GROUP BY c.{COL_ID}, COALESCE(c.{COL_COMP}, c.{COL_COMP_FALLBACK})
       ORDER BY company_name, i_cpn
    """
    rows = db_select_all(sql, (dong,))
    data = [{"i_cpn": r[0], "company_name": r[1], "sign_count": int(r[2])} for r in rows]
    return jsonify({"companies": data})


# === 특정 회사의 불법/신고 간판 목록 ===
@illegal_bp.route("/signs")
def api_illegal_signs():
    i_cpn = (request.args.get("i_cpn") or "").strip()
    if not i_cpn:
        return jsonify({"signs": []})
    sql = f"""
      SELECT s.{COL_ADIDX} AS i_info,
             s.{COL_SBF} AS sc_sbf,
             s.{COL_SBD} AS sc_sbd,
             s.{COL_SBC} AS sc_sbc,
             s.q_img_h, s.q_img_w, s.q_w_test, s.q_s_temp
        FROM {SIGN_TABLE} s
       WHERE s.{COL_CP_IDX}=%s
         AND TRIM(s.{COL_SBF}) IN ('SBF04','SBF06')
       ORDER BY s.{COL_ADIDX}
    """
    rows = db_select_all(sql, (i_cpn,))
    signs = []
    for r in rows:
        i_info, sc_sbf, sc_sbd, sc_sbc, qh, qw, qwt, qst = r
        signs.append({
            "i_info": str(i_info),
            "sc_sbf": sc_sbf,
            "sc_sbd": sc_sbd,
            "sc_sbc": sc_sbc,
            "q_img_h": qh,
            "q_img_w": qw,
            "q_w_test": qwt,
            "q_s_temp": qst,
        })
    return jsonify({"signs": signs})
