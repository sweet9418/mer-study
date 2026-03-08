import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, StudyPost
from crawler import crawl_url
from ai_helper import generate_summary, generate_study_notes, suggest_tags

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Database configuration
database_url = os.environ.get('DATABASE_URL', 'sqlite:///mer_study.db')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = '로그인이 필요합니다.'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


with app.app_context():
    db.create_all()


# ─── Auth Routes ────────────────────────────────────────

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        if not username or not email or not password:
            flash('모든 필드를 입력해주세요.', 'error')
            return render_template('register.html')

        if User.query.filter_by(username=username).first():
            flash('이미 사용 중인 사용자명입니다.', 'error')
            return render_template('register.html')

        if User.query.filter_by(email=email).first():
            flash('이미 등록된 이메일입니다.', 'error')
            return render_template('register.html')

        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash('회원가입이 완료되었습니다!', 'success')
        return redirect(url_for('index'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash('로그인 되었습니다!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))

        flash('사용자명 또는 비밀번호가 올바르지 않습니다.', 'error')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('로그아웃 되었습니다.', 'success')
    return redirect(url_for('index'))


# ─── Main Routes ────────────────────────────────────────

@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '').strip()

    if current_user.is_authenticated:
        query = StudyPost.query.filter_by(user_id=current_user.id)
        if search:
            query = query.filter(
                db.or_(
                    StudyPost.title.ilike(f'%{search}%'),
                    StudyPost.tags.ilike(f'%{search}%'),
                    StudyPost.study_notes.ilike(f'%{search}%')
                )
            )
        posts = query.order_by(StudyPost.created_at.desc()).paginate(
            page=page, per_page=10, error_out=False
        )
    else:
        posts = None

    return render_template('index.html', posts=posts, search=search)


@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_post():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        source_url = request.form.get('source_url', '').strip()
        study_notes = request.form.get('study_notes', '').strip()
        tags = request.form.get('tags', '').strip()
        original_content = ''
        summary = ''

        # If URL provided, crawl it
        if source_url:
            result = crawl_url(source_url)
            if result['success']:
                original_content = result['content']
                if not title:
                    title = result['title']
                summary = generate_summary(original_content)
                if not study_notes:
                    study_notes = generate_study_notes(original_content, title)
                if not tags:
                    suggested = suggest_tags(original_content, title)
                    tags = ', '.join(suggested)
            else:
                flash(f'URL 크롤링 실패: {result.get("error", "알 수 없는 오류")}', 'error')

        if not title:
            flash('제목을 입력해주세요.', 'error')
            return render_template('add_post.html')

        post = StudyPost(
            title=title,
            source_url=source_url,
            original_content=original_content,
            study_notes=study_notes,
            summary=summary,
            tags=tags,
            user_id=current_user.id
        )
        db.session.add(post)
        db.session.commit()

        flash('학습 노트가 저장되었습니다!', 'success')
        return redirect(url_for('study', post_id=post.id))

    return render_template('add_post.html')


@app.route('/study/<int:post_id>', methods=['GET', 'POST'])
@login_required
def study(post_id):
    post = StudyPost.query.get_or_404(post_id)
    if post.user_id != current_user.id:
        flash('접근 권한이 없습니다.', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        post.study_notes = request.form.get('study_notes', '')
        post.tags = request.form.get('tags', '')
        db.session.commit()
        flash('노트가 업데이트되었습니다!', 'success')

    return render_template('study.html', post=post)


@app.route('/delete/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    post = StudyPost.query.get_or_404(post_id)
    if post.user_id != current_user.id:
        flash('접근 권한이 없습니다.', 'error')
        return redirect(url_for('index'))

    db.session.delete(post)
    db.session.commit()
    flash('삭제되었습니다.', 'success')
    return redirect(url_for('index'))


# ─── Profile Routes ────────────────────────────────────

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.bio = request.form.get('bio', '').strip()
        current_user.is_public = request.form.get('is_public') == 'on'
        db.session.commit()
        flash('프로필이 업데이트되었습니다!', 'success')

    post_count = StudyPost.query.filter_by(user_id=current_user.id).count()
    return render_template('profile.html', post_count=post_count)


@app.route('/user/<string:username>')
def shared_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    if not user.is_public:
        flash('비공개 프로필입니다.', 'error')
        return redirect(url_for('index'))

    posts = StudyPost.query.filter_by(user_id=user.id).order_by(
        StudyPost.created_at.desc()
    ).limit(20).all()

    return render_template('shared_profile.html', user=user, posts=posts)


# ─── Community Route ────────────────────────────────────

@app.route('/community')
def community():
    page = request.args.get('page', 1, type=int)
    public_users = User.query.filter_by(is_public=True).all()
    user_ids = [u.id for u in public_users]

    posts = StudyPost.query.filter(StudyPost.user_id.in_(user_ids)).order_by(
        StudyPost.created_at.desc()
    ).paginate(page=page, per_page=20, error_out=False)

    return render_template('community.html', posts=posts)


if __name__ == '__main__':
    app.run(debug=True)
