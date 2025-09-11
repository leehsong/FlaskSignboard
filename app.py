# app.py — Merge(주소/회사 병합) + 불법/신고 검수 + 간판 상세/수정 + 이미지/행 관리
#          + 회사/간판 검수 로그(verify_db: MariaDB 호환) + (요약판) XLS 리뷰
import os, io, json, uuid, pathlib, configparser, urllib.parse
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, send_file, jsonify, session
from werkzeug.utils import secure_filename

import pandas as pd
import psycopg2, psycopg2.pool
import mysql.connector.pooling
import requests
from PIL import Image
import io as _io

MAX_W, MAX_H = 800, 600
# ======================
# 기본 설정
# ======================
UPLOAD_FOLDER = "./uploads"
ALLOWED_EXTENSIONS = {"xls", "xlsx", "xlsm"}
DATA_DIR = pathlib.Path("./uploads_data"); DATA_DIR.mkdir(parents=True, exist_ok=True)

KAKAO_KEY = os.getenv("KAKAO_KEY", "YOUR_KAKAO_KEY")
DB_INI    = os.getenv("DB_INI") or "db_config.ini"

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev-secret")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ======================
# 스키마 매핑 (회사: t_b_cpn / 간판: t_sb_info)
# ======================
META_TABLE = "public.t_b_cpn"
COL_ID     = "i_cpn"              # 회사 ID(업소ID)
COL_COMP   = "t_cpn"              # 회사명(업소명)
COL_COMP_FALLBACK = "i_cpn"       # 회사명이 없을 때 표시용 대체
COL_DONG   = "t_add_3"            # 읍/면/동
COL_BUNJI  = "t_add_num"          # 번지
COL_BUNJI2 = "t_add_2"            # 상세주소

SIGN_TABLE = "public.t_sb_info"
COL_ADIDX  = "i_info"             # 간판 PK
COL_CP_IDX = "i_cpn"              # FK → t_b_cpn.i_cpn
# 불법/신고 코드 컬럼
COL_SBF    = "i_sc_sbf"           # 신고/불법 구분 (SBF04/SBF06)
COL_SBD    = "i_sc_sbd"           # 간판 종류
COL_SBC    = "i_sc_sbc"     # 광고물종류  ← ✅ 추가/확인
# (선택) 허용 코드 목록
SBF_ALLOWED = {"SBF01","SBF02","SBF03","SBF04","SBF05","SBF06"}
# ======================
# DB 풀
# ======================
class MySQLPoolAdapter:
    def __init__(self, p): self._p = p
    def getconn(self):  return self._p.get_connection()
    def putconn(self, c): c.close()

def make_pool(section, ini=DB_INI):
    cfg = configparser.ConfigParser(inline_comment_prefixes=(';', '#'))
    read_files = cfg.read(ini, encoding="utf-8")
    if not read_files:
        raise RuntimeError(f"INI 파일을 찾지 못했습니다: {os.path.abspath(ini)}")
    if section not in cfg:
        raise RuntimeError(f"INI에 [{section}] 섹션이 없습니다. sections={cfg.sections()}")

    p = cfg[section]; drv = p.get("driver", "postgres").lower()
    if drv == "postgres":
        pool = psycopg2.pool.SimpleConnectionPool(
            1, int(p.get("pool_max", 10)),
            host=p["host"], port=p["port"], dbname=p["dbname"],
            user=p["user"], password=p["password"]
        )
    else:
        mp = mysql.connector.pooling.MySQLConnectionPool(
            pool_name=f"{section}_pool", pool_size=int(p.get("pool_max", 10)),
            host=p["host"], port=int(p["port"]), database=p["dbname"],
            user=p["user"], password=p["password"], autocommit=True
        )
        pool = MySQLPoolAdapter(mp)

    # 연결 테스트
    c = pool.getconn()
    if hasattr(c, "cursor"): c.cursor().close()
    pool.putconn(c)
    return pool

IMG_POOL = make_pool("image_db")     # 회사/간판/이미지
VER_POOL = make_pool("verify_db")    # 로그/검수(마리아DB)
try: META_POOL = make_pool("meta_db")
except Exception: META_POOL = IMG_POOL

# ======================
# DB 헬퍼
# ======================
def db_select_all(sql, params=(), use=None):
    use = use or META_POOL
    c = use.getconn()
    try:
        cur = c.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return rows
    finally: use.putconn(c)

def db_execute(sql, params=(), use=None):
    use = use or META_POOL
    c = use.getconn()
    try:
        cur = c.cursor()
        cur.execute(sql, params)
        if hasattr(c, "commit"): c.commit()
        cur.close()
    finally: use.putconn(c)

# ======================
# 유틸
# ======================
def allowed_file(fn): return "." in fn and fn.rsplit(".",1)[1].lower() in ALLOWED_EXTENSIONS

def geocode_kakao(addr: str):
    if not KAKAO_KEY: return None, None
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_KEY}"}
    r = requests.get(url, params={"query": addr}, headers=headers, timeout=5)
    if r.status_code != 200: return None, None
    docs = r.json().get("documents", [])
    if not docs: return None, None
    return float(docs[0]["x"]), float(docs[0]["y"])

# ======================
# 진단(디버그)
# ======================
@app.route("/diag")
def diag():
    try:
        cnt = db_select_all(f"SELECT COUNT(*) FROM {META_TABLE}")[0][0]
    except Exception as e:
        cnt = f"ERR: {e}"
    return jsonify({
        "config": {
            "META_TABLE": META_TABLE, "SIGN_TABLE": SIGN_TABLE,
            "COL_ID": COL_ID, "COL_COMP": COL_COMP, "COL_COMP_FALLBACK": COL_COMP_FALLBACK,
            "COL_DONG": COL_DONG, "COL_BUNJI": COL_BUNJI, "COL_BUNJI2": COL_BUNJI2,
            "COL_ADIDX": COL_ADIDX, "COL_CP_IDX": COL_CP_IDX, "COL_SBF": COL_SBF, "COL_SBD": COL_SBD
        },
        "meta_rows_count": cnt
    })

# ======================
# 시작/홈
# ======================
@app.route("/")
def root():
    if "reviewer_name" not in session: return redirect(url_for("start"))
    return redirect(url_for("home"))

@app.route("/start", methods=["GET","POST"])
def start():
    if request.method=="POST":
        nm=(request.form.get("reviewer") or "").strip()
        if not nm: return render_template("start.html", error="검수자 이름 필요")
        session.clear(); session["reviewer_name"]=nm
        return redirect(url_for("home"))
    return render_template("start.html")

