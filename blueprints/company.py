# blueprints/company.py
from flask import Blueprint, request, jsonify, current_app
import os, configparser, re
from functools import lru_cache
from typing import List, Tuple, Dict, Optional

company_bp = Blueprint("company", __name__, url_prefix="/api/company")

# ------------------------------------------------------------------------------
# [1] 스키마 컬럼 매핑
# - 기본 테이블을 t_b_cpn으로 설정
# - 실제 컬럼명이 다르면 환경변수로 덮어쓰세요.
# - 일부 컬럼은 자동 추정(옵션) 로직이 보조합니다.
# ------------------------------------------------------------------------------
COLMAP = {
    "companies": {
        "table": os.getenv("COMPANY_TABLE", "t_b_cpn"),
        "id": os.getenv("COMPANY_ID_COL", "id"),                   # PK(없어도 동작은 가능)
        "name": os.getenv("COMPANY_NAME_COL", "name"),             # 상호/회사명
        "emd": os.getenv("COMPANY_EMD_COL", "emd"),                # 읍면동/행정동
        "address": os.getenv("COMPANY_ADDRESS_COL", "address"),    # 단일 주소 컬럼(있으면 활용)

        # 주소 관련 세부 컬럼(있으면 자동으로 병합하여 반환)
        "road_addr": os.getenv("COMPANY_ROAD_ADDR_COL", None),     # 도로명주소
        "jibun_addr": os.getenv("COMPANY_JIBUN_ADDR_COL", None),   # 지번주소
        "addr1": os.getenv("COMPANY_ADDR1_COL", None),             # 주소1
        "addr2": os.getenv("COMPANY_ADDR2_COL", None),             # 주소2(상세)

        # 행정구역 세분화
        "sido": os.getenv("COMPANY_SIDO_COL", None),
        "sigungu": os.getenv("COMPANY_SIGUNGU_COL", None),
        "dong": os.getenv("COMPANY_DONG_COL", None),  # dong/eup/myeon 등

        # 비즈니스/연락처/좌표
        "bizno": os.getenv("COMPANY_BIZNO_COL", "bizno"),
        "tel": os.getenv("COMPANY_TEL_COL", None),
        "lat": os.getenv("COMPANY_LAT_COL", None),
        "lon": os.getenv("COMPANY_LON_COL", os.getenv("COMPANY_LNG_COL", None)),
        "category": os.getenv("COMPANY_CATEGORY_COL", None),       # 업종/분류
        "ceo": os.getenv("COMPANY_CEO_COL", None),
    },
    "signboards": {
        # 기존 간판 테이블 설정(필요 시 환경변수로 교체)
        "table": os.getenv("SIGNBOARD_TABLE", "signboards"),
        "id": os.getenv("SIGNBOARD_ID_COL", "id"),
        "company_id": os.getenv("SIGNBOARD_COMPANY_ID_COL", "company_id"),
        "company_name": os.getenv("SIGNBOARD_COMPANY_NAME_COL", "company_name"),
        "emd": os.getenv("SIGNBOARD_EMD_COL", "emd"),
        "address": os.getenv("SIGNBOARD_ADDRESS_COL", "address"),
        "bizno": os.getenv("SIGNBOARD_BIZNO_COL", "bizno"),
        "image_url": os.getenv("SIGNBOARD_IMG_COL", "image_url"),
        "status": os.getenv("SIGNBOARD_STATUS_COL", "status"),
        "updated_at": os.getenv("SIGNBOARD_UPDATED_AT_COL", "updated_at"),
    },
}

# ------------------------------------------------------------------------------
# [2] 공통 유틸
# ------------------------------------------------------------------------------
@lru_cache
def _project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

@lru_cache
def _load_db_config():
    cfg_path = os.path.join(_project_root(), "db_config.ini")
    cp = configparser.ConfigParser()
    cp.read(cfg_path, encoding="utf-8")
    return cp

def _param_placeholder(dialect: str) -> str:
    # psycopg2(%s) / PyMySQL(%s) / sqlite3(?)
    return "%s" if dialect in ("postgresql", "mysql") else "?"

def _cursor(conn, dialect: str, dict_cursor: bool = True):
    if dialect == "postgresql" and dict_cursor:
        from psycopg2.extras import RealDictCursor
        return conn.cursor(cursor_factory=RealDictCursor)
    return conn.cursor()

def _row_to_dict(row):
    try:
        return {k: row[k] for k in row.keys()}
    except Exception:
        try:
            return dict(row)
        except Exception:
            raise

