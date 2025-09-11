"""
🛂 admin_review.py  (관리자 승인/반려 도구)  – 2025-06-28
────────────────────────────────────────────────────────────────
• 대상 : verify_db.T_X_IMG_VERIFY  중  c_admin IS NULL
• 좌측 800×600 원본 이미지  ┃ 우측 검수 결과·코멘트·관리자 입력
• 승인(A) / 반려(R)  →  c_admin, t_admin_comment, c_admin_user, d_admin
• 모든 QThread 보관 → 안전 종료 (no “Destroyed while thread is running”)
────────────────────────────────────────────────────────────────
필수 패키지
    pip install PyQt5 psycopg2-binary mysql-connector-python
    pip install pandas requests
"""

import sys, os, traceback, configparser, requests
from datetime import datetime
import psycopg2, psycopg2.pool
import mysql.connector.pooling
from PyQt5.QtCore    import Qt, QThread, pyqtSignal, QUrl
from PyQt5.QtGui     import QPixmap
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QTextEdit,
    QHBoxLayout, QVBoxLayout, QSplitter, QMessageBox, QInputDialog
)

# ───────────────── 1. DB 풀 ─────────────────────────────────
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
                pool_name   = f"{section}_pool",
                pool_size   = int(p.get("pool_max", 10)),
                host        = p["host"], port=int(p["port"]),
                database    = p["dbname"],
                user        = p["user"], password=p["password"],
                autocommit  = True)
            pool = MySQLPoolAdapter(mp)

        pool.putconn(pool.getconn())  # 연결 테스트
        return pool
    except Exception as e:
        QMessageBox.critical(None, "DB 오류", str(e)); sys.exit(0)

# ───────────────── 2. 스레드 ────────────────────────────────
class FetchPending(QThread):
    done = pyqtSignal(list); err = pyqtSignal(str)
    def __init__(self, pool): super().__init__(); self.pool = pool
    def run(self):
        try:
            cn = self.pool.getconn(); cur = cn.cursor(dictionary=True)
            cur.execute(
                "SELECT i_img,c_verify,t_comment,c_reviewer "
                "FROM T_X_IMG_VERIFY WHERE c_admin IS NULL "
                "ORDER BY d_verify"
            )
            rows = cur.fetchall(); self.pool.putconn(cn)
            self.done.emit(rows)
        except Exception: self.err.emit(traceback.format_exc())

class FetchImage(QThread):
    done = pyqtSignal(bytes); err = pyqtSignal(str)
    def __init__(self, pool, i_img): super().__init__(); self.pool=pool; self.i_img=i_img
    def run(self):
        try:
            cn=self.pool.getconn(); cur=cn.cursor()
            cur.execute("SELECT b_img FROM T_X_IMG WHERE i_img=%s",(self.i_img,))
            row=cur.fetchone(); self.pool.putconn(cn)
            if not row or row[0] is None: self.err.emit("이미지 없음"); return
            self.done.emit(bytes(row[0]))
        except Exception: self.err.emit(traceback.format_exc())

class SaveAdmin(QThread):
    done = pyqtSignal(); err = pyqtSignal(str)
    def __init__(self, pool, i_img, res, cmt, user):
        super().__init__(); self.pool=pool
        self.i_img=i_img; self.res=res; self.cmt=cmt; self.user=user
    def run(self):
        try:
            cn=self.pool.getconn(); cur=cn.cursor()
            cur.execute("""
              UPDATE T_X_IMG_VERIFY
                 SET c_admin=%s,
                     t_admin_comment=%s,
                     c_admin_user=%s,
                     d_admin=NOW()
               WHERE i_img=%s
            """,(self.res,self.cmt,self.user,self.i_img))
            self.pool.putconn(cn); self.done.emit()
        except Exception: self.err.emit(traceback.format_exc())

