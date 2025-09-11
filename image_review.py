import sys, os, traceback, configparser, urllib.parse, webbrowser
from datetime import datetime
import pandas as pd
import psycopg2, psycopg2.pool
import mysql.connector.pooling
from PyQt5.QtCore    import Qt, QThread, pyqtSignal, QUrl
from PyQt5.QtGui     import QPixmap, QFont, QDesktopServices
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QTextEdit,
    QHBoxLayout, QVBoxLayout, QSplitter, QFileDialog, QMessageBox
)
import requests
KAKAO_KEY = "364d1d857bf47a507fe237a9e20f00e4"  # ← 실제 키로 변경

def geocode_kakao(addr: str):
    """
    주소 → (longitude, latitude)
    실패 시 (None, None) 반환
    """

    if not KAKAO_KEY:
            return None, None
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_KEY}"}
    r = requests.get(url, params={"query": addr}, headers=headers, timeout=5)
    if r.status_code != 200 or not r.json().get("documents"):
        return None, None
    doc = r.json()["documents"][0]
    return float(doc["x"]), float(doc["y"])          # (lng, lat)
    
# ───── DB 풀 팩토리 ───────────────────────────────────────────
class MySQLPoolAdapter:
    def __init__(self,p): self._p=p
    def getconn(self):  return self._p.get_connection()
    def putconn(self,c): c.close()

def make_pool(sec, ini="db_config.ini"):
    cfg=configparser.ConfigParser(inline_comment_prefixes=(';', '#'))
    cfg.read(ini,encoding="utf-8")
    p=cfg[sec]; drv=p.get("driver","postgres").lower()
    try:
        if drv=="postgres":
            pool=psycopg2.pool.SimpleConnectionPool(
                1,int(p.get("pool_max",10)),
                host=p["host"], port=p["port"], dbname=p["dbname"],
                user=p["user"], password=p["password"])
        else:
            mp=mysql.connector.pooling.MySQLConnectionPool(
                pool_name=f"{sec}_pool", pool_size=int(p.get("pool_max",10)),
                host=p["host"], port=int(p["port"]), database=p["dbname"],
                user=p["user"], password=p["password"], autocommit=True)
            pool=MySQLPoolAdapter(mp)
        pool.putconn(pool.getconn())  # test
        return pool, None
    except Exception as e:
        return None, str(e)

# ───── 스레드 ────────────────────────────────────────────────
class FetchOne(QThread):
    done=pyqtSignal(str,bytes); err=pyqtSignal(str)
    def __init__(self,pool,i_img):
        super().__init__(); self.pool=pool; self.i_img=i_img
    def run(self):
        try:
            c=self.pool.getconn(); cur=c.cursor()
            cur.execute("SELECT b_img FROM T_X_IMG WHERE i_img=%s",(self.i_img,))
            row=cur.fetchone(); self.pool.putconn(c)
            if not row or row[0] is None: self.err.emit(f"이미지 없음: {self.i_img}"); return
            blob=row[0]; blob=bytes(blob) if isinstance(blob, memoryview) else blob
            self.done.emit(self.i_img, blob)
        except Exception: self.err.emit(traceback.format_exc())

class Save(QThread):
    done=pyqtSignal(str); err=pyqtSignal(str)
    def __init__(self,pool,i_img,res,cmt,user):
        super().__init__(); self.pool=pool; self.i_img=i_img
        self.res=res; self.cmt=cmt; self.user=user
    def run(self):
        try:
            c=self.pool.getconn(); cur=c.cursor()
            cur.execute("""
              INSERT INTO T_X_IMG_VERIFY (i_img,c_verify,t_comment,c_reviewer,d_verify)
              VALUES (%s,%s,%s,%s,NOW())
              ON DUPLICATE KEY UPDATE
                c_verify=VALUES(c_verify), t_comment=VALUES(t_comment),
                c_reviewer=VALUES(c_reviewer), d_verify=NOW()
            """,(self.i_img,self.res,self.cmt,self.user))
            self.pool.putconn(c); self.done.emit(self.res)
        except Exception: self.err.emit(traceback.format_exc())

