# utils/geocode.py
import os
from functools import lru_cache

import requests

KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "").strip()

_session = requests.Session()
if KAKAO_REST_API_KEY:
    _session.headers.update({"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"})


class GeocodeError(Exception):
    """Raised when geocoding fails."""


@lru_cache(maxsize=10000)
def kakao_geocode(query: str, timeout: float = 5.0) -> dict:
    """
    주소/키워드 문자열 -> {'lng': float, 'lat': float, 'source': 'address'|'keyword'}
    실패 시 GeocodeError
    """
    if not KAKAO_REST_API_KEY:
        raise GeocodeError("KAKAO_REST_API_KEY not set")

    q = (query or "").strip()
    if not q:
        raise GeocodeError("empty query")

    # 1) 주소 검색
    try:
        r = _session.get(
            "https://dapi.kakao.com/v2/local/search/address.json",
            params={"query": q},
            timeout=timeout,
        )
        r.raise_for_status()
        docs = r.json().get("documents", [])
        if docs:
            return {"lng": float(docs[0]["x"]), "lat": float(docs[0]["y"]), "source": "address"}
    except requests.RequestException:
        pass

    # 2) 키워드 검색 폴백
    try:
        r2 = _session.get(
            "https://dapi.kakao.com/v2/local/search/keyword.json",
            params={"query": q},
            timeout=timeout,
        )
        r2.raise_for_status()
        docs2 = r2.json().get("documents", [])
        if docs2:
            return {"lng": float(docs2[0]["x"]), "lat": float(docs2[0]["y"]), "source": "keyword"}
    except requests.RequestException:
        pass

    raise GeocodeError(f"not found: {q}")
