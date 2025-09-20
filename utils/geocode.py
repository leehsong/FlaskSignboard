# utils/geocode.py
import requests, os

KAKAO_KEY = os.getenv("KAKAO_KEY")

def geocode_kakao(addr: str):
    """주소 문자열을 받아 카카오 API로 (lng, lat) 좌표 반환"""
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_KEY}"}
    r = requests.get(url, params={"query": addr}, headers=headers, timeout=5)
    if r.status_code != 200:
        return None, None
    docs = r.json().get("documents", [])
    if not docs:
        return None, None
    return float(docs[0]["x"]), float(docs[0]["y"])

def kakao_get_dong(lng, lat):
    """좌표를 받아 행정동 이름 반환"""
    url = "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_KEY}"}
    r = requests.get(url, params={"x": lng, "y": lat}, headers=headers, timeout=5)
    if r.status_code != 200:
        return ""
    docs = r.json().get("documents", [])
    return docs[0].get("region_3depth_name") if docs else ""

def kakao_get_road(lng, lat):
    """좌표를 받아 도로명 주소 반환"""
    url = "https://dapi.kakao.com/v2/local/geo/coord2address.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_KEY}"}
    r = requests.get(url, params={"x": lng, "y": lat}, headers=headers, timeout=5)
    if r.status_code != 200:
        return ""
    docs = r.json().get("documents", [])
    if docs and "road_address" in docs[0]:
        return docs[0]["road_address"].get("road_name")
    return ""