# ───────────────── 3. 메인 GUI ─────────────────────────────
class AdminReview(QWidget):
    def __init__(self):
        super().__init__()
        self.resize(1920, 1080)
        self.setWindowTitle("🛂 관리자 검수")

        # 관리자 ID
        admin, ok = QInputDialog.getText(self, "관리자 ID", "ID 입력:")
        if not ok or not admin: sys.exit(0)
        self.admin = admin

        # DB 풀
        self.pool_img    = make_pool("image_db")
        self.pool_verify = make_pool("verify_db")

        # 대기목록 로딩
        self.pending = []; self.idx = 0

        # --- UI ----------
        self.pic = QLabel(alignment=Qt.AlignCenter)
        self.pic.setFixedSize(800, 600)
        self.pic.setStyleSheet("border:1px solid #666;")

        self.info = QTextEdit(readOnly=True)
        self.info.setFixedWidth(600)
        self.info.setStyleSheet("background:#fafafa;")

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.pic)
        split.addWidget(self.info)
        split.setSizes([800, 600])

        b_prev,b_next = [QPushButton(t) for t in ("◀ 이전","다음 ▶")]
        b_appr = QPushButton("✅ 승인 (A)")
        b_rej  = QPushButton("❌ 반려 (R)")
        for b in (b_prev,b_next,b_appr,b_rej): b.setFixedHeight(40)

        b_prev.clicked.connect(lambda: self.move(-1))
        b_next.clicked.connect(lambda: self.move(+1))
        b_appr.clicked.connect(lambda: self.save('A'))
        b_rej .clicked.connect(lambda: self.save('R'))

        nav = QHBoxLayout(); nav.addWidget(b_prev); nav.addWidget(b_next)
        act = QHBoxLayout(); act.addWidget(b_appr); act.addWidget(b_rej)

        self.comment = QTextEdit(); self.comment.setFixedHeight(80)
        self.comment.setPlaceholderText("관리자 의견…")

        self.log = QTextEdit(readOnly=True); self.log.setFixedHeight(80); self.logs=[]

        lay = QVBoxLayout(self)
        lay.addWidget(split)
        lay.addLayout(nav)
        lay.addLayout(act)
        lay.addWidget(self.comment)
        lay.addWidget(self.log)

        self._threads=[]
        self.load_pending()

    # ------- 헬퍼 -------
    def _track(self, th: QThread):
        self._threads.append(th)
        th.finished.connect(lambda: self._threads.remove(th))
    def _log(self, m):
        t=datetime.now().strftime('%H:%M:%S')
        self.logs=self.logs[-3:]+[f"[{t}] {m}"]
        self.log.setPlainText("\n".join(self.logs))

    # ------- 초기 목록 -------
    def load_pending(self):
        th = FetchPending(self.pool_verify); self._track(th)
        th.done.connect(self.set_pending); th.err.connect(self.error)
        th.start(); self._log("대기 목록 로딩…")

    def set_pending(self, rows):
        if not rows:
            QMessageBox.information(self,"완료","미승인 항목이 없습니다."); self.close(); return
        self.pending = rows; self.idx = 0; self.show_current()

    # ------- 표시 -------
    def show_current(self):
        it = self.pending[self.idx]
        i_img = it['i_img']
        self.info.setHtml(
            f"<b>이미지 ID:</b> {i_img}<br>"
            f"<b>검수자:</b> {it['c_reviewer']}<br>"
            f"<b>결과:</b> {it['c_verify']}<br>"
            f"<b>검수자 코멘트:</b><br>{it['t_comment']}"
        )
        # 이미지
        fx = FetchImage(self.pool_img, i_img); self._track(fx)
        fx.done.connect(self._set_pixmap); fx.err.connect(self.error); fx.start()

        self.setWindowTitle(f"{i_img}  ({self.idx+1}/{len(self.pending)})")
        self.comment.clear()

    def _set_pixmap(self, blob: bytes):
        pix = QPixmap(); pix.loadFromData(blob)
        self.pic.setPixmap(pix)

    # ------- 네비 -------
    def move(self, step):
        self.idx = (self.idx + step) % len(self.pending)
        self.show_current()

    # ------- 저장 -------
    def save(self, res):
        it = self.pending[self.idx]; i_img = it['i_img']
        sv = SaveAdmin(
            self.pool_verify, i_img, res,
            self.comment.toPlainText().strip(), self.admin)
        self._track(sv)
        sv.done.connect(lambda: self.after_save(i_img))
        sv.err .connect(self.error)
        sv.start(); self._log(f"저장 시도: {i_img} → {res}")

    def after_save(self, i_img):
        self._log(f"저장 완료: {i_img}")
        del self.pending[self.idx]
        if not self.pending:
            QMessageBox.information(self, "완료", "모든 항목 처리 완료"); self.close(); return
        if self.idx >= len(self.pending): self.idx = 0
        self.show_current()

    # ------- 오류/종료 -------
    def error(self, msg):
        QMessageBox.critical(self,"오류",msg); self._log("오류")

    def closeEvent(self, e):
        for th in list(self._threads):
            if th.isRunning():
                th.quit(); th.wait()
        e.accept()

# ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet("QPushButton{font-family:'Segoe UI'; font-size:15px;}")
    AdminReview().show()
    sys.exit(app.exec_())
