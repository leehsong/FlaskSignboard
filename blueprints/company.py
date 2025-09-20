from flask import Blueprint, request, jsonify, url_for, current_app
from utils.db import db_select_all, db_execute
import time 
company_bp = Blueprint("company", __name__)

# --- helpers ---
def cfg():
    return current_app.config

def q(sql, params=(), pool="META_POOL"):
    return db_select_all(sql, params, use=cfg()[pool])

def ex(sql, params=(), pool="META_POOL"):
    return db_execute(sql, params, use=cfg()[pool])


# ======================
# 동 목록
# ======================
@company_bp.get("/dongs")
def api_dongs():
    c = cfg()
    sql = f"""
      SELECT DISTINCT {c['COL_DONG']}
        FROM {c['META_TABLE']}
       WHERE {c['COL_DONG']} IS NOT NULL AND TRIM({c['COL_DONG']})<>''
       ORDER BY {c['COL_DONG']}
    """
    rows = q(sql)
    return jsonify({"dongs": [r[0] for r in rows]})


# ======================
# 번지 목록 (/api/bunjis/<dong>)
# ======================
@company_bp.get("/bunjis/<path:dong>")
def api_get_bunjis(dong):
    c = cfg()
    dong = (dong or "").strip()
    if not dong:
        return jsonify({"bunjis": []})

    sql = f"""
      SELECT DISTINCT {c['COL_BUNJI']}
        FROM {c['META_TABLE']}
       WHERE {c['COL_DONG']}=%s
         AND {c['COL_BUNJI']} IS NOT NULL AND TRIM({c['COL_BUNJI']})<>''
       ORDER BY {c['COL_BUNJI']}
    """
    rows = q(sql, (dong,))
    return jsonify({"bunjis": [r[0] for r in rows]})


# ======================
# 회사 목록 (/api/companies/<dong>/<bunji>)
# ======================
@company_bp.get("/companies/<path:dong>/<path:bunji>")
def api_get_companies(dong, bunji):
    c = cfg()
    dong, bunji = (dong or "").strip(), (bunji or "").strip()
    if not dong or not bunji:
        return jsonify({"companies": []})

    sql = f"""
        SELECT
            c.{c['COL_ID']} AS cidx,
            COALESCE(c.{c['COL_COMP']}, c.{c['COL_COMP_FALLBACK']}) AS company_name,
            COALESCE(c.{c['COL_BUNJI2']}, '') AS addr2,
            COUNT(s.{c['COL_ADIDX']}) AS ad_count
          FROM {c['META_TABLE']} c
     LEFT JOIN {c['SIGN_TABLE']} s
            ON s.{c['COL_CP_IDX']} = c.{c['COL_ID']}
         WHERE c.{c['COL_DONG']}=%s AND c.{c['COL_BUNJI']}=%s
         GROUP BY
            c.{c['COL_ID']},
            COALESCE(c.{c['COL_COMP']}, c.{c['COL_COMP_FALLBACK']}),
            COALESCE(c.{c['COL_BUNJI2']}, '')
         ORDER BY 2, 1
    """
    rows = q(sql, (dong, bunji))
    comps = [{"id": str(r[0]), "name": r[1], "addr2": r[2], "ad_count": int(r[3])} for r in rows]
    return jsonify({"companies": comps})


# ======================
# 회사 상세 (/api/company/info/<company_id>)
# ======================
@company_bp.get("/company/info/<company_id>")
def api_company_info(company_id):
    c = cfg()
    sql = f"""
      SELECT {c['COL_ID']}, {c['COL_COMP']}, {c['COL_DONG']}, {c['COL_BUNJI']}, {c['COL_BUNJI2']}
        FROM {c['META_TABLE']}
       WHERE {c['COL_ID']}=%s
       LIMIT 1
    """
    rows = q(sql, (company_id,))
    if not rows:
        return jsonify({"ok": False, "msg": "not found"}), 404

    cid, name, dong, bunji, bunji2 = rows[0]
    return jsonify({"ok": True, "info": {
        "company_id": str(cid),
        "company_name": name,
        "dong": dong,
        "bunji": bunji,
        "bunji2": bunji2
    }})


# ======================
# 간판 목록 (/api/signs/<company_id>)
# ======================
@company_bp.get("/signs/<company_id>")
def api_sign_info(company_id):
    c = cfg()
    sql = f"""
      SELECT {c['COL_ADIDX']}, {c['COL_SBD']}, {c['COL_SBC']}, q_img_h, q_img_w
        FROM {c['SIGN_TABLE']}
       WHERE {c['COL_CP_IDX']}=%s
       ORDER BY {c['COL_ADIDX']}
    """
    rows = db_select_all(sql, (company_id,), use=c["IMG_POOL"])
    signs = []
    for r in rows:
        i_info, sbd, sbc, h, w = r
        signs.append({
            "i_info": str(i_info),
            "type": sbd,
            "category": sbc,
            "height": h,
            "width": w,
            # 캐시 방지용 타임스탬프 파라미터 추가
            "thumb": url_for("sign.api_image_blob", ad_id=str(i_info)) + f"?v={int(time.time())}"
        })
    return jsonify({"ok": True, "signs": signs})


# ======================
# 회사 병합 (/api/merge)
# ======================
@company_bp.post("/merge")
def api_merge_companies():
    c = cfg()
    data = request.get_json(force=True, silent=True) or {}
    ids = [str(x).strip() for x in (data.get("selected_ids") or []) if str(x).strip()]
    canonical = (data.get("canonical_name") or "").strip()

    if len(ids) < 2 or not canonical:
        return jsonify({"ok": False, "msg": "selected_ids(2+)와 canonical_name 필요"}), 400

    canonical_id = min(ids)
    ph = ",".join(["%s"] * len(ids))
    ex(f"UPDATE {c['META_TABLE']} SET {c['COL_COMP']}=%s WHERE {c['COL_ID']} IN ({ph})",
       [canonical] + ids, pool="META_POOL")

    targets = [x for x in ids if x != canonical_id]
    if targets:
        ph2 = ",".join(["%s"] * len(targets))
        ex(f"UPDATE {c['SIGN_TABLE']} SET {c['COL_CP_IDX']}=%s WHERE {c['COL_CP_IDX']} IN ({ph2})",
           [canonical_id] + targets, pool="IMG_POOL")

    return jsonify({"ok": True, "canonical_id": canonical_id, "merged_ids": targets})


@company_bp.get("/dongs_with_stats")
def api_dongs_with_stats():
    c = cfg()
    # 먼저 회사 단위로 sign_count를 세고, 다시 dong 단위로 합계
    sql = f"""
      SELECT dong,
             COUNT(*) AS total,
             SUM(CASE WHEN sign_count > 0 THEN 1 ELSE 0 END) AS reviewed
        FROM (
            SELECT c.{c['COL_DONG']} AS dong,
                   c.{c['COL_ID']}   AS company_id,
                   COUNT(s.{c['COL_ADIDX']}) AS sign_count
              FROM {c['META_TABLE']} c
         LEFT JOIN {c['SIGN_TABLE']} s
                ON s.{c['COL_CP_IDX']} = c.{c['COL_ID']}
             WHERE c.{c['COL_DONG']} IS NOT NULL AND TRIM(c.{c['COL_DONG']}) <> ''
             GROUP BY c.{c['COL_DONG']}, c.{c['COL_ID']}
        ) t
    GROUP BY dong
    ORDER BY dong
    """
    rows = db_select_all(sql, (), use=c["META_POOL"])
    out = [{"dong": r[0], "total": int(r[1]), "reviewed": int(r[2])} for r in rows]
    return jsonify({"dongs": out})
