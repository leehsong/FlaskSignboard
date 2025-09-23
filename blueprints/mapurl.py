from flask import Blueprint, request, jsonify
from urllib.parse import quote_plus
from utils.db import db_select_all
from utils.geocode import geocode_kakao  # kakao_geocode 대신 geocode_kakao
mapurl_bp = Blueprint("mapurl", __name__, url_prefix="/api/geocode")

@mapurl_bp.route("/roadview_url")
def api_company_roadview_url():
    """
    /api/map/roadview_url?i_cpn=...
    1) META_TABLE에서 도로명 주소(t_add_road) → 없으면 동/번지/상세 조합
    2) Kakao 지오코딩으로 (lng, lat) 좌표 → 네이버 v5 로드뷰 URL 반환
    3) 실패 시 네이버 검색 URL 폴백
    """
    i_cpn = (request.args.get("i_cpn") or "").strip()
    if not i_cpn:
        return jsonify({"ok": False, "msg": "i_cpn required"}), 400

    # 1) 회사 주소 로드
    have_road = True
    try:
        db_select_all(f"SELECT t_add_road FROM {META_TABLE} LIMIT 1", (), use=META_POOL)
    except Exception:
        have_road = False

    try:
        if have_road:
            cols = f"{COL_DONG}, {COL_BUNJI}, {COL_BUNJI2}, t_add_road"
            rows = db_select_all(
                f"SELECT {cols} FROM {META_TABLE} WHERE {COL_ID}=%s LIMIT 1",
                (i_cpn,), use=META_POOL
            )
            if not rows:
                return jsonify({"ok": False, "msg": "company not found"}), 404
            dong, bunji, bunji2, road = rows[0]
        else:
            cols = f"{COL_DONG}, {COL_BUNJI}, {COL_BUNJI2}"
            rows = db_select_all(
                f"SELECT {cols} FROM {META_TABLE} WHERE {COL_ID}=%s LIMIT 1",
                (i_cpn,), use=META_POOL
            )
            if not rows:
                return jsonify({"ok": False, "msg": "company not found"}), 404
            dong, bunji, bunji2 = rows[0]
            road = None
    except Exception as e:
        print("[/api/company/roadview_url] fetch meta ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500

    # 2) 주소 문자열 결정
    parts = []
    if road: parts.append(str(road).strip())
    parts += [x for x in [dong, bunji, bunji2] if x]
    addr = " ".join(map(str, parts)).strip()
    if not addr:
        return jsonify({"ok": False, "msg": "empty address"}), 400

    # 3) Kakao 지오코딩 → 네이버 로드뷰 URL
    try:
        result = kakao_geocode(addr)
        lng, lat = result["lng"], result["lat"]
        url = f"https://map.naver.com/v5/roadview/{lng},{lat}?layers=roadview"
        return jsonify({"ok": True, "url": url, "addr": addr, "lng": lng, "lat": lat})
    except GeocodeError as e:
        print("[roadview_url] geocode ERROR:", e)
        # 좌표 못 찾으면 네이버 검색 URL로 폴백
        url = f"https://map.naver.com/v5/search/{quote_plus(addr)}"
        return jsonify({"ok": True, "url": url, "addr": addr, "lng": None, "lat": None})

@mapurl_bp.get("/sync")
def api_geocode_sync():
    addr = (request.args.get("addr") or "").strip()
    if not addr:
        return jsonify({"ok": False, "msg": "addr required"}), 400
    try:
        result = kakao_geocode(addr)
        return jsonify({"ok": True, "lat": result["lat"], "lng": result["lng"]})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500