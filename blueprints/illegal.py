from flask import Blueprint, request, jsonify, render_template, session, current_app
from utils.db import db_select_all

illegal_bp = Blueprint("illegal", __name__)

# === 불법/신고 간판 페이지 ===
@illegal_bp.route("/")
def illegal_page():
    return render_template("illegal.html", reviewer=session.get("reviewer_name", ""))

# === 불법/신고 간판 존재하는 동 목록 ===
@illegal_bp.route("/dongs")
def api_illegal_dongs():
    c = current_app.config
    sql = f"""
      SELECT DISTINCT c.{c['COL_DONG']}
        FROM {c['META_TABLE']} c
        JOIN {c['SIGN_TABLE']} s ON s.{c['COL_CP_IDX']}=c.{c['COL_ID']}
       WHERE TRIM(s.{c['COL_SBF']}) IN ('SBF04','SBF06')
         AND c.{c['COL_DONG']} IS NOT NULL AND c.{c['COL_DONG']}<>''
       ORDER BY c.{c['COL_DONG']}
    """
    rows = db_select_all(sql, use=c["META_POOL"])
    return jsonify({"dongs": [r[0] for r in rows]})

# === 특정 동 내 불법/신고 간판 회사 목록 ===
@illegal_bp.route("/companies")
def api_illegal_companies():
    c = current_app.config
    dong = (request.args.get("dong") or "").strip()
    if not dong:
        return jsonify({"companies": []})

    sql = f"""
      SELECT c.{c['COL_ID']} AS i_cpn,
             COALESCE(c.{c['COL_COMP']}, c.{c['COL_COMP_FALLBACK']}) AS company_name,
             COUNT(*) AS sign_count
        FROM {c['META_TABLE']} c
        JOIN {c['SIGN_TABLE']} s ON s.{c['COL_CP_IDX']}=c.{c['COL_ID']}
       WHERE c.{c['COL_DONG']}=%s
         AND TRIM(s.{c['COL_SBF']}) IN ('SBF04','SBF06')
       GROUP BY c.{c['COL_ID']}, COALESCE(c.{c['COL_COMP']}, c.{c['COL_COMP_FALLBACK']})
       ORDER BY company_name, i_cpn
    """
    rows = db_select_all(sql, (dong,), use=c["META_POOL"])
    data = [{"i_cpn": r[0], "company_name": r[1], "sign_count": int(r[2])} for r in rows]
    return jsonify({"companies": data})

# === 특정 회사의 불법/신고 간판 목록 ===
@illegal_bp.route("/signs")
def api_illegal_signs():
    c = current_app.config
    i_cpn = (request.args.get("i_cpn") or "").strip()
    if not i_cpn:
        return jsonify({"signs": []})

    sql = f"""
      SELECT s.{c['COL_ADIDX']} AS i_info,
             s.{c['COL_SBF']} AS sc_sbf,
             s.{c['COL_SBD']} AS sc_sbd,
             s.{c['COL_SBC']} AS sc_sbc,
             s.q_img_h, s.q_img_w, s.q_w_test, s.q_s_temp
        FROM {c['SIGN_TABLE']} s
       WHERE s.{c['COL_CP_IDX']}=%s
         AND TRIM(s.{c['COL_SBF']}) IN ('SBF04','SBF06')
       ORDER BY s.{c['COL_ADIDX']}
    """
    rows = db_select_all(sql, (i_cpn,), use=c["IMG_POOL"])
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

@illegal_bp.route("/all_signs")
def api_all_signs():
    c = current_app.config
    i_cpn = (request.args.get("i_cpn") or "").strip()
    if not i_cpn:
        return jsonify({"signs": []})

    sql = f"""
      SELECT s.{c['COL_ADIDX']} AS i_info,
             s.{c['COL_SBF']}   AS sc_sbf,
             s.{c['COL_SBD']}   AS sc_sbd,
             s.{c['COL_SBC']}   AS sc_sbc,
             s.q_img_h, s.q_img_w, s.q_w_test, s.q_s_temp
        FROM {c['SIGN_TABLE']} s
       WHERE s.{c['COL_CP_IDX']}=%s
       ORDER BY s.{c['COL_ADIDX']}
    """
    rows = db_select_all(sql, (i_cpn,), use=c["IMG_POOL"])

    # 코드 → 한글 변환
    map_sbf = {"SBF01":"합법","SBF02":"허가","SBF03":"신고",
               "SBF04":"불법","SBF05":"철거대상","SBF06":"미등록"}
    map_sbd = {"SBD01":"간판","SBD02":"현수막","SBD03":"입간판"}
    map_sbc = {"SBC01":"벽부","SBC02":"돌출","SBC03":"옥상"}

    signs = []
    for r in rows:
        i_info, sc_sbf, sc_sbd, sc_sbc, qh, qw, qwt, qst = r
        sbf_label = map_sbf.get(sc_sbf, "미분류")
        sbd_label = map_sbd.get(sc_sbd, "미분류")
        sbc_label = map_sbc.get(sc_sbc, "미분류")
        signs.append({
            "i_info": str(i_info),
            "분류": f"{sbf_label} / {sbd_label} / {sbc_label}",
            "q_img_h": qh, "q_img_w": qw
        })
    return jsonify({"signs": signs})

