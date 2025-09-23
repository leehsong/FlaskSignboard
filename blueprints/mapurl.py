from flask import Blueprint, request, jsonify, current_app

# utils.db에는 보통 db_select_all / db_execute 만 있으므로 그것만 사용합니다.
from utils.db import db_select_all

# 지오코딩 함수명이 레포마다 다를 수 있어 두 가지를 모두 시도합니다.
try:
    from utils.geocode import geocode_kakao as _geocode
except ImportError:
    from utils.geocode import kakao_geocode as _geocode

# 기존 앱에서 보통 url_prefix="/api/map" 로 등록하므로 이름을 "mapurl"로 맞춥니다.
mapurl_bp = Blueprint("mapurl", __name__)

@mapurl_bp.route("/roadview_url")
def api_company_roadview_url():
    """
    /api/map/roadview_url?i_cpn=...
    - 회사 메타테이블에서 도로명 주소(t_add_road)와 번지(t_add_num)를 가져옴
    - 주소는 '도로명만 사용', 없을 경우에만 '번지' 사용 (동/번지/도로명 조합 금지)
    - Kakao 지오코딩으로 좌표 → 네이버 v5 로드뷰 URL 반환
    """
    i_cpn = (request.args.get("i_cpn") or "").strip()
    if not i_cpn:
        return jsonify({"ok": False, "msg": "i_cpn required"}), 400

    c = current_app.config
    # 도로명(t_add_road) + 번지(COL_BUNJI)만 가져옵니다.
    sql = f"""
      SELECT t_add_road, {c['COL_BUNJI']}
        FROM {c['META_TABLE']}
       WHERE {c['COL_ID']}=%s
       LIMIT 1
    """
    rows = db_select_all(sql, (i_cpn,), use=c["META_POOL"])
    if not rows:
        return jsonify({"ok": False, "msg": "company not found"}), 404

    road, bunji = rows[0]

    # === 주소 문자열: 도로명만 사용, 없으면 번지 사용 ===
    road = (road or "").strip()
    bunji = (bunji or "").strip()
    addr = road if road else bunji

    if not addr:
        return jsonify({"ok": False, "msg": "empty address"}), 400

    # Kakao 지오코딩 → 네이버 로드뷰 URL
    try:
        # _geocode는 (lng, lat) 또는 dict를 반환할 수 있으니 유연 처리
        geo = _geocode(addr)
        if isinstance(geo, dict):
            lng, lat = geo.get("lng"), geo.get("lat")
        else:
            lng, lat = geo  # (lng, lat) 튜플
        if lng is None or lat is None:
            raise ValueError("geocode returned empty coords")

        url = f"https://map.naver.com/v5/roadview/{lng},{lat}?layers=roadview"
        return jsonify({"ok": True, "url": url, "addr": addr, "lng": lng, "lat": lat})
    except Exception as e:
        # 좌표 못 찾으면 네이버 검색으로 폴백
        from urllib.parse import quote_plus
        url = f"https://map.naver.com/v5/search/{quote_plus(addr)}"
        # 폴백도 ok=True로 주면 iframe에서 바로 열 수 있습니다.
        return jsonify({"ok": True, "url": url, "addr": addr, "lng": None, "lat": None, "fallback": True, "msg": str(e)})