@app.route("/home")
def home():
    if "reviewer_name" not in session: return redirect(url_for("start"))
    return render_template("home.html", reviewer=session["reviewer_name"])

# --- Admin (미니멀: 링크 깨짐 방지용) ---
@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method == "POST":
        admin = (request.form.get("admin_id") or "").strip()
        if not admin:
            return render_template("admin_login.html", error="관리자 ID를 입력하세요.")
        session["admin_user"] = admin
        return redirect(url_for("admin_panel"))
    return render_template("admin_login.html")

@app.route("/admin")
def admin_panel():  # <-- home.html에서 url_for('admin_panel')로 들어옵니다
    if "admin_user" not in session:
        return redirect(url_for("admin_login"))
    # 간단한 패널/플레이스홀더
    return render_template("admin.html", admin=session["admin_user"])


# ======================
# 회사 주소 합치기(요약: 동/번지/회사/이미지)
# ======================
@app.route("/merge")
def merge_page():
    return render_template("merge.html", reviewer=session.get("reviewer_name",""))

@app.route("/api/dongs")
def api_dongs():
    sql=f"SELECT DISTINCT {COL_DONG} FROM {META_TABLE} WHERE {COL_DONG} IS NOT NULL AND {COL_DONG}<>'' ORDER BY {COL_DONG}"
    rows=db_select_all(sql)
    return jsonify({"dongs":[r[0] for r in rows]})

@app.route("/api/bunji")
def api_bunji():
    dong=(request.args.get("dong") or "").strip()
    if not dong: return jsonify({"bunji":[]})
    sql=f"SELECT DISTINCT {COL_BUNJI} FROM {META_TABLE} WHERE {COL_DONG}=%s AND {COL_BUNJI} IS NOT NULL AND {COL_BUNJI}<>'' ORDER BY {COL_BUNJI}"
    rows=db_select_all(sql,(dong,))
    return jsonify({"bunji":[r[0] for r in rows]})

@app.route("/api/companies")
def api_companies():
    dong  = (request.args.get("dong")  or "").strip()
    bunji = (request.args.get("bunji") or "").strip()
    if not dong or not bunji: return jsonify({"companies":[]})
    sql = f"""
        SELECT
            c.{COL_ID} AS cidx,
            COALESCE(c.{COL_COMP}, c.{COL_COMP_FALLBACK}) AS company_name,
            COALESCE(c.{COL_BUNJI2}, '') AS addr2,
            COUNT(s.{COL_ADIDX}) AS ad_count
        FROM {META_TABLE} c
        LEFT JOIN {SIGN_TABLE} s
               ON s.{COL_CP_IDX} = c.{COL_ID}
        WHERE c.{COL_DONG}=%s AND c.{COL_BUNJI}=%s
        GROUP BY
            c.{COL_ID},
            COALESCE(c.{COL_COMP}, c.{COL_COMP_FALLBACK}),
            COALESCE(c.{COL_BUNJI2}, '')
        ORDER BY 2, 1
    """
    rows = db_select_all(sql, (dong, bunji))
    data=[{"cidx": r[0], "company_name": r[1], "addr2": r[2], "ad_count": int(r[3])} for r in rows]
    return jsonify({"companies": data})

