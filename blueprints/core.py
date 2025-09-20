# blueprints/core.py

from flask import Blueprint, render_template, session, redirect, url_for, request

core_bp = Blueprint("core", __name__)

@core_bp.route("/start", methods=["GET", "POST"])
def start():
    if request.method == "POST":
        nm = (request.form.get("reviewer") or "").strip()
        if not nm:
            return render_template("start.html", error="이름을 입력하세요.")
        session.clear()
        session["reviewer_name"] = nm
        return redirect(url_for("core.home"))
    return render_template("start.html")

@core_bp.route("/home")
def home():
    # 세션에 사용자 이름 없으면 시작 페이지로
    if "reviewer_name" not in session:
        return redirect(url_for("core.start"))
    # 첫 화면: 4개의 카드 보여주는 home.html
    return render_template("home.html", reviewer=session["reviewer_name"])

# 아래는 각 카드 눌렀을 때 가는 화면들 (현재는 placeholder)
@core_bp.route("/company_merge")
def company_merge():
    return render_template("company_merge.html")

@core_bp.route("/upload_records")
def upload_records():
    return render_template("upload_records.html")

@core_bp.route("/sign_edit")
def sign_edit():
    return render_template("sign_edit.html")

@core_bp.route("/view_reviews")
def view_reviews():
    return render_template("view_reviews.html")