# ───── 메인 GUI ─────────────────────────────────────────────
class Reviewer(QWidget):
    def __init__(self):
        super().__init__(); self.setWindowTitle("🖼️ Image Reviewer"); self.resize(1100,720)

        # Excel 선택
        xl,_=QFileDialog.getOpenFileName(self,"Excel 선택","","Excel Files (*.xls *.xlsx *.xlsm)")
        if not xl: sys.exit(0)

        try: df=pd.read_excel(xl)
        except Exception as e: QMessageBox.critical(self,"엑셀 오류",str(e)); sys.exit(0)

        if 'ad_idx' not in df.columns:
            QMessageBox.critical(self,"컬럼 오류","Excel에 'ad_idx' 컬럼이 없습니다."); sys.exit(0)

        self.rows=df[['ad_idx','company_name','읍면동','번지','광고물규격','광고물높이','광고물종류']].fillna("").to_dict('records')
        self.addr_full = df.get('번지2', pd.Series([""]*len(df))).fillna("").tolist()
        self.id_list=[str(r['ad_idx']) for r in self.rows]
        self.reviewer=os.path.splitext(os.path.basename(xl))[0]

        # DB
        self.pool_img,err=make_pool("image_db")
        if err: QMessageBox.critical(self,"DB 오류",f"image_db 연결 실패:\n{err}"); sys.exit(0)
        self.pool_ver,err=make_pool("verify_db")
        if err: QMessageBox.critical(self,"DB 오류",f"verify_db 연결 실패:\n{err}"); sys.exit(0)

        # UI ─── 이미지 + 메타
        self.pic=QLabel(alignment=Qt.AlignCenter)
        self.pic.setMinimumSize(600,460); self.pic.setStyleSheet("border:1px solid #888;")

        self.meta=QTextEdit(readOnly=True); self.meta.setStyleSheet("background:#f9f9f9;")
        self.meta.setFixedWidth(420)

        split=QSplitter(Qt.Horizontal); split.addWidget(self.pic); split.addWidget(self.meta); split.setStretchFactor(0,3)

        # 버튼
        b_prev,b_next=[QPushButton(t) for t in ("◀ 이전","다음 ▶")]
        b_ok,b_ng,b_hold=[QPushButton(t) for t in ("✅ 정상(Y)","❌ 불량(N)","🕗 유보(U)")]
        b_open=QPushButton("📂 폴더"); b_map=QPushButton("🗺️ 지도")
        for b in (b_prev,b_next,b_ok,b_ng,b_hold,b_open,b_map): b.setFixedHeight(34)

        b_prev.clicked.connect(lambda:self.move(-1)); b_next.clicked.connect(lambda:self.move(+1))
        b_ok.clicked.connect(lambda:self.save('Y')); b_ng.clicked.connect(lambda:self.save('N')); b_hold.clicked.connect(lambda:self.save('U'))
        b_open.clicked.connect(self.open_folder); b_map.clicked.connect(self.open_map)

        nav=QHBoxLayout(); nav.addWidget(b_prev); nav.addWidget(b_next)
        act=QHBoxLayout(); act.addWidget(b_ok); act.addWidget(b_ng); act.addWidget(b_hold); act.addWidget(b_open); act.addWidget(b_map)

        self.memo=QTextEdit(); self.memo.setFixedHeight(60); self.memo.setPlaceholderText("검수 의견…")
        self.log=QTextEdit(readOnly=True); self.log.setFixedHeight(90); self.logs=[]

        lay=QVBoxLayout(self); lay.addWidget(split); lay.addLayout(nav); lay.addLayout(act); lay.addWidget(self.memo); lay.addWidget(self.log)

        # 상태
        self.idx=0; self.cache={}; self.thread=None
        self.show_current()

    # 로그
    def _log(self,msg):
        t=datetime.now().strftime('%H:%M:%S')
        self.logs=self.logs[-3:]+[f"[{t}] {msg}"]; self.log.setPlainText("\n".join(self.logs))

    # DB fetch
    def fetch_blob(self,i_img):
        if i_img in self.cache: self.display(i_img,self.cache[i_img]); return
        self.pic.setText("🔄 로딩…"); th=FetchOne(self.pool_img,i_img); self.thread=th
        th.done.connect(lambda id,b:self.on_blob(id,b)); th.err.connect(self.err); th.start(); self._log(f"요청: {i_img}")

    def on_blob(self,i,b):
        self.cache[i]=b; self.display(i,b); self.thread=None; self._log(f"로드: {i}")
    def err(self,msg):
        QMessageBox.critical(self,"오류",msg); self._log("오류"); self.thread=None

    # 표시
    def display(self,i_img,blob):
        pix=QPixmap(); ok=pix.loadFromData(blob)
        self.pic.setPixmap(pix.scaled(self.pic.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation) if ok else QPixmap())
        row=self.rows[self.idx]
        meta=(f"<b>{row['company_name']}</b><br>"
              f"• 주소: {row['읍면동']} {row['번지']}<br>"
              f"• 규격: {row['광고물규격']}<br>"
              f"• 높이: {row['광고물높이']} m<br>"
              f"• 종류: {row['광고물종류']}")
        self.meta.setHtml(meta); self.memo.clear()
        self.setWindowTitle(f"{i_img}  ({self.idx+1}/{len(self.id_list)})")

    # 이동
    def move(self,st):
        if self.thread and self.thread.isRunning(): return
        self.idx=(self.idx+st)%len(self.id_list); self.show_current()

    def show_current(self):
        i_img=f"p_if_pk_{self.id_list[self.idx]}"; self.fetch_blob(i_img)

    # 저장
    def save(self,res):
        if self.thread and self.thread.isRunning(): return
        i_img=f"p_if_pk_{self.id_list[self.idx]}"; txt=self.memo.toPlainText().strip()
        sv=Save(self.pool_ver,i_img,res,txt,self.reviewer)
        sv.done.connect(lambda r:self._log(f"저장: {i_img}→{r}")); sv.err.connect(self.err); sv.start()

    # 폴더 열기
    def open_folder(self):
        row=self.rows[self.idx]; path=os.path.join("images",row['읍면동'],row['번지'])
        if not os.path.exists(path):
            self._log("폴더 없음"); QMessageBox.information(self,"경로 없음",path); return
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(path))); self._log("폴더 오픈")

    # 지도 (검색 + zoom=18)
    def open_map(self):
        # ① 주소 문장
        addr = self.addr_full[self.idx] or (
            f"{self.rows[self.idx]['읍면동']} {self.rows[self.idx]['번지']}"
        )

        # ② 좌표 얻기
        lng, lat = geocode_kakao(addr)
        print(lng, lat)
        if lng and lat:
            # ③ 좌표 기반 URL - 줌 18단계
            url = (
                f"https://map.naver.com/v5/geo/{lng},{lat}"
                f"?c={lng},{lat},18,0,0,0,dh"
            )
            self._log("지도(좌표) 오픈")
        else:
            # 좌표 실패 → 일반 검색
            q   = urllib.parse.quote_plus(addr)
            url = f"https://map.naver.com/v5/search/{q}"
            self._log("지도(검색) 오픈")

        webbrowser.open(url)


    def closeEvent(self,e):
        if self.thread and self.thread.isRunning(): self.thread.quit(); self.thread.wait()
        e.accept()

# 실행
if __name__=="__main__":
    app=QApplication(sys.argv)
    app.setStyleSheet("QPushButton{font-family:'Segoe UI';font-size:14px;}")
    Reviewer().show(); sys.exit(app.exec_())