@app.route("/api/company/update", methods=["POST"])
def api_company_update():
    data   = request.get_json(force=True, silent=True) or {}
    i_cpn  = (data.get("i_cpn") or "").strip()
    fields = data.get("fields") or {}
    if not i_cpn or not isinstance(fields, dict) or not fields:
        return jsonify({"ok": False, "msg":"invalid payload"}), 400

    allowed = ["t_cpn","t_add_3","t_add_num","t_add_2","t_tel","t_road"]  # t_road 추가
    sets = []; params = []
    for k in allowed:
        if k in fields and fields[k] is not None:
            # 컬럼 존재 검사 (옵션 필드: t_tel, t_road)
            if k in ("t_tel","t_road"):
                try: db_select_all(f"SELECT {k} FROM {META_TABLE} LIMIT 1", (), use=META_POOL)
                except Exception: continue  # 없으면 무시
            sets.append(f"{k}=%s"); params.append(fields[k])

    if not sets:
        return jsonify({"ok": False, "msg":"no updatable fields"}), 400

    sql = f"UPDATE {META_TABLE} SET {', '.join(sets)} WHERE {COL_ID}=%s"
    params.append(i_cpn)
    try:
        db_execute(sql, params, use=META_POOL)
        return jsonify({"ok": True})
    except Exception as e:
        print("[/api/company/update] ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route("/api/company/delete", methods=["POST"])
def api_company_delete():
    """
    payload: { "i_cpn":"...", "force": false }
    - 해당 회사의 간판이 존재하면 기본적으로 삭제 거부
    - force=true일 때 간판도 함께 삭제(신중히!)
    """
    data  = request.get_json(force=True, silent=True) or {}
    i_cpn = (data.get("i_cpn") or "").strip()
    force = bool(data.get("force", False))
    if not i_cpn:
        return jsonify({"ok": False, "msg":"i_cpn required"}), 400

    try:
        # 간판 존재 여부
        rows = db_select_all(f"SELECT COUNT(*) FROM {SIGN_TABLE} WHERE {COL_CP_IDX}=%s", (i_cpn,), use=IMG_POOL)
        cnt  = int(rows[0][0])
        if cnt > 0 and not force:
            return jsonify({"ok": False, "msg": f"간판 {cnt}건이 연결되어 있어 삭제 불가(강제 삭제 허용 시 force=true)"}), 400

        if cnt > 0 and force:
            db_execute(f"DELETE FROM {SIGN_TABLE} WHERE {COL_CP_IDX}=%s", (i_cpn,), use=IMG_POOL)

        # 회사 삭제
        db_execute(f"DELETE FROM {META_TABLE} WHERE {COL_ID}=%s", (i_cpn,), use=META_POOL)
        return jsonify({"ok": True})
    except Exception as e:
        print("[/api/company/delete] ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500


@app.route("/api/company_signs")
def api_company_signs():
    cidx_list = [x.strip() for x in request.args.getlist("cidx") if x.strip()]
    if not cidx_list: return jsonify({"images": []})
    placeholders = ",".join(["%s"] * len(cidx_list))
    sql = f"""
        SELECT {COL_ADIDX}
        FROM {SIGN_TABLE}
        WHERE {COL_CP_IDX} IN ({placeholders})
        ORDER BY {COL_ADIDX}
    """
    rows = db_select_all(sql, cidx_list)
    ids  = [str(r[0]) for r in rows]
    urls = [url_for("api_image_blob", ad_id=i) for i in ids]
    return jsonify({"images": urls})

@app.route("/api/company/signs_all")
def api_company_signs_all():
    i_cpn = (request.args.get("i_cpn") or "").strip()
    if not i_cpn:
        return jsonify({"ok": False, "msg": "i_cpn required"}), 400
    try:
        sql = f"""
          SELECT {COL_ADIDX} AS i_info,
                 {COL_SBF}   AS i_sc_sbf,
                 {COL_SBD}   AS i_sc_sbd,      -- ✅ 조명종류1
                 {COL_SBC}   AS i_sc_sbc,      -- ✅ 광고물종류
                 q_l, q_s, q_w,
                 q_img_h, q_img_w
            FROM {SIGN_TABLE}
           WHERE {COL_CP_IDX}=%s
           ORDER BY {COL_ADIDX}
        """
        rows = db_select_all(sql, (i_cpn,), use=IMG_POOL)
        signs = []
        for r in rows:
            i_info, i_sbf, i_sbd, i_sbc, ql, qs, qw, qh, qw2 = r
            signs.append({
                "i_info": str(i_info),
                "i_sc_sbf": i_sbf,
                "i_sc_sbd": i_sbd,    # ✅ 포함
                "i_sc_sbc": i_sbc,    # ✅ 포함
                "q_l": ql, "q_s": qs, "q_w": qw,
                "q_img_h": qh, "q_img_w": qw2,
                "thumb": url_for("api_image_blob", ad_id=str(i_info))
            })
        return jsonify({"ok": True, "signs": signs})
    except Exception as e:
        print("[/api/company/signs_all] ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500


# 회사명 병합 + 간판 FK(i_cpn) 대표ID로 통일
@app.route("/api/merge_companies", methods=["POST"])
def api_merge_companies():
    """
    payload (신규 권장):
      {
        "selected_ids": ["A001","A007","A015"],  # i_cpn 목록 (2개 이상 필수)
        "canonical_name": "대표상호"              # 병합 후 회사명
      }
    호환(구버전):
      {
        "dong": "...", "bunji": "...",
        "selected_names": ["(주)A","A주식회사"], "canonical_name": "A"
      }

    동작:
      - 대표 회사ID(canonical_id)는 selected_ids 중 '최솟값'으로 선택 (다르게 정하고 싶으면 향후 canonical_id 필드 추가)
      - META_TABLE의 선택된 회사ID들 이름을 canonical_name으로 변경
      - SIGN_TABLE의 FK(i_cpn)를 대표 회사ID로 통일
    """
    data = request.get_json(force=True, silent=True) or {}
    canonical = (data.get("canonical_name") or "").strip()
    selected_ids = data.get("selected_ids") or []   # 신 버전

    if selected_ids:
        # --- ID 기반 병합 (동/번지/이름 상관없이 확실함)
        ids = [str(x).strip() for x in selected_ids if str(x).strip()]
        ids = list(dict.fromkeys(ids))  # 중복 제거, 순서 유지
        if len(ids) < 2 or not canonical:
            return jsonify({"ok": False, "msg": "selected_ids(2+)와 canonical_name이 필요합니다."}), 400

        try:
            # 1) 대표 회사ID: 최솟값(문자열 기준 -> 필요시 숫자형 비교로 변경)
            canonical_id = min(ids)

            # 2) 회사명 일괄 변경 (선택된 ID들만)
            ph = ",".join(["%s"] * len(ids))
            sql_upd_name = f"UPDATE {META_TABLE} SET {COL_COMP}=%s WHERE {COL_ID} IN ({ph})"
            db_execute(sql_upd_name, [canonical] + ids, use=META_POOL)

            # 3) 간판 FK 통일 (대표ID 제외)
            target_ids = [x for x in ids if x != canonical_id]
            if target_ids:
                ph2 = ",".join(["%s"] * len(target_ids))
                sql_upd_fk = f"UPDATE {SIGN_TABLE} SET {COL_CP_IDX}=%s WHERE {COL_CP_IDX} IN ({ph2})"
                db_execute(sql_upd_fk, [canonical_id] + target_ids, use=IMG_POOL)

            return jsonify({"ok": True, "canonical_id": canonical_id, "merged_ids": target_ids})
        except Exception as e:
            print("[/api/merge_companies] ID-based merge ERROR:", e)
            return jsonify({"ok": False, "msg": str(e)}), 500

    # --- 이하 구버전(이름 기반) 하위호환: 가능하면 selected_ids 사용으로 전환 권장 ---
    dong  = (data.get("dong") or "").strip()
    bunji = (data.get("bunji") or "").strip()
    names = [s.strip() for s in (data.get("selected_names") or []) if s.strip()]
    if not dong or not bunji or len(names) < 1 or not canonical:
        return jsonify({"ok": False, "msg": "신규 selected_ids 사용 또는 dong/bunji/selected_names/canonical_name 필요"}), 400
    try:
        # 대표ID는 canonical_name을 가진 첫 레코드
        rows = db_select_all(
            f"SELECT {COL_ID} FROM {META_TABLE} WHERE {COL_DONG}=%s AND {COL_BUNJI}=%s AND {COL_COMP}=%s LIMIT 1",
            (dong, bunji, canonical), use=META_POOL)
        if not rows:
            # canonical_name을 가진 레코드가 없으면 이름기반 병합의 기준을 잡기 어려움 -> names들의 첫 ID를 대표로
            ph = ",".join(["%s"] * len(names))
            rows_any = db_select_all(
                f"SELECT {COL_ID} FROM {META_TABLE} WHERE {COL_DONG}=%s AND {COL_BUNJI}=%s AND {COL_COMP} IN ({ph}) ORDER BY {COL_ID} LIMIT 1",
                [dong, bunji] + names, use=META_POOL)
            if not rows_any:
                return jsonify({"ok": False, "msg": "병합 대상 회사를 찾지 못했습니다."}), 404
            canonical_id = str(rows_any[0][0])
        else:
            canonical_id = str(rows[0][0])

        # 대상 ID들 수집 (동/번지/이름 조건)
        ph2 = ",".join(["%s"] * len(names))
        rows_ids = db_select_all(
            f"SELECT {COL_ID} FROM {META_TABLE} WHERE {COL_DONG}=%s AND {COL_BUNJI}=%s AND {COL_COMP} IN ({ph2})",
            [dong, bunji] + names, use=META_POOL)
        ids = [str(r[0]) for r in rows_ids]
        target_ids = [x for x in ids if x != canonical_id]

        # 이름 변경
        db_execute(
            f"UPDATE {META_TABLE} SET {COL_COMP}=%s WHERE {COL_ID} IN ({','.join(['%s']*len(ids))})",
            [canonical] + ids, use=META_POOL)

        # FK 통일
        if target_ids:
            db_execute(
                f"UPDATE {SIGN_TABLE} SET {COL_CP_IDX}=%s WHERE {COL_CP_IDX} IN ({','.join(['%s']*len(target_ids))})",
                [canonical_id] + target_ids, use=IMG_POOL)

        return jsonify({"ok": True, "canonical_id": canonical_id, "merged_ids": target_ids})
    except Exception as e:
        print("[/api/merge_companies] name-based merge ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500


# 회사 상세 (주소) → 네이버 지도용
@app.route("/api/company/detail")
def api_company_detail():
    i_cpn = (request.args.get("i_cpn") or "").strip()
    if not i_cpn:
        return jsonify({"ok": False, "msg": "i_cpn required"}), 400
    try:
        # t_road 컬럼 존재 여부 체크 후 동적 SELECT
        have_road = True
        try:
            db_select_all(f"SELECT t_road FROM {META_TABLE} LIMIT 1", (), use=META_POOL)
        except Exception:
            have_road = False

        cols = f"{COL_COMP} AS company_name, {COL_DONG} AS dong, {COL_BUNJI} AS bunji, {COL_BUNJI2} AS bunji2"
        if have_road:
            cols += ", t_road"

        rows = db_select_all(f"SELECT {cols} FROM {META_TABLE} WHERE {COL_ID}=%s LIMIT 1", (i_cpn,), use=META_POOL)
        if not rows: return jsonify({"ok": False, "msg":"not found"}), 404

        # dict 변환
        desc = ["company_name","dong","bunji","bunji2"] + (["t_road"] if have_road else [])
        data = dict(zip(desc, rows[0]))
        return jsonify({"ok": True, **data})
    except Exception as e:
        print("[/api/company/detail] ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500

from urllib.parse import quote_plus

@app.route("/api/company/roadview_url")
def api_company_roadview_url():
    """
    /api/company/roadview_url?i_cpn=...
    1) company_info(META_TABLE)에서 도로명 주소(t_add_road)를 우선 조회
       - 없으면 동/번지/상세(COL_DONG, COL_BUNJI, COL_BUNJI2) 조합
    2) Kakao 지오코딩 → (lng, lat) 얻으면 네이버 v5 로드뷰 URL 반환
       - 좌표 실패 시 네이버 검색 URL로 폴백
    response: { ok, url, addr, lng, lat }
    """
    i_cpn = (request.args.get("i_cpn") or "").strip()
    if not i_cpn:
        return jsonify({"ok": False, "msg": "i_cpn required"}), 400

    # 1) t_add_road 존재 여부 감지
    have_road = True
    try:
        # 컬럼 존재 테스트 (스키마/권한 이슈 대비)
        db_select_all(f"SELECT t_add_road FROM {META_TABLE} LIMIT 1", (), use=META_POOL)
    except Exception:
        have_road = False

    # 2) 회사 주소 로드
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

    # 3) 주소 문자열 결정 (도로명 우선)
    parts = []
    if road:
        parts.append(str(road).strip())
    # 도로명이 아주 짧거나 부정확한 경우 보조로 동/번지/상세를 덧붙여도 됨
    # 필요 시 아래 주석 해제
    # parts += [x for x in [dong, bunji, bunji2] if x]

    if not parts:
        parts = [x for x in [dong, bunji, bunji2] if x]

    addr = " ".join(map(lambda x: str(x).strip(), parts)).strip()
    if not addr:
        return jsonify({"ok": False, "msg": "empty address"}), 400

    # 4) 지오코딩 → 네이버 로드뷰 URL 생성
    try:
        lng, lat = geocode_kakao(addr)  # (lng, lat) 문자열/숫자 모두 허용
    except Exception as e:
        print("[/api/company/roadview_url] geocode ERROR:", e)
        lng, lat = None, None

    if lng and lat:
        url = f"https://map.naver.com/v5/roadview/{lng},{lat}?layers=roadview"
        return jsonify({"ok": True, "url": url, "addr": addr, "lng": float(lng), "lat": float(lat)})
    else:
        # 좌표 못 찾으면 검색 URL로 폴백
        url = f"https://map.naver.com/v5/search/{quote_plus(addr)}"
        return jsonify({"ok": True, "url": url, "addr": addr, "lng": None, "lat": None})


# ======================
# 불법/신고 간판 (SBF04/SBF06)
# ======================
@app.route("/illegal")
def illegal_page():
    return render_template("illegal.html", reviewer=session.get("reviewer_name",""))

@app.route("/api/illegal/dongs")
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

@app.route("/api/illegal/companies")
def api_illegal_companies():
    dong = (request.args.get("dong") or "").strip()
    if not dong: return jsonify({"companies":[]})
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

@app.route("/api/illegal/signs")
def api_illegal_signs():
    i_cpn = (request.args.get("i_cpn") or "").strip()
    if not i_cpn: return jsonify({"signs":[]})
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
        i_info, sc_sbf, sc_sbd, qh, qw, qwt, qst = r
        signs.append({
            "i_info": str(i_info),
            "thumb": url_for("api_image_blob", ad_id=str(i_info)),
            "sc_sbf": sc_sbf, "sc_sbd": sc_sbd, "sc_sbc": sbc,
            "q_img_h": qh, "q_img_w": qw, "q_w_test": qwt, "q_s_temp": qst
        })
    return jsonify({"signs": signs})

# ======================
# 간판 상세/수정/이미지/행 관리
# ======================
@app.route("/api/sign_detail/<ad_id>")
def api_sign_detail(ad_id):
    sql = f"""
      SELECT s.*, c.{COL_COMP} AS company_name
        FROM {SIGN_TABLE} s
   LEFT JOIN {META_TABLE} c ON c.{COL_ID} = s.{COL_CP_IDX}
       WHERE s.{COL_ADIDX} = %s
      LIMIT 1
    """
    try:
        c = IMG_POOL.getconn(); cur = c.cursor()
        cur.execute(sql, (ad_id,))
        row = cur.fetchone(); desc = [d[0] for d in cur.description]
        cur.close(); IMG_POOL.putconn(c)
        if not row: return jsonify({"ok": False, "msg": "not found"}), 404
        data = {k: v for k, v in zip(desc, row)}
        if "b_img" in data: data.pop("b_img")
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        print("[/api/sign_detail] ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500

# 선택 필드 업데이트(화이트리스트)
@app.route("/api/sign_update", methods=["POST"])
def api_sign_update():
    data = request.get_json(force=True, silent=True) or {}
    i_info = (data.get("i_info") or "").strip()
    fields = data.get("fields") or {}
    if not i_info or not isinstance(fields, dict) or not fields:
        return jsonify({"ok": False, "msg":"invalid payload"}), 400
    allowed = {"sc_sbd","sc_sbc", "q_img_h", "q_img_w", "q_w_test", "q_s_temp"}
    updates=[]; params=[]
    # 매핑: 입력 키 → 실제 컬럼
    colmap={"sc_sbd":COL_SBD, "sc_sbc": COL_SBC, "q_img_h":"q_img_h", "q_img_w":"q_img_w", "q_w_test":"q_w_test", "q_s_temp":"q_s_temp"}
    for k,v in fields.items():
        if k in allowed:
            updates.append(f"{colmap[k]}=%s")
            params.append(v)
    if not updates: return jsonify({"ok": False, "msg":"no updatable fields"}), 400
    sql = f"UPDATE {SIGN_TABLE} SET {', '.join(updates)} WHERE {COL_ADIDX}=%s"
    params.append(i_info)
    try:
        db_execute(sql, params, use=IMG_POOL)
        return jsonify({"ok": True})
    except Exception as e:
        print("[/api/sign_update] ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route("/api/sign_update_sbf", methods=["POST"])
def api_sign_update_sbf():
    """
    payload: { "i_info": "...", "i_sc_sbf": "SBF04" }
    효과: t_sb_info.i_sc_sbf 업데이트 (+ 선택: 리뷰로그)
    """
    data = request.get_json(force=True, silent=True) or {}
    i_info  = (data.get("i_info")  or "").strip()
    i_sc_sbf= (data.get("i_sc_sbf") or "").strip().upper()

    if not i_info or not i_sc_sbf:
        return jsonify({"ok": False, "msg": "i_info and i_sc_sbf required"}), 400
    # (선택) 허용 코드 체크
    if 'SBF_ALLOWED' in globals():
        if i_sc_sbf not in SBF_ALLOWED:
            return jsonify({"ok": False, "msg": f"invalid i_sc_sbf: {i_sc_sbf}"}), 400

    try:
        # 1) 업데이트
        sql = f"UPDATE {SIGN_TABLE} SET {COL_SBF}=%s WHERE {COL_ADIDX}=%s"
        db_execute(sql, (i_sc_sbf, i_info), use=IMG_POOL)

        # 2) (선택) 리뷰 로그를 남기고 싶으면 아래 주석 해제
        try:
            reviewer = session.get("reviewer_name", "web-user")
            db_execute(
                "INSERT INTO T_X_REVIEW_LOG (i_info, i_cpn, `action`, comment, reviewer, created_at) VALUES (%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)",
                (i_info, None, "update_sbf", f"i_sc_sbf -> {i_sc_sbf}", reviewer),
                use=VER_POOL
            )
        except Exception as e_log:
            print("[/api/sign_update_sbf] log warn:", e_log)

        return jsonify({"ok": True})
    except Exception as e:
        print("[/api/sign_update_sbf] ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500


# 간판 행 삭제(이미지 BLOB은 유지)
@app.route("/api/sign/delete", methods=["POST"])
def api_sign_delete():
    data = request.get_json(force=True, silent=True) or {}
    i_info = (data.get("i_info") or "").strip()
    if not i_info: return jsonify({"ok": False, "msg":"i_info required"}), 400
    try:
        db_execute(f"DELETE FROM {SIGN_TABLE} WHERE {COL_ADIDX}=%s", (i_info,), use=IMG_POOL)
        return jsonify({"ok": True, "deleted": i_info})
    except Exception as e:
        print("[/api/sign/delete] ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500

# 더미 간판 생성(q_img_h/q_img_w=0)
@app.route("/api/sign/create_dummy", methods=["POST"])
def api_sign_create_dummy():
    data = request.get_json(force=True, silent=True) or {}
    i_cpn = (data.get("i_cpn") or "").strip()
    if not i_cpn:
        return jsonify({"ok": False, "msg": "i_cpn required"}), 400

    try:
        # 1) 새 PK 계산 (MAX+1) — 테이블 전역 기준
        rows = db_select_all(
            f"SELECT COALESCE(MAX({COL_ADIDX})::bigint, 0) + 1 FROM {SIGN_TABLE}",
            (), use=IMG_POOL
        )
        new_id = int(rows[0][0])

        # 2) 명시적 PK로 INSERT
        db_execute(
            f"INSERT INTO {SIGN_TABLE} ({COL_ADIDX}, {COL_CP_IDX}, q_img_h, q_img_w) VALUES (%s, %s, 0, 0)",
            (new_id, i_cpn), use=IMG_POOL
        )

        return jsonify({"ok": True, "i_cpn": i_cpn, "i_info": str(new_id)})
    except Exception as e:
        print("[/api/sign/create_dummy] ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500

# 이미지 스트리밍 (i_img=p_if_pk_{i_info})
@app.route("/api/image_blob/<ad_id>")
def api_image_blob(ad_id):
    iimg=f"p_if_pk_{ad_id}"
    c=IMG_POOL.getconn()
    try:
        cur=c.cursor()
        cur.execute("SELECT b_img FROM T_X_IMG WHERE i_img=%s",(iimg,))
        row=cur.fetchone(); cur.close()
        if row and row[0]:
            blob=row[0]
            if isinstance(blob, memoryview): blob=bytes(blob)
            return send_file(io.BytesIO(blob), mimetype="image/jpeg")
        return "이미지 없음",404
    finally: IMG_POOL.putconn(c)

# ======================
# 검수 로그 (verify_db: MariaDB 호환)
# ======================
@app.route("/api/review/log", methods=["POST"])
def api_review_log():
    """
    payload:
      - 간판 단위:  { "i_info":"12345", "action":"inspect", "comment":"..." }
      - 회사 단위:  { "i_cpn":"ACME01", "action":"company_review", "comment":"..." }
    """
    data = request.get_json(force=True, silent=True) or {}
    i_info   = (data.get("i_info") or "").strip() or None
    i_cpn    = (data.get("i_cpn")  or "").strip() or None
    action   = (data.get("action") or "").strip()
    comment  = (data.get("comment") or "").strip() or None
    reviewer = (data.get("reviewer") or "").strip() or session.get("reviewer_name","web-user")
    if not i_info and not i_cpn:
        return jsonify({"ok": False, "msg": "i_info 또는 i_cpn 중 하나는 필수입니다."}), 400
    if not action:
        action = "inspect" if i_info else "company_review"
    sql = """
      INSERT INTO T_X_REVIEW_LOG (i_info, i_cpn, `action`, comment, reviewer, created_at)
      VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
    """
    try:
        db_execute(sql, (i_info, i_cpn, action, comment, reviewer), use=VER_POOL)
        return jsonify({"ok": True})
    except Exception as e:
        print("[/api/review/log] ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route("/api/review/by_sign/<i_info>")
def api_review_by_sign(i_info):
    sql = """
      SELECT id,i_info,i_cpn,`action`,comment,reviewer,created_at
        FROM T_X_REVIEW_LOG
       WHERE i_info=%s
       ORDER BY created_at DESC
       LIMIT 200
    """
    try:
        rows = db_select_all(sql, (i_info,), use=VER_POOL)
        items = [{
            "id":r[0], "i_info":r[1], "i_cpn":r[2], "action":r[3],
            "comment":r[4], "reviewer":r[5],
            "created_at": r[6].isoformat() if r[6] else None
        } for r in rows]
        return jsonify({"ok": True, "items": items})
    except Exception as e:
        print("[/api/review/by_sign] ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route("/api/review/by_company/<i_cpn>")
def api_review_by_company(i_cpn):
    sql = """
      SELECT id,i_info,i_cpn,`action`,comment,reviewer,created_at
        FROM T_X_REVIEW_LOG
       WHERE i_cpn=%s
       ORDER BY created_at DESC
       LIMIT 500
    """
    try:
        rows = db_select_all(sql, (i_cpn,), use=VER_POOL)
        items = [{
            "id":r[0], "i_info":r[1], "i_cpn":r[2], "action":r[3],
            "comment":r[4], "reviewer":r[5],
            "created_at": r[6].isoformat() if r[6] else None
        } for r in rows]
        return jsonify({"ok": True, "items": items})
    except Exception as e:
        print("[/api/review/by_company] ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500

# ======================
# (요약) XLS 업로드 리뷰(선택)
# ======================
@app.route("/upload", methods=["GET","POST"])
def upload_index():
    if "reviewer_name" not in session: return redirect(url_for("start"))
    if request.method=="POST":
        f=request.files.get("excel")
        if not f or f.filename=="": return render_template("index.html", error="엑셀 파일을 선택하세요.", reviewer=session["reviewer_name"])
        if not allowed_file(f.filename): return render_template("index.html", error="허용되지 않는 파일 형식입니다.", reviewer=session["reviewer_name"])
        path=os.path.join(UPLOAD_FOLDER, secure_filename(f.filename)); f.save(path)
        try: df=pd.read_excel(path)
        except Exception as e: return render_template("index.html", error=f"엑셀 읽기 오류: {e}", reviewer=session["reviewer_name"])
        base_cols=[COL_ADIDX, COL_COMP, COL_DONG, COL_BUNJI]
        for c in base_cols:
            if c not in df.columns: df[c]=""
        view_cols=base_cols+["ad_specification","ad_height","ad_type"]
        for c in view_cols:
            if c not in df.columns: df[c]=""
        rows_df=df[view_cols].fillna("")
        addr_full=df.get(COL_BUNJI2, pd.Series([""]*len(df))).fillna("").tolist()
        upload_id=uuid.uuid4().hex
        _save_session_data(upload_id, rows_df.to_dict("records"), addr_full, session["reviewer_name"])
        session["upload_id"]=upload_id; session["cursor"]=0
        return redirect(url_for("review"))
    return render_template("index.html", reviewer=session["reviewer_name"])

@app.route("/api/sign_image/replace", methods=["POST"])
def api_sign_image_replace():
    """
    multipart/form-data:
      - i_info: 간판 PK (필수)
      - image : 파일 (필수)
    동작:
      1) 원본 width/height 추출 → t_sb_info.q_img_w/q_img_h 업데이트
      2) 원본이 너무 큰 경우 800x600 이하로 리사이즈(비율유지) → T_X_IMG에 업서트
    반환: {ok, orig_w, orig_h, stored_bytes}
    """
    i_info = (request.form.get("i_info") or "").strip()
    file = request.files.get("image")
    if not i_info or not file:
        return jsonify({"ok": False, "msg": "i_info and image are required"}), 400

    try:
        # 1) 이미지 열기
        img = Image.open(file.stream).convert("RGB")  # 일단 RGB로
        orig_w, orig_h = img.size

        # 2) 리사이즈(필요 시)
        img_to_store = img
        if orig_w > MAX_W or orig_h > MAX_H:
            img_to_store = img.copy()
            img_to_store.thumbnail((MAX_W, MAX_H), Image.LANCZOS)

        # 3) 바이트로 직렬화 (JPEG로 저장; 필요시 PNG로 바꿔도 됨)
        buf = _io.BytesIO()
        img_to_store.save(buf, format="JPEG", quality=92)
        data = buf.getvalue()

        # 4) T_X_IMG 업서트
        iimg = f"p_if_pk_{i_info}"
        try:
            # MariaDB/MySQL
            sql_my = "INSERT INTO T_X_IMG (i_img, b_img) VALUES (%s,%s) ON DUPLICATE KEY UPDATE b_img=VALUES(b_img)"
            db_execute(sql_my, (iimg, data), use=IMG_POOL)
        except Exception:
            # PostgreSQL
            sql_pg = "INSERT INTO T_X_IMG (i_img, b_img) VALUES (%s,%s) ON CONFLICT (i_img) DO UPDATE SET b_img=EXCLUDED.b_img"
            db_execute(sql_pg, (iimg, data), use=IMG_POOL)

        # 5) t_sb_info 원본 크기 업데이트 (원본 이미지의 w/h)
        sql_u = f"UPDATE {SIGN_TABLE} SET q_img_w=%s, q_img_h=%s WHERE {COL_ADIDX}=%s"
        db_execute(sql_u, (orig_w, orig_h, i_info), use=IMG_POOL)

        return jsonify({"ok": True, "orig_w": orig_w, "orig_h": orig_h, "stored_bytes": len(data)})
    except Exception as e:
        print("[/api/sign_image/replace] ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500

# ======================
# 검수 요약 페이지 렌더
# ======================
@app.route("/review-summary")
def review_summary_page():
    return render_template("summary.html", reviewer=session.get("reviewer_name",""))

# ======================
# 검수 요약 API (JSON)
# ======================
@app.route("/api/review/summary")
def api_review_summary():
    """
    query:
      from, to (YYYY-MM-DD)  -- 선택, 없으면 최근 30일
      dong                   -- 선택
      kind = all|inspect|company  (기본 all)
      limit                  -- 기본 1000
    output:
      rows: [{dong, addr, company_name, i_info, action, comment, reviewer, created_at}]
    내부동작:
      1) verify_db(T_X_REVIEW_LOG)에서 로그 조회
      2) 필요한 i_info -> SIGN_TABLE에서 i_cpn 확정
      3) i_cpn -> META_TABLE에서 주소/회사명 확보
    """
    import datetime as dt

    d_from = (request.args.get("from") or "").strip()
    d_to   = (request.args.get("to") or "").strip()
    dong_f = (request.args.get("dong") or "").strip()
    kind   = (request.args.get("kind") or "all").strip()  # all | inspect | company
    limit  = int(request.args.get("limit") or 1000)

    # 1) 로그 쿼리(verify_db)
    where = []
    params = []

    if d_from:
        where.append("created_at >= %s")
        params.append(d_from + " 00:00:00")
    else:
        # 기본: 최근 30일
        since = (dt.date.today() - dt.timedelta(days=30)).strftime("%Y-%m-%d")
        where.append("created_at >= %s")
        params.append(since + " 00:00:00")

    if d_to:
        where.append("created_at <= %s")
        params.append(d_to + " 23:59:59")

    if kind == "inspect":
        where.append("`action` = %s")
        params.append("inspect")
    elif kind == "company":
        where.append("`action` = %s")
        params.append("company_review")
    # else: all

    sql_log = "SELECT id,i_info,i_cpn,`action`,comment,reviewer,created_at FROM T_X_REVIEW_LOG"
    if where:
        sql_log += " WHERE " + " AND ".join(where)
    sql_log += " ORDER BY created_at DESC LIMIT %s"
    params2 = params + [limit]

    try:
        rows_log = db_select_all(sql_log, params2, use=VER_POOL)
    except Exception as e:
        print("[/api/review/summary] log query ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500

    # 2) i_info -> i_cpn 매핑 (image_db)
    i_infos = {r[1] for r in rows_log if r[1]}  # i_info
    map_info_to_cpn = {}
    if i_infos:
        # 배치 조회
        # i_info 타입이 문자열일 수 있으니 %s 반복
        ph = ",".join(["%s"] * len(i_infos))
        sql_s = f"SELECT {COL_ADIDX}, {COL_CP_IDX} FROM {SIGN_TABLE} WHERE {COL_ADIDX} IN ({ph})"
        try:
            rows_s = db_select_all(sql_s, list(i_infos), use=IMG_POOL)
            map_info_to_cpn = {str(a): str(b) for (a,b) in rows_s}
        except Exception as e:
            print("[/api/review/summary] sign map ERROR:", e)

    # 최종 i_cpn 확정
    items = []
    cpn_set = set()
    for rid, i_info, i_cpn, action, comment, reviewer, created_at in rows_log:
        cpn = (i_cpn or None)
        if not cpn and i_info:
            cpn = map_info_to_cpn.get(str(i_info))
        items.append({
            "i_info": str(i_info) if i_info else "",
            "i_cpn":  str(cpn) if cpn else "",
            "action": action or "",
            "comment": comment or "",
            "reviewer": reviewer or "",
            "created_at": created_at,
        })
        if cpn:
            cpn_set.add(str(cpn))

    # 3) i_cpn -> 회사/주소 (image_db)
    map_cpn_to_meta = {}
    if cpn_set:
        ph = ",".join(["%s"] * len(cpn_set))
        sql_c = f"""
          SELECT {COL_ID}, {COL_COMP}, {COL_DONG}, {COL_BUNJI}, {COL_BUNJI2}
            FROM {META_TABLE}
           WHERE {COL_ID} IN ({ph})
        """
        try:
            rows_c = db_select_all(sql_c, list(cpn_set), use=IMG_POOL)
            for i_cpn2, name, dong, bunji, bunji2 in rows_c:
                map_cpn_to_meta[str(i_cpn2)] = {
                    "company_name": name or "",
                    "dong": dong or "",
                    "bunji": bunji or "",
                    "bunji2": bunji2 or ""
                }
        except Exception as e:
            print("[/api/review/summary] company meta ERROR:", e)

    # 4) 행 구성 + 동 필터 적용(있다면)
    out_rows = []
    for it in items:
        meta = map_cpn_to_meta.get(it["i_cpn"], {"company_name":"","dong":"","bunji":"","bunji2":""})
        dong = meta["dong"]
        if dong_f and dong != dong_f:
            continue
        addr = " ".join(x for x in [meta["bunji"], meta["bunji2"]] if x).strip()
        out_rows.append({
            "dong": dong,
            "addr": addr,
            "company_name": meta["company_name"],
            "i_info": it["i_info"],
            "action": it["action"],
            "comment": it["comment"],
            "reviewer": it["reviewer"],
            "created_at": it["created_at"].strftime("%Y-%m-%d %H:%M:%S") if it["created_at"] else ""
        })

    return jsonify({"ok": True, "rows": out_rows})

# ======================
# 검수 요약 Excel 다운로드
# ======================
@app.route("/api/review/summary_export")
def api_review_summary_export():
    """
    동일한 파라미터로 엑셀(xlsx) 다운로드
    """
    from io import BytesIO
    import pandas as pd

    # 내부적으로 JSON API를 재사용
    with app.test_request_context():
        # 간단히 현재 request.args를 그대로 넘겨서 JSON 로직 호출
        pass

    # 직접 내부 함수 호출 대신 한번 더 로직을 재사용
    # 여기서는 코드 중복을 피하려고 api_review_summary를 직접 부르는 대신
    # 동일 로직을 간소하게 재작성합니다.
    # (프로덕션이면 함수로 분리해서 호출하세요)

    try:
        # /api/review/summary 로 한 번 호출해서 rows만 가져오기
        with app.test_request_context():
            # 이 trick 대신, 위의 로직을 함수로 분리해 호출하는 걸 권장합니다.
            pass
    except:
        pass

    # 간단히: 위의 api_review_summary 로직을 최소 재사용
    # -> 파라미터를 그대로 읽고 동일 로직을 수행
    # (코드 중복이지만, 이해하기 쉽게 별도 구현)
    resp = api_review_summary()
    if isinstance(resp, tuple):
        data, status = resp
        if status != 200:
            return resp
        data = data.get_json()
    else:
        data = resp.get_json()

    if not data.get("ok"):
        return jsonify(data), 500

    rows = data.get("rows", [])
    if not rows:
        # 빈 엑셀도 다운로드
        df = pd.DataFrame(columns=["동","세부주소","회사명","간판ID","작업종류","검수내용","작업자","일시"])
    else:
        df = pd.DataFrame(rows)
        df = df.rename(columns={
            "dong":"동","addr":"세부주소","company_name":"회사명","i_info":"간판ID",
            "action":"작업종류","comment":"검수내용","reviewer":"작업자","created_at":"일시"
        })

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="검수요약")
    buf.seek(0)

    filename = "review_summary.xlsx"
    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def _save_session_data(upload_id, rows, addr_full, reviewer):
    path=DATA_DIR / f"{upload_id}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump({"rows": rows, "addr_full": addr_full, "reviewer": reviewer}, f, ensure_ascii=False)

def _load_session_data():
    upload_id=session.get("upload_id"); 
    if not upload_id: return None
    path=DATA_DIR / f"{upload_id}.json"
    if not path.exists(): return None
    with path.open("r", encoding="utf-8") as f: return json.load(f)

@app.route("/review")
def review():
    if "upload_id" not in session: return redirect(url_for("upload_index"))
    return render_template("review.html", reviewer=session.get("reviewer_name"))

@app.route("/api/state")
def api_state():
    data=_load_session_data() or {"rows":[]}
    idx=int(session.get("cursor",0))
    return jsonify({"index":idx, "total":len(data["rows"])})

@app.route("/api/meta/<int:index>")
def api_meta(index):
    data=_load_session_data()
    if not data: return jsonify({"error":"no session data"}), 400
    rows, addr_full = data["rows"], data["addr_full"]
    if index<0 or index>=len(rows): return jsonify({"error":"index out of range"}), 400
    r=rows[index]
    name=r.get(COL_COMP) or r.get("company_name") or r.get("t_cpn") or r.get("i_cpn") or ""
    meta_html=(f"<b>{name}</b><br>"
               f"• 주소: {r.get(COL_DONG,'')} {r.get(COL_BUNJI,'')} "
               f"{(addr_full[index] if index<len(addr_full) else '')}<br>"
               f"• 규격: {r.get('ad_specification','')}<br>"
               f"• 높이: {r.get('ad_height','')}<br>"
               f"• 종류: {r.get('ad_type','')}")
    return jsonify({"id": str(r.get(COL_ADIDX,"")), "addr_full": addr_full[index] if index<len(addr_full) else "", "meta_html": meta_html})

@app.route("/api/image_by_iimg/<i_img>")
def api_image_by_iimg(i_img):
    blob=_fetch_image_blob(i_img)
    if blob: return send_file(io.BytesIO(blob), mimetype="image/jpeg")
    return "이미지 없음",404

def _fetch_image_blob(iimg:str):
    c=IMG_POOL.getconn()
    try:
        cur=c.cursor()
        cur.execute("SELECT b_img FROM T_X_IMG WHERE i_img=%s",(iimg,))
        row=cur.fetchone(); cur.close()
        if row and row[0]:
            blob=row[0]
            if isinstance(blob, memoryview): blob=bytes(blob)
            return blob
        return None
    finally: IMG_POOL.putconn(c)

# (A) 재촬영 요청 생성
@app.route("/api/recapture/request", methods=["POST"])
def api_recapture_request():
    """
    payload:
      {
        "i_cpn": "회사ID",           -- 필수
        "i_info": "간판ID",          -- 선택(신규 촬영은 생략 가능)
        "reason": "사유 메모",       -- 선택
        "img_note": "이미지 참고"    -- 선택(파일명/현장메모 등)
      }
    동작:
      verify_db.T_X_RECAPTURE_REQ 에 한 건을 INSERT
    """
    data = request.get_json(force=True, silent=True) or {}
    i_cpn   = (data.get("i_cpn") or "").strip()
    i_info  = (data.get("i_info") or "").strip() or None
    reason  = (data.get("reason") or "").strip() or None
    img_note= (data.get("img_note") or "").strip() or None
    requester = session.get("reviewer_name", "web-user")

    if not i_cpn:
        return jsonify({"ok": False, "msg": "i_cpn required"}), 400

    sql = """
      INSERT INTO T_X_RECAPTURE_REQ (i_cpn, i_info, requester, reason, img_note, status, created_at, updated_at)
      VALUES (%s, %s, %s, %s, %s, 'OPEN', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """
    try:
        db_execute(sql, (i_cpn, i_info, requester, reason, img_note), use=VER_POOL)
        return jsonify({"ok": True})
    except Exception as e:
        print("[/api/recapture/request] ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500

# (B) 재촬영 요청 조회(옵션) — 대시보드/필터링용
@app.route("/api/recapture/list")
def api_recapture_list():
    """
    예: /api/recapture/list?status=OPEN&from=2025-09-01&to=2025-09-10&i_cpn=...&requester=...
    """
    status    = (request.args.get("status") or "").strip()
    d_from    = (request.args.get("from") or "").strip()
    d_to      = (request.args.get("to") or "").strip()
    i_cpn     = (request.args.get("i_cpn") or "").strip()
    requester = (request.args.get("requester") or "").strip()

    where = []; params = []
    if status:
        where.append("status=%s"); params.append(status)
    if d_from:
        where.append("created_at >= %s"); params.append(d_from + " 00:00:00")
    if d_to:
        where.append("created_at <= %s"); params.append(d_to + " 23:59:59")
    if i_cpn:
        where.append("i_cpn=%s"); params.append(i_cpn)
    if requester:
        where.append("requester=%s"); params.append(requester)

    sql = "SELECT id,i_cpn,i_info,requester,reason,img_note,status,created_at,updated_at FROM T_X_RECAPTURE_REQ"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT 1000"

    try:
        rows = db_select_all(sql, params, use=VER_POOL)
        items = []
        for r in rows:
            rid, cpn, info, req, rea, note, st, ca, ua = r
            items.append({
                "id": rid, "i_cpn": cpn, "i_info": info,
                "requester": req, "reason": rea, "img_note": note,
                "status": st,
                "created_at": ca.isoformat() if ca else None,
                "updated_at": ua.isoformat() if ua else None
            })
        return jsonify({"ok": True, "items": items})
    except Exception as e:
        print("[/api/recapture/list] ERROR:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500


# ======================
# 템플릿 엔드포인트(필요한 것만)
# ======================
@app.route("/index")
def index_page(): return render_template("index.html", reviewer=session.get("reviewer_name",""))

# ======================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=26000, debug=True)
