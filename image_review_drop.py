"""
🖼️ Image Reviewer  (2025-06-28 통합판)
─────────────────────────────────────────────────────────────────
• 1920×1080 레이아웃 ─ DB 이미지 800×600 ┃ Drag&Drop 존 800×600 ┃ 메타 300px
• Drag & Drop  +  Ctrl+V 붙여넣기
   ├─ 로컬 파일
   ├─ http(s) 이미지 URL
   ├─ data:image;base64
   ├─ 일반 HTML 페이지  ➜ og:image 추출 후 다운로드
   └─ QImage (클립보드)
• 드롭/붙여넣기 → data/{ad_idx}.jpg 저장
• “◀/▶” 이동 시 드롭 존 리셋
• 온디맨드 DB 로딩, 폴더·지도 버튼, 4줄 로그, QThread 안전 종료
─────────────────────────────────────────────────────────────────
필수 패키지
    pip install PyQt5 psycopg2-binary mysql-connector-python
    pip install pandas openpyxl requests beautifulsoup4
"""

import sys, os, re, base64, traceback, urllib.parse, webbrowser, requests, configparser
from datetime import datetime
from bs4 import BeautifulSoup
import pandas as pd
import psycopg2, psycopg2.pool
import mysql.connector.pooling
from PyQt5.QtCore    import Qt, QThread, pyqtSignal, QUrl, QBuffer, QIODevice
from PyQt5.QtGui     import QPixmap, QGuiApplication, QKeySequence, QDesktopServices
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QTextEdit, QPushButton, QShortcut,
    QHBoxLayout, QVBoxLayout, QSplitter, QFileDialog, QMessageBox
)

# ──────────────────────────────────────────────────────────
# 1. Drag & Drop + Paste 라벨
# ──────────────────────────────────────────────────────────
IMG_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp")
_DATA_URL_RE = re.compile(r'data:image/[^;]+;base64,(.*)', re.I)

