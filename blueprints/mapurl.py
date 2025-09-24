# blueprints/mapurl.py
from flask import Blueprint, request, jsonify
from urllib.parse import quote_plus
from utils.db import db_select_all, db_execute
from utils.geocode import geocode_kakao, GeocodeError
from extensions import logger

# META_TABLE, META_POOL, COL_ID, COL_DONG, COL_BUNJI, COL_BUNJI2는 config에서 import
# 예시:
# from config import META_TABLE, META_POOL, COL_ID, COL_DONG, COL_BUNJI, COL_BUNJI2

mapurl_bp = Blueprint("mapurl", __name__, url_prefix="/api/map")

# === 로드뷰 URL 조회 ===
@mapurl_bp.route("/roadview_url")
def api_company_roadview_url():
    """
    /api/map/roadview_url?i_cpn=...
    1) META_TABLE에서 도로명 주소(t_add_road)를 우선 조회
    2) Kakao 지오코딩으로 (lng, lat) 좌표 → 네이버 v5 로드뷰 URL 반환
    3) 실패 시 네이버 검색 URL 폴백
    """
    i_cpn = (request.args.get("i_cpn") or "").strip()
    if not i_cpn:
        return jsonify({"ok": False, "msg": "i_cpn required"}), 400

    try:
        # 회사 주소 조회 (도로명 주소 포함)
        rows = db_select_all(
            f"SELECT t_add_road, {COL_DONG}, {COL_BUNJI}, {COL_BUNJI2} "
            f"FROM {META_TABLE} WHERE {COL_ID}=%s LIMIT 1",
            (i_cpn,), use=META_POOL
        )
        if not rows:
            return jsonify({"ok": False, "msg": "company not found"}), 404

        road, dong, bunji, bunji2 = rows[0]

        # 주소 문자열: 도로명 주소 > 동/번지 조합
        if road and str(road).strip():
            addr = str(road).strip()
        else:
            parts = [x for x in [dong, bunji, bunji2] if x]
            addr = " ".join(map(str, parts)).strip()

        if not addr:
            return jsonify({"ok": False, "msg": "empty address"}), 400

        # Kakao 지오코딩 → 네이버 로드뷰 URL
        try:
            result = geocode_kakao(addr)
            lng, lat = result["lng"], result["lat"]
            url = f"https://map.naver.com/v5/roadview/{lat},{lng}?c={lng},{lat},0,0,0,dh"
            return jsonify({"ok": True, "url": url, "addr": addr, "lng": lng, "lat": lat})
        except GeocodeError as e:
            logger.warning("[roadview_url] geocode ERROR: %s", e)
            url = f"https://map.naver.com/v5/search/{quote_plus(addr)}"
            return jsonify({"ok": True, "url": url, "addr": addr, "lng": None, "lat": None})

    except Exception as e:
        logger.error("[/api/map/roadview_url] fetch meta ERROR: %s", e)
        return jsonify({"ok": False, "msg": str(e)}), 500


# === 로드뷰 URL 저장 ===
@mapurl_bp.route("/roadview_save", methods=["POST"])
def api_company_roadview_save():
    """
    /api/map/roadview_save
    payload: { i_cpn: "...", navrv_url: "..." }
    """
    data = request.get_json(force=True, silent=True) or {}
    i_cpn = (data.get("i_cpn") or "").strip()
    navrv_url = (data.get("navrv_url") or "").strip()

    if not i_cpn or not navrv_url:
        return jsonify({"ok": False, "msg": "invalid params"}), 400

    sql = """
        INSERT INTO public.t_x_company_mapurl (i_cpn, navrv_url, updated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (i_cpn)
        DO UPDATE SET navrv_url=EXCLUDED.navrv_url, updated_at=NOW()
    """
    try:
        db_execute(sql, (i_cpn, navrv_url))
        return jsonify({"ok": True})
    except Exception as e:
        logger.error("[/api/map/roadview_save] ERROR: %s", e)
        return jsonify({"ok": False, "msg": str(e)}), 500
