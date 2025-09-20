from flask import Blueprint, render_template, redirect, url_for, session, jsonify, request

core_bp = Blueprint("core", __name__)

@core_bp.route("/start", methods=["GET","POST"])
def start():
    if request.method == "POST":
        nm = (request.form.get("reviewer") or "").strip()
        if not nm:
            return render_template("start.html", error="검수자 이름 필요")
        session.clear()
        session["reviewer_name"] = nm
        return redirect(url_for("core.home"))   # ✅ 블루프린트 이름 붙여주기
    return render_template("start.html")

@core_bp.route("/home")
def home():
    if "reviewer_name" not in session:
        return redirect(url_for("core.start")) # ✅ 블루프린트 이름 붙여주기
    return render_template("home.html", reviewer=session["reviewer_name"])