class DropImageLabel(QLabel):
    """드롭 또는 Ctrl+V 붙여넣기 → on_receive(bytes) 호출"""
    default_text = "이미지를\n여기로 드래그\n(Ctrl+V 붙여넣기)"

    def __init__(self, on_receive):
        super().__init__(self.default_text, alignment=Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.setStyleSheet("border:2px dashed #888; color:#555;")
        self.on_receive = on_receive

    def reset(self):
        self.clear()
        self.setText(self.default_text)

    # 드래그 허용
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self._process_mime(e.mimeData())

    # 클립보드도 동일 로직 사용
    def paste_from_clipboard(self):
        self._process_mime(QGuiApplication.clipboard().mimeData())

    # ------------------------------------------------------
    def _process_mime(self, md):
        # 1) URL 리스트
        if md.hasUrls():
            for url in md.urls():
                s = url.toString()

                # 로컬 파일
                if url.isLocalFile():
                    return self._accept(open(url.toLocalFile(), "rb").read())

                # data:image;base64
                m = _DATA_URL_RE.match(s)
                if m:
                    try: return self._accept(base64.b64decode(m.group(1)))
                    except Exception: pass

                # http(s) URL
                if s.startswith("http"):
                    try:
                        # 직접 이미지 확장자
                        if s.lower().endswith(IMG_EXT):
                            r = requests.get(s, timeout=5); r.raise_for_status()
                            return self._accept(r.content)

                        # HTML → og:image 추출
                        r = requests.get(
                            s, timeout=5,
                            headers={"User-Agent": "Mozilla/5.0"})
                        if "text/html" in r.headers.get("Content-Type", ""):
                            soup = BeautifulSoup(r.text, "html.parser")
                            og = soup.find("meta", property="og:image")
                            if og and og.get("content"):
                                img = requests.get(og["content"], timeout=5)
                                img.raise_for_status()
                                return self._accept(img.content)
                    except Exception:
                        pass

        # 2) 바이너리 이미지(QImage)
        if md.hasImage():
            qimg = md.imageData()
            if not qimg.isNull():
                px  = QPixmap.fromImage(qimg)
                buf = QBuffer(); buf.open(QIODevice.WriteOnly)
                px.save(buf, "JPG")
                return self._accept(bytes(buf.data()))

    def _accept(self, data: bytes):
        pix = QPixmap(); pix.loadFromData(data)
        self.setPixmap(pix.scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.on_receive(data)

# ──────────────────────────────────────────────────────────
# 2. DB Connection Pool
# ──────────────────────────────────────────────────────────
class MySQLPoolAdapter:
    def __init__(self, p): self._p = p
    def getconn(self):     return self._p.get_connection()
    def putconn(self, c):  c.close()

def make_pool(section, ini="db_config.ini"):
    cfg = configparser.ConfigParser(inline_comment_prefixes=(';', '#'))
    cfg.read(ini, encoding="utf-8")
    p = cfg[section]
    drv = p.get("driver", "postgres").lower()

    try:
        if drv == "postgres":
            pool = psycopg2.pool.SimpleConnectionPool(
                1, int(p.get("pool_max", 10)),
                host=p["host"], port=p["port"],
                dbname=p["dbname"], user=p["user"], password=p["password"])
        else:
            mp = mysql.connector.pooling.MySQLConnectionPool(
                pool_name=f"{section}_pool",
                pool_size=int(p.get("pool_max", 10)),
                host=p["host"], port=int(p["port"]),
                database=p["dbname"],
                user=p["user"], password=p["password"],
                autocommit=True)
            pool = MySQLPoolAdapter(mp)

        pool.putconn(pool.getconn())  # 연결 테스트
        return pool
    except Exception as e:
        QMessageBox.critical(None, "DB 오류", str(e))
        sys.exit(0)

# ──────────────────────────────────────────────────────────
# 3. 스레드 (이미지 Fetch / 결과 Save)
# ──────────────────────────────────────────────────────────
class FetchOne(QThread):
    done = pyqtSignal(str, bytes)
    err  = pyqtSignal(str)
    def __init__(self, pool, i_img):
        super().__init__(); self.pool=pool; self.i_img=i_img
    def run(self):
        try:
            cn=self.pool.getconn(); cur=cn.cursor()
            cur.execute("SELECT b_img FROM T_X_IMG WHERE i_img=%s",(self.i_img,))
            row=cur.fetchone(); self.pool.putconn(cn)
            if not row or row[0] is None:
                self.err.emit("이미지 없음"); return
            self.done.emit(self.i_img, bytes(row[0]))
        except Exception:
            self.err.emit(traceback.format_exc())

class Save(QThread):
    done=pyqtSignal(str); err=pyqtSignal(str)
    def __init__(self, pool, i_img, res, cmt, user):
        super().__init__(); self.pool=pool
        self.i_img=i_img; self.res=res; self.cmt=cmt; self.user=user
    def run(self):
        try:
            cn=self.pool.getconn(); cur=cn.cursor()
            cur.execute("""
             INSERT INTO T_X_IMG_VERIFY (i_img,c_verify,t_comment,c_reviewer,d_verify)
             VALUES (%s,%s,%s,%s,NOW())
             ON DUPLICATE KEY UPDATE
               c_verify=VALUES(c_verify),
               t_comment=VALUES(t_comment),
               c_reviewer=VALUES(c_reviewer),
               d_verify=NOW()
            """,(self.i_img,self.res,self.cmt,self.user))
            self.pool.putconn(cn); self.done.emit(self.res)
        except Exception:
            self.err.emit(traceback.format_exc())

# ──────────────────────────────────────────────────────────
# 4. 메인 GUI
# ──────────────────────────────────────────────────────────
class Reviewer(QWidget):
    def __init__(self):
        super().__init__()
        self.resize(1920, 1080)

        # -------- Excel 로드 --------
        xl, _ = QFileDialog.getOpenFileName(
            self, "Excel 선택", "", "Excel Files (*.xls *.xlsx *.xlsm)")
        if not xl: sys.exit(0)
        df = pd.read_excel(xl)
        if 'ad_idx' not in df.columns:
            QMessageBox.critical(self, "컬럼 오류", "ad_idx 컬럼이 없습니다."); sys.exit(0)

        self.rows = df[['ad_idx','company_name','읍면동','번지',
                        '광고물규격','광고물높이','광고물종류']].fillna("").to_dict('records')
        self.addr_full = df.get('번지2', pd.Series([""]*len(df))).fillna("").tolist()
        self.ids = [str(r['ad_idx']) for r in self.rows]
        self.reviewer = os.path.splitext(os.path.basename(xl))[0]

        # -------- DB 풀 --------
        self.pool_img = make_pool("image_db")
        self.pool_ver = make_pool("verify_db")

        # -------- UI --------
        self.pic = QLabel(alignment=Qt.AlignCenter)
        self.pic.setFixedSize(800, 600)
        self.pic.setStyleSheet("border:1px solid #666;")

        self.dropper = DropImageLabel(self.handle_drop)
        self.dropper.setFixedSize(800, 600)

        self.meta = QTextEdit(readOnly=True)
        self.meta.setFixedWidth(300)
        self.meta.setStyleSheet("background:#fafafa;")

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.pic)
        split.addWidget(self.dropper)
        split.addWidget(self.meta)
        split.setSizes([800, 800, 300])

        # 버튼
        b_prev,b_next=[QPushButton(t) for t in ("◀ 이전","다음 ▶")]
        b_ok,b_ng,b_hold=[QPushButton(t) for t in ("✅ 정상","❌ 불량","🕗 유보")]
        b_open = QPushButton("📂 폴더")
        b_map  = QPushButton("🗺️ 지도")
        for b in (b_prev,b_next,b_ok,b_ng,b_hold,b_open,b_map): b.setFixedHeight(40)

        b_prev.clicked.connect(lambda: self.move(-1))
        b_next.clicked.connect(lambda: self.move(+1))
        b_ok  .clicked.connect(lambda: self.save('Y'))
        b_ng  .clicked.connect(lambda: self.save('N'))
        b_hold.clicked.connect(lambda: self.save('U'))
        b_open.clicked.connect(self.open_folder)
        b_map .clicked.connect(self.open_map)

        nav = QHBoxLayout(); nav.addWidget(b_prev); nav.addWidget(b_next)
        act = QHBoxLayout(); act.addWidget(b_ok); act.addWidget(b_ng); act.addWidget(b_hold); act.addWidget(b_open); act.addWidget(b_map)

        self.memo = QTextEdit(); self.memo.setFixedHeight(70)
        self.log  = QTextEdit(readOnly=True); self.log.setFixedHeight(90); self.logs=[]

        lay = QVBoxLayout(self)
        lay.addWidget(split)
        lay.addLayout(nav)
        lay.addLayout(act)
        lay.addWidget(self.memo)
        lay.addWidget(self.log)

        # Ctrl+V 붙여넣기
        QShortcut(QKeySequence("Ctrl+V"), self,
                  activated=lambda: self.dropper.paste_from_clipboard())

        # 스레드 관리
        self._threads=[]

        # 상태
        self.idx = 0
        self.cache = {}

        self.show_current()

    # -------- 로깅 & 스레드 헬퍼 --------
    def _log(self, msg):
        t = datetime.now().strftime('%H:%M:%S')
        self.logs = self.logs[-3:] + [f"[{t}] {msg}"]
        self.log.setPlainText("\n".join(self.logs))

    def _track(self, th: QThread):
        self._threads.append(th)
        th.finished.connect(lambda: self._threads.remove(th))

    # -------- 드롭/붙여넣기 처리 --------
    def handle_drop(self, data: bytes):
        ad_idx = self.ids[self.idx]
        os.makedirs("data", exist_ok=True)
        path = os.path.join("data", f"{ad_idx}.jpg")
        with open(path, "wb") as f: f.write(data)
        self._log(f"저장: {os.path.basename(path)}")

    # -------- DB 이미지 --------
    def fetch_blob(self, i_img):
        if i_img in self.cache:
            self.display(i_img, self.cache[i_img]); return
        th = FetchOne(self.pool_img, i_img); self._track(th)
        th.done.connect(lambda I,b: self.display(I,b))
        th.err .connect(self.error)
        th.start(); self._log(f"요청: {i_img}")

    def display(self, i_img, blob):
        self.cache[i_img] = blob
        pix = QPixmap(); pix.loadFromData(blob)
        self.pic.setPixmap(pix.scaled(
            self.pic.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        r = self.rows[self.idx]
        self.meta.setHtml(
            f"<b>{r['company_name']}</b><br>"
            f"• 주소: {r['읍면동']} {r['번지']}<br>"
            f"• 규격: {r['광고물규격']}<br>"
            f"• 높이: {r['광고물높이']} m<br>"
            f"• 종류: {r['광고물종류']}"
        )
        self.setWindowTitle(f"p_if_pk_{self.ids[self.idx]} "
                            f"({self.idx+1}/{len(self.ids)})")
        self.memo.clear()

    # -------- 네비게이션 --------
    def move(self, step):
        self.idx = (self.idx + step) % len(self.ids)
        self.dropper.reset()          # 드롭 존 초기화
        self.show_current()

    def show_current(self):
        self.fetch_blob(f"p_if_pk_{self.ids[self.idx]}")

    # -------- 저장 --------
    def save(self, res):
        i_img = f"p_if_pk_{self.ids[self.idx]}"
        sv = Save(self.pool_ver, i_img, res,
                  self.memo.toPlainText().strip(), self.reviewer)
        self._track(sv)
        sv.done.connect(lambda r: self._log(f"저장: {i_img} → {r}"))
        sv.err .connect(self.error)
        sv.start()

    # -------- 보조 기능 --------
    def open_folder(self):
        r = self.rows[self.idx]
        p = os.path.join("images", r['읍면동'], r['번지'])
        if os.path.exists(p):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(p)))
            self._log("폴더 열기")
        else:
            self._log("폴더 없음")

    def open_map(self):
        addr = self.addr_full[self.idx] or (
            f"{self.rows[self.idx]['읍면동']} {self.rows[self.idx]['번지']}")
        url  = f"https://map.naver.com/v5/search/{urllib.parse.quote_plus(addr)}?zoom=18"
        webbrowser.open(url)
        self._log("지도 열기")

    # -------- 오류·종료 --------
    def error(self, msg):
        QMessageBox.critical(self, "오류", msg)
        self._log("오류")

    def closeEvent(self, e):
        for th in list(self._threads):
            if th.isRunning():
                th.quit()
                th.wait()
        e.accept()

# ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet("QPushButton{font-family:'Segoe UI'; font-size:15px;}")
    Reviewer().show()
    sys.exit(app.exec_())
