import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, session, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import OperationalError
from collections import Counter

app = Flask(__name__)
app.secret_key = "lux_secret"

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + DB_PATH
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

def ensure_category_description_column():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(category);")
        cols = [r[1] for r in cur.fetchall()]
        if "description" not in cols:
            cur.execute("ALTER TABLE category ADD COLUMN description TEXT;")
            conn.commit()
    finally:
        if conn:
            conn.close()

def ensure_post_score_column():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(post);")
        cols = [r[1] for r in cur.fetchall()]
        if "score" not in cols:
            cur.execute("ALTER TABLE post ADD COLUMN score REAL DEFAULT 0;")
            conn.commit()
    finally:
        if conn:
            conn.close()

ensure_category_description_column()
ensure_post_score_column()

db = SQLAlchemy(app)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    companies = db.relationship("Company", backref="category", lazy=True)
    posts = db.relationship("Post", backref="category", lazy=True)

class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False, unique=True)
    bio = db.Column(db.Text)
    website = db.Column(db.String(250))
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=True)
    posts = db.relationship("Post", backref="author", lazy=True)
    comments = db.relationship("Comment", backref="author", lazy=True)
    investments_made = db.relationship("InvestmentHistory", backref="investor", lazy=True, foreign_keys='InvestmentHistory.company_id')
    messages_sent = db.relationship("Message", backref="sender", lazy=True, foreign_keys='Message.sender_id')
    messages_received = db.relationship("Message", backref="receiver", lazy=True, foreign_keys='Message.receiver_id')

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    likes = db.Column(db.Integer, default=0)
    investment = db.Column(db.Integer, default=0)
    score = db.Column(db.Float, default=0)
    company_id = db.Column(db.Integer, db.ForeignKey("company.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    comments = db.relationship("Comment", backref="post", lazy=True, cascade="all, delete-orphan")
    investment_history = db.relationship("InvestmentHistory", backref="post", lazy=True, cascade="all, delete-orphan")

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    company_id = db.Column(db.Integer, db.ForeignKey("company.id"), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)

class PostLike(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey("company.id"), nullable=False)

class InvestmentHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("company.id"), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("company.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("company.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

def fix_companies_missing_category():
    try:
        companies = Company.query.filter((Company.category_id == None)).all()
    except:
        return
    updates = 0
    for comp in companies:
        posts = Post.query.filter_by(company_id=comp.id).all()
        if not posts:
            continue
        cat_ids = [p.category_id for p in posts if p.category_id]
        if not cat_ids:
            continue
        most_common = Counter(cat_ids).most_common(1)
        if most_common:
            comp.category_id = most_common[0][0]
            updates += 1
    if updates > 0:
        db.session.commit()

def calculate_post_score(post):
    base = (post.likes or 0) * 2 + (post.investment or 0) * 3
    content_factor = min(len(post.content or "") / 100, 10)
    comment_factor = min(len(post.comments), 10)
    post.score = base + content_factor + comment_factor
    db.session.commit()
    return post.score

def update_all_scores():
    for p in Post.query.all():
        calculate_post_score(p)

def get_sorted_companies(category, q=None):
    companies = category.companies
    companies_with_score = []
    for c in companies:
        total = sum((p.score or 0) for p in c.posts)
        c.ai_score = total
        companies_with_score.append(c)
    companies_with_score.sort(key=lambda x: x.ai_score, reverse=True)
    if q:
        ql = q.lower()
        return [c for c in companies_with_score if ql in c.name.lower() or any(ql in p.title.lower() for p in c.posts)]
    return companies_with_score

@app.route("/")
def home():
    cats = Category.query.order_by(Category.name).all()
    q = request.args.get("q", "").strip()
    for c in cats:
        c.companies_sorted = get_sorted_companies(c, q if q else None)
    return render_template("home.html", categories=cats, q=q)
@app.route("/categories")
def categories():
    cats = Category.query.order_by(Category.name).all()
    q = request.args.get("q", "").strip()
    for c in cats:
        c.companies_sorted = get_sorted_companies(c, q if q else None)
    return render_template("categories.html", categories=cats, q=q)

@app.route("/categories/create", methods=["GET", "POST"])
def create_category():
    # credenciais hardcoded
    SUPER_USER_NAME = "Lux"
    SUPER_USER_PASSWORD = "Sa0610He"

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        # verifica se é o superusuário
        if username != SUPER_USER_NAME or password != SUPER_USER_PASSWORD:
            return "Você não tem permissão para criar categoria", 403

        # coleta os dados da categoria
        name = request.form.get("name", "").strip()
        desc = request.form.get("description", "").strip()
        if not name:
            return "Nome é obrigatório", 400
        if Category.query.filter_by(name=name).first():
            return "Categoria já existe", 400

        c = Category(name=name, description=desc)
        db.session.add(c)
        db.session.commit()
        return redirect("/categories")

    return render_template("create_category.html")


@app.route("/categories/<int:category_id>")
def view_category(category_id):
    cat = Category.query.get_or_404(category_id)
    posts = Post.query.filter_by(category_id=category_id).order_by(Post.created_at.desc()).all()
    return render_template("category.html", category=cat, posts=posts)

@app.route("/categories/<int:category_id>/companies")
def companies_by_category(category_id):
    cat = Category.query.get_or_404(category_id)
    companies = Company.query.filter_by(category_id=category_id).all()
    companies_with_posts = []
    for c in companies:
        posts = Post.query.filter_by(company_id=c.id).order_by(Post.created_at.desc()).all()
        companies_with_posts.append({"company": c, "posts": posts})
    return render_template("companies.html", category=cat, companies_with_posts=companies_with_posts)

@app.route("/companies/create", methods=["GET", "POST"])
def create_company():
    cats = Category.query.order_by(Category.name).all()
    if request.method == "POST":
        name = request.form.get("name")
        bio = request.form.get("bio")
        site = request.form.get("website")
        cat_id = request.form.get("category_id")
        password = request.form.get("password")
        if not name or not cat_id or not password:
            return "Nome, senha e categoria são obrigatórios", 400
        if Company.query.filter_by(name=name).first():
            return "Empresa já existe", 400
        company = Company(name=name, bio=bio, website=site, category_id=int(cat_id), password=password)
        db.session.add(company)
        db.session.commit()
        return redirect(f"/company/{company.id}")
    return render_template("create_company.html", categories=cats)

@app.route("/company/<int:company_id>")
def company_detail(company_id):
    company = Company.query.get_or_404(company_id)
    posts = Post.query.filter_by(company_id=company.id).order_by(Post.created_at.desc()).all()
    return render_template("company_detail.html", company=company, posts=posts)

@app.route("/company/<int:company_id>/website")
def company_website(company_id):
    company = Company.query.get_or_404(company_id)
    posts = Post.query.filter_by(company_id=company.id).order_by(Post.created_at.desc()).all()
    return render_template("company_website.html", company=company, posts=posts)

@app.route("/company/<int:company_id>/history")
def company_history(company_id):
    company = Company.query.get_or_404(company_id)
    investments_received = (
        db.session.query(InvestmentHistory)
        .join(Post, InvestmentHistory.post_id == Post.id)
        .filter(Post.company_id == company.id)
        .order_by(InvestmentHistory.created_at.desc())
        .all()
    )
    return render_template("company_history.html", company=company, investments=investments_received)

@app.route("/history")
def history_global():
    investments = InvestmentHistory.query.order_by(InvestmentHistory.created_at.desc()).limit(200).all()
    return render_template("history.html", investments=investments)

@app.route("/top_posts")
def top_posts():
    update_all_scores()
    posts = Post.query.order_by(Post.score.desc()).limit(50).all()
    return render_template("top_posts.html", posts=posts)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password")
        company = Company.query.filter_by(name=name).first()
        if not company or company.password != password:
            return render_template("login.html", error="Nome ou senha incorretos")
        session["company_id"] = company.id
        return redirect("/my_account")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/my_account", methods=["GET", "POST"])
def my_account():
    if "company_id" not in session:
        return redirect("/login")
    company = Company.query.get(session["company_id"])
    if request.method == "POST":
        other_name = request.form.get("other_name", "").strip()
        other_company = Company.query.filter_by(name=other_name).first()
        if other_company:
            return redirect(url_for("chat", other_id=other_company.id))
        return "Empresa não encontrada", 404

    investments_received = (
        db.session.query(InvestmentHistory)
        .join(Post, InvestmentHistory.post_id == Post.id)
        .filter(Post.company_id == company.id)
        .order_by(InvestmentHistory.created_at.desc())
        .all()
    )

    investments_made = (
        InvestmentHistory.query
        .filter_by(company_id=company.id)
        .order_by(InvestmentHistory.created_at.desc())
        .all()
    )

    contacts = set()
    msgs = Message.query.filter(
        (Message.sender_id == company.id) | (Message.receiver_id == company.id)
    ).all()
    for m in msgs:
        if m.sender_id != company.id:
            contacts.add(m.sender_id)
        if m.receiver_id != company.id:
            contacts.add(m.receiver_id)
    contact_companies = Company.query.filter(Company.id.in_(contacts)).all() if contacts else []

    return render_template(
        "my_account.html",
        company=company,
        investments_received=investments_received,
        investments_made=investments_made,
        contacts=contact_companies
    )
@app.route("/my_investments")
def my_investments():
    if "company_id" not in session:
        return redirect("/login")
    company = Company.query.get(session["company_id"])
    investments = InvestmentHistory.query.filter_by(company_id=company.id).order_by(InvestmentHistory.created_at.desc()).all()
    return render_template("my_investments.html", investments=investments)


@app.route("/messages")
def inbox():
    if "company_id" not in session:
        return redirect("/login")
    me = session["company_id"]

    ids = db.session.query(Message.sender_id).filter(Message.receiver_id == me).distinct().all()
    ids2 = db.session.query(Message.receiver_id).filter(Message.sender_id == me).distinct().all()

    flat = set([i[0] for i in ids] + [i[0] for i in ids2])
    contacts = Company.query.filter(Company.id.in_(flat)).all() if flat else []

    return render_template("inbox.html", contacts=contacts)


@app.route("/chat/<int:other_id>", methods=["GET", "POST"])
def chat(other_id):
    if "company_id" not in session:
        return redirect("/login")

    company = Company.query.get(session["company_id"])
    other_company = Company.query.get_or_404(other_id)

    if request.method == "POST":
        content = request.form.get("message", "").strip()
        if content:
            msg = Message(sender_id=company.id, receiver_id=other_id, content=content)
            db.session.add(msg)
            db.session.commit()
        return redirect(url_for("chat", other_id=other_id))

    messages = Message.query.filter(
        ((Message.sender_id == company.id) & (Message.receiver_id == other_id)) |
        ((Message.sender_id == other_id) & (Message.receiver_id == company.id))
    ).order_by(Message.created_at).all()

    return render_template("messages.html", other=other_company, messages=messages, current_user=company)


@app.route("/edit_account", methods=["GET", "POST"])
def edit_account():
    if "company_id" not in session:
        return redirect("/login")

    company = Company.query.get(session["company_id"])

    if request.method == "POST":
        name = request.form.get("name").strip()
        bio = request.form.get("bio")
        website = request.form.get("website")
        password = request.form.get("password")

        if name:
            company.name = name
        company.bio = bio
        company.website = website
        if password:
            company.password = password

        db.session.commit()
        return redirect("/my_account")

    return render_template("edit_account.html", company=company)


# -----------------------------
#   ⭐ NOVO: EDITAR POST ⭐
# -----------------------------
@app.route("/post/<int:post_id>/edit", methods=["GET", "POST"])
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)

    if "company_id" not in session or session["company_id"] != post.company_id:
        return "Você não pode editar esse post", 403

    if request.method == "POST":
        post.title = request.form.get("title").strip()
        post.content = request.form.get("content").strip()
        db.session.commit()
        calculate_post_score(post)
        return redirect(f"/post/{post.id}")

    return render_template("edit_post.html", post=post)


@app.route("/posts/new/<int:category_id>", methods=["GET", "POST"])
def new_post(category_id):
    if "company_id" not in session:
        return redirect("/login")

    category = Category.query.get_or_404(category_id)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        invest = request.form.get("investment") or 0

        if not title:
            return "Título obrigatório", 400

        post = Post(
            title=title,
            content=content,
            company_id=session["company_id"],
            category_id=category_id,
            investment=int(invest)
        )
        db.session.add(post)
        db.session.commit()
        calculate_post_score(post)

        return redirect(url_for("post_view", post_id=post.id))

    return render_template("new_post.html", category=category)


@app.route("/post/<int:post_id>", methods=["GET", "POST"])
def post_view(post_id):
    post = Post.query.get_or_404(post_id)

    if request.method == "POST":

        # Comentário
        if "comment" in request.form:
            if "company_id" not in session:
                return redirect("/login")

            text = request.form.get("comment", "").strip()
            if text:
                c = Comment(content=text, company_id=session["company_id"], post_id=post.id)
                db.session.add(c)
                db.session.commit()
                calculate_post_score(post)

            return redirect(url_for("post_view", post_id=post.id))

        # Like
        if "like" in request.form:
            if "company_id" not in session:
                return redirect("/login")

            liked = PostLike.query.filter_by(post_id=post.id, company_id=session["company_id"]).first()
            if not liked:
                like = PostLike(post_id=post.id, company_id=session["company_id"])
                post.likes += 1
                db.session.add(like)
                db.session.commit()
                calculate_post_score(post)

            return redirect(url_for("post_view", post_id=post.id))

        # Investimento
        if "invest" in request.form:
            if "company_id" not in session:
                return redirect("/login")

            amount = int(request.form.get("invest", 0))
            if amount > 0:
                inv = InvestmentHistory(company_id=session["company_id"], post_id=post.id, amount=amount)
                post.investment += amount
                db.session.add(inv)
                db.session.commit()
                calculate_post_score(post)

            return redirect(url_for("post_view", post_id=post.id))

    return render_template("post_view.html", post=post)
@app.route("/post/<int:post_id>/delete", methods=["POST"])
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)

    if "company_id" not in session or session["company_id"] != post.company_id:
        return "Você não pode apagar esse post", 403

    db.session.delete(post)
    db.session.commit()
    return redirect("/")
@app.route("/comment/<int:comment_id>/delete", methods=["POST"])
def delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    if "company_id" not in session or session["company_id"] != comment.company_id:
        return "Você não pode apagar esse comentário", 403
    db.session.delete(comment)
    db.session.commit()
    return redirect(url_for("post_view", post_id=comment.post_id))
@app.route("/categories/delete/<int:category_id>", methods=["POST"])
def delete_category(category_id):
    # Só o superusuário Lux pode deletar
    username = request.form.get("username")
    password = request.form.get("password")
    if username != "Lux" or password != "Sa0610He":
        return "Acesso negado", 403

    category = Category.query.get_or_404(category_id)
    db.session.delete(category)
    db.session.commit()
    return redirect("/categories")


# ---------------------------------------------------
#   🔎 PESQUISA COMBINADA (EMPRESA + POST)
# ---------------------------------------------------
@app.route("/search_combined")
def search_combined():
    q = request.args.get("q", "").strip()

    if not q or "+" not in q:
        return "Formato correto: empresa + post", 400

    parts = q.split("+")
    if len(parts) < 2:
        return "Formato correto: empresa + post", 400

    company_name = parts[0].strip()
    post_name = parts[1].strip()

    comp = Company.query.filter(Company.name.ilike(f"%{company_name}%")).first()
    if not comp:
        return "Empresa não encontrada", 404

    post = Post.query.filter(Post.company_id == comp.id, Post.title.ilike(f"%{post_name}%")).first()
    if not post:
        return "Post não encontrado", 404

    return redirect(f"/post/{post.id}")
@app.route("/delete_account/<int:company_id>", methods=["POST"])
def delete_account(company_id):
    empresa = Company.query.get(company_id)
    if not empresa:
        return "Empresa não encontrada", 404

    try:
        # Deletar todos os investimentos feitos pela empresa
        InvestmentHistory.query.filter_by(company_id=empresa.id).delete()

        # Deletar todos os posts da empresa e os investimentos desses posts
        posts = Post.query.filter_by(company_id=empresa.id).all()
        for post in posts:
            InvestmentHistory.query.filter_by(post_id=post.id).delete()
            db.session.delete(post)

        # Deletar todas as mensagens enviadas ou recebidas pela empresa
        Message.query.filter((Message.sender_id == empresa.id) | (Message.receiver_id == empresa.id)).delete(synchronize_session=False)

        # Finalmente deletar a empresa
        db.session.delete(empresa)
        db.session.commit()
        return redirect(url_for("home"))
    except Exception as e:
        db.session.rollback()
        return f"Erro ao excluir a conta: {str(e)}"


# -----------------------------
#   FINAL DO APP
# -----------------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        fix_companies_missing_category()
        update_all_scores()
    app.run(debug=True)
