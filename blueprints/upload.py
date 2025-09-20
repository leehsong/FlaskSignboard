from flask import Blueprint, request, render_template, redirect, url_for, session
import os, uuid, pandas as pd
from werkzeug.utils import secure_filename
from utils.geocode import geocode_kakao, kakao_get_dong, kakao_get_road

upload_bp = Blueprint("upload", __name__)

UPLOAD_FOLDER = "./uploads"

@upload_bp.route("/upload", methods=["GET","POST"])
def upload_index():
    if "reviewer_name" not in session:
        return redirect(url_for("core.start"))
    if request.method=="POST":
        f=request.files.get("excel")
        path=os.path.join(UPLOAD_FOLDER, secure_filename(f.filename))
        f.save(path); df=pd.read_excel(path)
        for idx,row in df.iterrows():
            dong,road,bunji = row.get("t_add_3"),row.get("t_add_road"),row.get("t_add_num")
            if road and bunji and not dong:
                lng,lat=geocode_kakao(f"{road} {bunji}")
                if lng and lat: df.at[idx,"t_add_3"]=kakao_get_dong(lng,lat)
            if dong and bunji and not road:
                lng,lat=geocode_kakao(f"{dong} {bunji}")
                if lng and lat: df.at[idx,"t_add_road"]=kakao_get_road(lng,lat)
        upload_id=uuid.uuid4().hex
        session["upload_id"]=upload_id
        return redirect(url_for("review.log_review"))
    return render_template("index.html", reviewer=session["reviewer_name"])