def _columns_of_table(conn, dialect: str, table: str) -> List[str]:
    cur = _cursor(conn, dialect, dict_cursor=False)
    try:
        if dialect == "postgresql":
            cur.execute("""
                SELECT column_name
                  FROM information_schema.columns
                 WHERE table_schema = 'public' AND table_name = %s
            """, (table,))
            cols = [r[0] for r in cur.fetchall()]
        elif dialect == "mysql":
            cur.execute("""
                SELECT column_name
                  FROM information_schema.columns
                 WHERE table_schema = DATABASE() AND table_name = %s
            """, (table,))
            cols = [r[0] for r in cur.fetchall()]
        else:  # sqlite
            cur.execute(f"PRAGMA table_info({table})")
            cols = [r[1] for r in cur.fetchall()]
        return cols
    finally:
        cur.close()

def _get_connection():
    cp = _load_db_config()
    if "postgresql" in cp:
        import psycopg2
        sec = cp["postgresql"]
        conn = psycopg2.connect(
            host=sec.get("host", "localhost"),
            dbname=sec.get("database") or sec.get("dbname"),
            user=sec.get("user"),
            password=sec.get("password", ""),
            port=sec.getint("port", 5432),
        )
        return conn, "postgresql"
    if "mysql" in cp or "mariadb" in cp:
        import pymysql
        sec = cp["mysql"] if "mysql" in cp else cp["mariadb"]
        conn = pymysql.connect(
            host=sec.get("host", "localhost"),
            db=sec.get("database"),
            user=sec.get("user"),
            password=sec.get("password", ""),
            port=sec.getint("port", 3306),
            charset=sec.get("charset", "utf8mb4"),
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
        return conn, "mysql"
    if "sqlite" in cp:
        import sqlite3
        sec = cp["sqlite"]
        path = sec.get("path", os.path.join(_project_root(), "data", "signboards.db"))
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn, "sqlite"
    raise RuntimeError("db_config.ini에 [postgresql] / [mysql] / [sqlite] 중 하나가 필요합니다.")

# ------------------------------------------------------------------------------
# [3] 컬럼 자동 추정(옵션): t_b_cpn이 표준 이름이 아닐 때 보조 매핑
# ------------------------------------------------------------------------------
def _pick_first(cols_lc: set, *cands) -> Optional[str]:
    for cand in cands:
        if cand and cand.lower() in cols_lc:
            return cand
    return None

def _ensure_company_colmap(conn, dialect: str):
    """
    환경변수로 지정되지 않았거나 실제 테이블에 없는 경우,
    흔한 컬럼명 패턴을 기반으로 보조 매핑을 시도합니다.
    """
    cm = COLMAP["companies"]
    table = cm["table"]
    cols = _columns_of_table(conn, dialect, table)
    cols_lc = {c.lower(): c for c in cols}  # lc -> original
    def resolve(*names):  # 실제 존재하는 원본 컬럼명 반환
        pick = _pick_first(set(cols_lc.keys()), *names)
        return cols_lc.get(pick) if pick else None

    # name
    if cm["name"] not in cols:
        cm["name"] = resolve("name", "cpn_nm", "corp_nm", "company_nm",
                             "bizes_nm", "entrps_nm", "store_nm", "sangho", "title") or cm["name"]
    # id
    if cm["id"] not in cols:
        cm["id"] = resolve("id", "cpn_id", "corp_id", "company_id", "idx")
    # emd/dong
    if cm["emd"] not in cols:
        cm["emd"] = resolve("emd", "emd_nm", "dong", "dong_nm", "li_nm", "eupmyeon", "eupmyeondong")
    # address variants
    for key, candidates in {
        "address": ("address", "addr", "full_addr", "addr_full"),
        "road_addr": ("road_addr", "rd_addr", "rdnm_addr", "roadaddress", "raddr"),
        "jibun_addr": ("jibun_addr", "lotno_addr", "lno_addr", "jibunaddress", "jaddr"),
        "addr1": ("addr1", "address1", "addr_1"),
        "addr2": ("addr2", "address2", "addr_2", "detail_addr", "addr_detail"),
        "sido": ("sido", "si_do", "sido_nm", "ctprvn_nm"),
        "sigungu": ("sigungu", "si_gun_gu", "sgg_nm"),
        "dong": ("dong", "dong_nm", "legal_dong", "adm_dong"),
        "bizno": ("bizno", "biz_no", "bizregno", "bno", "brno", "saupja_no"),
        "tel": ("tel", "telno", "phone", "tel_no", "tel1"),
        "lat": ("lat", "y", "latitude"),
        "lon": ("lon", "lng", "x", "longitude"),
        "category": ("category", "cate", "induty", "industry", "bupjong", "업종"),
        "ceo": ("ceo", "owner", "repr_nm", "대표자명"),
    }.items():
        if cm.get(key) not in cols:
            guessed = resolve(*candidates)
            if guessed:
                cm[key] = guessed

# ------------------------------------------------------------------------------
# [4] 주소/메타 정규화(응답용)
# ------------------------------------------------------------------------------
def _compose_address_view(cm: Dict[str, str], row: Dict) -> Dict:
    g = lambda k: (cm.get(k) and row.get(cm[k])) or None
    # 우선순위: road_addr > (addr1 + addr2) > address > jibun_addr
    addr1 = g("addr1")
    addr2 = g("addr2")
    preferred = g("road_addr") or " ".join([a for a in [addr1, addr2] if a]) or g("address") or g("jibun_addr")

    return {
        "address_preferred": preferred,
        "address_road": g("road_addr"),
        "address_jibun": g("jibun_addr"),
        "addr1": addr1,
        "addr2": addr2,
        "sido": g("sido"),
        "sigungu": g("sigungu"),
        "emd": g("emd") or g("dong"),
        "dong": g("dong"),
        "tel": g("tel"),
        "bizno": g("bizno"),
        "lat": (float(g("lat")) if g("lat") not in (None, "",) else None) if g("lat") is not None else None,
        "lon": (float(g("lon")) if g("lon") not in (None, "",) else None) if g("lon") is not None else None,
        "category": g("category"),
        "ceo": g("ceo"),
    }

# ------------------------------------------------------------------------------
# [5] 문자열 전처리 + fuzzy 스코어링
# ------------------------------------------------------------------------------
_COMPANY_STOPWORDS = (
    "주식회사", "㈜", "(주)", "유한회사", "(유)", "유한",
    "co.,ltd", "co.ltd", "co ltd", "ltd", "inc", "llc", "gmbh", "sas", "s.a.", "pte", "k.k", "kk", "corp", "company"
)

def _normalize_company_name(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[\s\.\-_/&+·•,:;'\"`~!?()\[\]{}]+", "", s)
    for w in _COMPANY_STOPWORDS:
        s = s.replace(w, "")
    return s

def _score_similarity(a: str, b: str) -> int:
    try:
        from rapidfuzz import fuzz
        return max(int(fuzz.ratio(a, b)), int(fuzz.partial_ratio(a, b)))
    except Exception:
        from difflib import SequenceMatcher
        return int(round(100 * SequenceMatcher(None, a, b).ratio()))

def _as_bool(v) -> bool:
    return str(v).strip().lower() in {"1", "true", "t", "yes", "y", "on"}

def _has_pg_trgm(conn) -> bool:
    cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM pg_extension WHERE extname='pg_trgm'")
        return cur.fetchone() is not None
    except Exception:
        return False
    finally:
        cur.close()

# ------------------------------------------------------------------------------
# [6] 검색: t_b_cpn(회사) -> 후보군 -> 간판 연계
# ------------------------------------------------------------------------------
def _build_or_like_clause(alias: str, cols: List[str], ph: str) -> Tuple[str, int]:
    parts = [f"LOWER(COALESCE({alias}.{c}, '')) LIKE {ph}" for c in cols]
    return "(" + " OR ".join(parts) + ")", len(parts)

def _find_companies(
    conn,
    dialect: str,
    emd: str,
    company: str,
    limit: int = 20,
    fuzzy: bool = False,
    threshold: float = 70.0,
    pool: int = 300,
    return_scores: bool = False,
):
    cm = COLMAP["companies"]
    _ensure_company_colmap(conn, dialect)  # 자동 보정

    table = cm["table"]
    namec = cm["name"]
    idc = cm.get("id")

    # emd/주소 필터에 사용할 후보 컬럼들(존재하는 것만)
    all_filters = [c for c in [
        cm.get("emd"), cm.get("dong"),
        cm.get("address"), cm.get("road_addr"), cm.get("jibun_addr"),
        cm.get("addr1"), cm.get("addr2"),
        cm.get("sido"), cm.get("sigungu"),
    ] if c]

    ph = _param_placeholder(dialect)
    like_emd = f"%{emd.strip().lower()}%"
    q_company = company.strip()
    q_norm = _normalize_company_name(q_company)

    if not namec:
        raise RuntimeError("회사명 컬럼(name) 매핑을 찾을 수 없습니다. COMPANY_NAME_COL 환경변수를 지정하세요.")

    # 1) fuzzy 아님 → LIKE 기반
    if not fuzzy:
        where_addr, n_addr = _build_or_like_clause("c", all_filters, ph) if all_filters else ("TRUE", 0)
        sql = f"""
        SELECT *
          FROM {table} c
         WHERE {where_addr}
           AND LOWER(COALESCE(c.{namec}, '')) LIKE {ph}
         ORDER BY {('c.' + idc) if idc else f"LOWER(c.{namec})"}
         LIMIT {limit}
        """
        params = [like_emd] * n_addr + [f"%{q_company.lower()}%"]
        cur = _cursor(conn, dialect, dict_cursor=True)
        try:
            cur.execute(sql, params)
            rows = [_row_to_dict(r) for r in cur.fetchall()]
        finally:
            cur.close()
        if return_scores:
            for r in rows:
                r["_match"] = {"score": 100, "method": "like"}
        return rows

    # 2) fuzzy → DB별 전략
    # 2-1) Postgres + pg_trgm
    if dialect == "postgresql" and _has_pg_trgm(conn):
        th = threshold/100.0 if threshold > 1 else float(th)
        where_addr, n_addr = _build_or_like_clause("c", all_filters, ph) if all_filters else ("TRUE", 0)
        sql = f"""
        SELECT c.*, similarity(LOWER(c.{namec}), {ph}) AS score
          FROM {table} c
         WHERE {where_addr}
           AND LOWER(c.{namec}) % {ph}
           AND similarity(LOWER(c.{namec}), {ph}) >= {ph}
         ORDER BY score DESC, {('c.' + idc) if idc else f"LOWER(c.{namec})"} ASC
         LIMIT {limit}
        """
        params = [like_emd]*n_addr + [q_company.lower(), q_company.lower(), th]
        cur = _cursor(conn, dialect, dict_cursor=True)
        try:
            cur.execute(sql, params)
            rows = [_row_to_dict(r) for r in cur.fetchall()]
        finally:
            cur.close()
        if return_scores:
            for r in rows:
                s = r.pop("score", None)
                r["_match"] = {"score": round(float(s)*100, 1) if s is not None else None,
                               "method": "pg_trgm", "query": q_company}
        return rows

    # 2-2) 기타 → 주소 조건으로 후보 pool 뽑은 후 파이썬에서 유사도
    where_addr, n_addr = _build_or_like_clause("c", all_filters, ph) if all_filters else ("TRUE", 0)
    sql_pool = f"""
    SELECT *
      FROM {table} c
     WHERE {where_addr}
     LIMIT {pool}
    """
    cur = _cursor(conn, dialect, dict_cursor=True)
    try:
        cur.execute(sql_pool, [like_emd]*n_addr)
        cand = [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        cur.close()

    rescored: List[Tuple[dict, int]] = []
    for r in cand:
        name_val = str(r.get(namec, "")).strip()
        s = _score_similarity(_normalize_company_name(name_val), q_norm)
        if s >= threshold:
            if return_scores:
                r["_match"] = {"score": s, "method": "python_fuzzy", "query": q_company}
            rescored.append((r, s))
    rescored.sort(key=lambda x: (-x[1], x[0].get(idc) if idc in (x[0].keys()) else 0))
    return [r for r, _ in rescored[:limit]]

# 간판 연계: company_id → bizno → (회사명+주소) 순
def _find_signboards_for_company(conn, dialect: str, company_row: dict, emd: str, limit: int = 100):
    s = COLMAP["signboards"]
    c = COLMAP["companies"]
    t_s = s["table"]
    sb_cols = set(_columns_of_table(conn, dialect, t_s))
    ph = _param_placeholder(dialect)

    # 1) FK(company_id)
    if s["company_id"] in sb_cols and c["id"] in company_row and company_row.get(c["id"]) is not None:
        cur = _cursor(conn, dialect, dict_cursor=True)
        try:
            cur.execute(f"SELECT * FROM {t_s} WHERE {s['company_id']} = {ph} LIMIT {limit}",
                        [company_row[c["id"]]])
            return [_row_to_dict(r) for r in cur.fetchall()]
        finally:
            cur.close()

    # 2) 사업자번호(bizno)
    if s["bizno"] in sb_cols and c["bizno"] in company_row and company_row.get(c["bizno"]):
        cur = _cursor(conn, dialect, dict_cursor=True)
        try:
            cur.execute(f"SELECT * FROM {t_s} WHERE {s['bizno']} = {ph} LIMIT {limit}",
                        [company_row[c["bizno"]]])
            return [_row_to_dict(r) for r in cur.fetchall()]
        finally:
            cur.close()

    # 3) 회사명+읍면동/주소 텍스트 매칭
    like_name = f"%{str(company_row.get(c['name'], '')).lower()}%"
    like_emd = f"%{emd.strip().lower()}%"
    cur = _cursor(conn, dialect, dict_cursor=True)
    try:
        cur.execute(f"""
            SELECT *
              FROM {t_s} s
             WHERE LOWER(COALESCE(s.{s['company_name']}, '')) LIKE {ph}
               AND (
                    LOWER(COALESCE(s.{s['emd']}, '')) LIKE {ph}
                 OR LOWER(COALESCE(s.{s['address']}, '')) LIKE {ph}
                   )
             LIMIT {limit}
        """, [like_name, like_emd, like_emd])
        return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        cur.close()

# ------------------------------------------------------------------------------
# [7] API 엔드포인트
# ------------------------------------------------------------------------------
@company_bp.get("/signboards")
def api_company_signboards():
    """
    GET /api/company/signboards?emd=학장동&company=레이어 와이즈
        &fuzzy=1&threshold=68&limit=5&sb_limit=20&return_scores=1
    - 회사는 t_b_cpn(또는 COMPANY_TABLE)에서 조회
    - 응답 company 객체에 주소/연락처/좌표 등 정규화 필드를 추가
    """
    emd = (request.args.get("emd") or "").strip()
    company = (request.args.get("company") or "").strip()
    topk = request.args.get("limit", type=int) or 10
    sbk = request.args.get("sb_limit", type=int) or 50

    fuzzy = _as_bool(request.args.get("fuzzy", "0"))
    return_scores = _as_bool(request.args.get("return_scores", "0"))
    threshold = request.args.get("threshold", type=float) or 70.0
    pool = request.args.get("pool", type=int) or 300

    if not emd or not company:
        return jsonify({"ok": False, "error": "필수 파라미터 누락: emd, company"}), 400

    try:
        conn, dialect = _get_connection()
    except Exception as e:
        return jsonify({"ok": False, "error": f"DB 연결 실패: {e}"}), 500

    try:
        companies = _find_companies(
            conn, dialect,
            emd=emd,
            company=company,
            limit=topk,
            fuzzy=fuzzy,
            threshold=threshold,
            pool=pool,
            return_scores=return_scores,
        )

        cm = COLMAP["companies"]
        results = []
        for comp in companies:
            # 주소/메타 정규화 추가
            view = _compose_address_view(cm, comp)

            signboards = _find_signboards_for_company(conn, dialect, comp, emd, limit=sbk)

            def _sanitize(d: dict):
                out = {}
                for k, v in d.items():
                    if hasattr(v, "isoformat"):
                        out[k] = v.isoformat()
                    else:
                        out[k] = v
                return out

            comp_aug = _sanitize(comp)
            comp_aug.update(view)  # 정규화 필드를 company 객체에 합침

            results.append({
                "company": comp_aug,
                "signboards": [_sanitize(s) for s in signboards],
                "signboard_count": len(signboards),
            })

        payload = {
            "ok": True,
            "query": {
                "emd": emd,
                "company": company,
                "fuzzy": fuzzy,
                "threshold": threshold,
                "pool": pool,
            },
            "count": len(results),
            "results": results,
        }
        try:
            current_app.config.setdefault("JSON_AS_ASCII", False)
        except Exception:
            pass

        return jsonify(payload), 200
    finally:
        try:
            conn.close()
        except Exception:
            pass
# ---[ NEW ]---------------------------------------------------------------
# /api/company/ : 읍면동 + 회사명으로 회사 ID 및 관련 정보 검색
@company_bp.get("/")
@company_bp.get("")  # /api/company (슬래시 없이)도 허용
def api_company_search():
    """
    예) GET /api/company/?emd=학장동&company=레이어 와 이 즈&fuzzy=1&return_scores=1
    파라미터:
      - emd (필수): 읍면동/행정동 문자열
      - company (필수): 회사/상호명
      - limit (기본 20), offset (기본 0)
      - fuzzy (0/1, 기본 1): 유사 검색 활성화(오타/띄어쓰기/㈜ 등 허용)
      - threshold (기본 70.0): fuzzy 임계 (0~100, 낮을수록 느슨)
      - pool (기본 300): fuzzy-python에서 후보 풀 크기
      - return_scores (0/1): 유사도/매칭 방법 표기
      - fields: 원본 컬럼명 콤마구분(예: fields=updated_at,create_dt) → 존재하면 함께 반환
      - raw (0/1): 원본 행 전체(_raw) 포함
    응답:
      company_id(값) + id_col(실제 ID 컬럼명) + 표준화 주소/연락처/좌표 등
    """
    from flask import request, jsonify, current_app

    emd = (request.args.get("emd") or "").strip()
    company = (request.args.get("company") or "").strip()
    limit = request.args.get("limit", type=int) or 20
    offset = request.args.get("offset", type=int) or 0

    fuzzy = _as_bool(request.args.get("fuzzy", "1"))
    threshold = request.args.get("threshold", type=float) or 70.0
    pool = request.args.get("pool", type=int) or 300
    return_scores = _as_bool(request.args.get("return_scores", "0"))
    fields_q = request.args.get("fields")  # "colA,colB"
    include_raw = _as_bool(request.args.get("raw", "0"))

    if not emd or not company:
        return jsonify({"ok": False, "error": "필수 파라미터 누락: emd, company"}), 400

    # DB 연결
    try:
        conn, dialect = _get_connection()
    except Exception as e:
        return jsonify({"ok": False, "error": f"DB 연결 실패: {e}"}), 500

    try:
        # 테이블/컬럼 매핑 자동 보정 (t_b_cpn 기준)
        _ensure_company_colmap(conn, dialect)
        cm = COLMAP["companies"]
        id_col = cm.get("id")
        name_col = cm.get("name")
        emd_col = cm.get("emd") or cm.get("dong")

        # offset 지원: (offset+limit) 만큼 받아 slice
        rows = _find_companies(
            conn, dialect,
            emd=emd, company=company,
            limit=offset + limit,
            fuzzy=fuzzy, threshold=threshold, pool=pool,
            return_scores=return_scores,
        )
        rows = rows[offset: offset + limit]

        # fields 쿼리 파싱
        extra_fields = []
        if fields_q:
            extra_fields = [f.strip() for f in fields_q.split(",") if f.strip()]

        results = []
        for r in rows:
            # 표준화된 주소/연락처/좌표 뷰 생성
            view = _compose_address_view(cm, r)

            item = {
                "company_id": r.get(id_col) if id_col else None,
                "id_col": id_col,                 # 실제 PK 컬럼명
                "name": r.get(name_col) if name_col else None,
                "name_col": name_col,             # 실제 이름 컬럼명(예: bizes_nm)
                "emd": r.get(emd_col) if emd_col else view.get("emd"),

                # 보기용 표준 필드
                "address_preferred": view.get("address_preferred"),
                "address_road": view.get("address_road"),
                "address_jibun": view.get("address_jibun"),
                "sido": view.get("sido"),
                "sigungu": view.get("sigungu"),
                "dong": view.get("dong"),
                "bizno": view.get("bizno"),
                "tel": view.get("tel"),
                "lat": view.get("lat"),
                "lon": view.get("lon"),
                "category": view.get("category"),
                "ceo": view.get("ceo"),
            }

            # 유사도/매칭 방법(옵션)
            if return_scores and r.get("_match"):
                item["_match"] = r["_match"]

            # 요청한 원본 컬럼 추가(존재할 때만)
            for f in extra_fields:
                item[f] = r.get(f)

            # 원본 행 전체(옵션)
            if include_raw:
                item["_raw"] = r

            results.append(item)

        payload = {
            "ok": True,
            "query": {
                "emd": emd, "company": company,
                "fuzzy": fuzzy, "threshold": threshold,
                "limit": limit, "offset": offset,
                "pool": pool,
                "fields": extra_fields or None,
            },
            "id_col": id_col,
            "name_col": name_col,
            "count": len(results),
            "results": results,
        }

        try:
            current_app.config.setdefault("JSON_AS_ASCII", False)
        except Exception:
            pass

        return jsonify(payload), 200
    finally:
        try:
            conn.close()
        except Exception:
            pass
# -------------------------------------------------------------------------
