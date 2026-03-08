import os
import calendar
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, StudyPost, QAEntry, Comment, Bookmark
from crawler import crawl_url
from ai_helper import generate_summary, generate_study_notes, suggest_tags, answer_question

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

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
    # Add missing columns to existing tables
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    if 'study_post' in inspector.get_table_names():
        columns = [c['name'] for c in inspector.get_columns('study_post')]
        if 'is_shared' not in columns:
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE study_post ADD COLUMN is_shared BOOLEAN DEFAULT FALSE'))
                conn.commit()


# ─── Auth Routes ────────────────────────────────────────

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

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
        return redirect(url_for('dashboard'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash('로그인 되었습니다!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard'))

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
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html')


# ─── Dashboard (Calendar View) ─────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    year = request.args.get('year', date.today().year, type=int)
    month = request.args.get('month', date.today().month, type=int)

    if month < 1:
        month = 12
        year -= 1
    elif month > 12:
        month = 1
        year += 1

    cal = calendar.Calendar(firstweekday=6)  # Sunday first
    month_days = cal.monthdayscalendar(year, month)

    posts = StudyPost.query.filter_by(user_id=current_user.id).all()

    # day -> list of posts for this month
    day_posts = {}
    for post in posts:
        d = post.created_at.date()
        if d.year == year and d.month == month:
            day_posts.setdefault(d.day, []).append(post)

    # Streak calculation
    study_dates = set()
    for post in posts:
        study_dates.add(post.created_at.date())

    total_posts = len(posts)
    this_month_count = sum(len(v) for v in day_posts.values())
    streak = _calc_streak(study_dates)

    bookmarks = Bookmark.query.filter_by(user_id=current_user.id).order_by(
        Bookmark.created_at.desc()
    ).limit(10).all()

    recent_shared = StudyPost.query.filter(
        StudyPost.is_shared == True,
        StudyPost.user_id != current_user.id
    ).order_by(StudyPost.updated_at.desc()).limit(5).all()

    return render_template('dashboard.html',
                           year=year, month=month,
                           month_days=month_days,
                           day_posts=day_posts,
                           today=date.today(),
                           total_posts=total_posts,
                           this_month_count=this_month_count,
                           streak=streak,
                           bookmarks=bookmarks,
                           recent_shared=recent_shared,
                           month_name=f'{year}년 {month}월')


def _calc_streak(study_dates):
    if not study_dates:
        return 0
    today = date.today()
    streak = 0
    d = today
    while d in study_dates:
        streak += 1
        d = date.fromordinal(d.toordinal() - 1)
    return streak


# ─── Workspace (3-column) ──────────────────────────────

@app.route('/workspace')
@login_required
def workspace():
    posts = StudyPost.query.filter_by(user_id=current_user.id).order_by(
        StudyPost.created_at.desc()
    ).all()

    post_id = request.args.get('post_id', type=int)
    active_post = None
    qa_entries = []

    if post_id:
        active_post = StudyPost.query.get(post_id)
        if active_post and active_post.user_id != current_user.id:
            if not active_post.is_shared:
                active_post = None
        if active_post:
            qa_entries = QAEntry.query.filter_by(post_id=active_post.id).order_by(
                QAEntry.created_at.desc()
            ).all()
    elif posts:
        active_post = posts[0]
        qa_entries = QAEntry.query.filter_by(post_id=active_post.id).order_by(
            QAEntry.created_at.desc()
        ).all()

    comments = []
    if active_post:
        comments = Comment.query.filter_by(post_id=active_post.id).order_by(
            Comment.created_at.asc()
        ).all()

    return render_template('workspace.html', posts=posts, active_post=active_post,
                           qa_entries=qa_entries, comments=comments)


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

        if source_url:
            result = crawl_url(source_url)
            if result['success']:
                original_content = result['content']
                if not title:
                    title = result['title']
                summary = generate_summary(original_content)
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

        flash('글이 추가되었습니다!', 'success')
        return redirect(url_for('workspace', post_id=post.id))

    return render_template('add_post.html')


@app.route('/delete/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    post = StudyPost.query.get_or_404(post_id)
    if post.user_id != current_user.id:
        flash('접근 권한이 없습니다.', 'error')
        return redirect(url_for('workspace'))

    Comment.query.filter_by(post_id=post.id).delete()
    QAEntry.query.filter_by(post_id=post.id).delete()
    db.session.delete(post)
    db.session.commit()
    flash('삭제되었습니다.', 'success')
    return redirect(url_for('workspace'))


# ─── Sharing & Comments ───────────────────────────────

@app.route('/api/post/<int:post_id>/toggle-share', methods=['POST'])
@login_required
def api_toggle_share(post_id):
    post = StudyPost.query.get_or_404(post_id)
    if post.user_id != current_user.id:
        return jsonify({'error': '접근 권한이 없습니다.'}), 403
    post.is_shared = not post.is_shared
    db.session.commit()
    return jsonify({'is_shared': post.is_shared})


@app.route('/shared/<int:post_id>')
def view_shared(post_id):
    post = StudyPost.query.get_or_404(post_id)
    if not post.is_shared:
        flash('공유되지 않은 노트입니다.', 'error')
        return redirect(url_for('index'))

    comments = Comment.query.filter_by(post_id=post.id).order_by(
        Comment.created_at.asc()
    ).all()

    return render_template('shared_note.html', post=post, comments=comments)


@app.route('/shared/<int:post_id>/comment', methods=['POST'])
@login_required
def add_comment(post_id):
    post = StudyPost.query.get_or_404(post_id)
    if not post.is_shared:
        flash('공유되지 않은 노트입니다.', 'error')
        return redirect(url_for('index'))

    content = request.form.get('content', '').strip()
    if not content:
        flash('댓글 내용을 입력해주세요.', 'error')
        return redirect(url_for('view_shared', post_id=post_id))

    comment = Comment(post_id=post.id, user_id=current_user.id, content=content)
    db.session.add(comment)
    db.session.commit()
    flash('댓글이 등록되었습니다!', 'success')
    return redirect(url_for('view_shared', post_id=post_id))


@app.route('/api/comment/<int:comment_id>', methods=['DELETE'])
@login_required
def api_delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    if comment.user_id != current_user.id:
        return jsonify({'error': '접근 권한이 없습니다.'}), 403
    db.session.delete(comment)
    db.session.commit()
    return jsonify({'success': True})


# ─── Bookmarks ─────────────────────────────────────────

@app.route('/bookmarks')
@login_required
def bookmarks_page():
    bms = Bookmark.query.filter_by(user_id=current_user.id).order_by(
        Bookmark.created_at.desc()
    ).all()
    return render_template('bookmarks.html', bookmarks=bms)


@app.route('/bookmarks/add', methods=['POST'])
@login_required
def add_bookmark():
    title = request.form.get('title', '').strip()
    url = request.form.get('url', '').strip()
    memo = request.form.get('memo', '').strip()

    if not title or not url:
        flash('제목과 URL을 입력해주세요.', 'error')
        return redirect(url_for('bookmarks_page'))

    bm = Bookmark(user_id=current_user.id, title=title, url=url, memo=memo)
    db.session.add(bm)
    db.session.commit()
    flash('북마크가 추가되었습니다!', 'success')
    return redirect(url_for('bookmarks_page'))


@app.route('/bookmarks/<int:bm_id>/delete', methods=['POST'])
@login_required
def delete_bookmark(bm_id):
    bm = Bookmark.query.get_or_404(bm_id)
    if bm.user_id != current_user.id:
        flash('접근 권한이 없습니다.', 'error')
        return redirect(url_for('bookmarks_page'))
    db.session.delete(bm)
    db.session.commit()
    flash('북마크가 삭제되었습니다.', 'success')
    return redirect(url_for('bookmarks_page'))


# ─── API Routes (AJAX) ─────────────────────────────────

@app.route('/api/ask', methods=['POST'])
@login_required
def api_ask():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data'}), 400

    post_id = data.get('post_id')
    selected_text = data.get('selected_text', '').strip()
    question = data.get('question', '').strip()

    if not post_id or not question:
        return jsonify({'error': '질문을 입력해주세요.'}), 400

    post = StudyPost.query.get(post_id)
    if not post or post.user_id != current_user.id:
        return jsonify({'error': '접근 권한이 없습니다.'}), 403

    ai_answer = answer_question(selected_text, question, post.original_content)

    qa = QAEntry(
        post_id=post.id,
        selected_text=selected_text,
        question=question,
        ai_answer=ai_answer,
    )
    db.session.add(qa)
    db.session.commit()

    return jsonify({
        'id': qa.id,
        'selected_text': qa.selected_text,
        'question': qa.question,
        'ai_answer': qa.ai_answer,
        'created_at': qa.created_at.strftime('%Y-%m-%d %H:%M'),
    })


@app.route('/api/qa/<int:qa_id>/save-note', methods=['POST'])
@login_required
def api_save_note(qa_id):
    qa = QAEntry.query.get_or_404(qa_id)
    if qa.post.user_id != current_user.id:
        return jsonify({'error': '접근 권한이 없습니다.'}), 403

    data = request.get_json()
    qa.my_note = data.get('my_note', '')
    qa.is_saved = True
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/qa/<int:qa_id>/toggle-save', methods=['POST'])
@login_required
def api_toggle_save(qa_id):
    qa = QAEntry.query.get_or_404(qa_id)
    if qa.post.user_id != current_user.id:
        return jsonify({'error': '접근 권한이 없습니다.'}), 403

    qa.is_saved = not qa.is_saved
    db.session.commit()
    return jsonify({'is_saved': qa.is_saved})


@app.route('/api/qa/<int:qa_id>', methods=['DELETE'])
@login_required
def api_delete_qa(qa_id):
    qa = QAEntry.query.get_or_404(qa_id)
    if qa.post.user_id != current_user.id:
        return jsonify({'error': '접근 권한이 없습니다.'}), 403

    db.session.delete(qa)
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/post/<int:post_id>/update-notes', methods=['POST'])
@login_required
def api_update_notes(post_id):
    post = StudyPost.query.get_or_404(post_id)
    if post.user_id != current_user.id:
        return jsonify({'error': '접근 권한이 없습니다.'}), 403

    data = request.get_json()
    post.study_notes = data.get('study_notes', '')
    db.session.commit()
    return jsonify({'success': True})


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

    posts = StudyPost.query.filter_by(user_id=user.id, is_shared=True).order_by(
        StudyPost.created_at.desc()
    ).limit(20).all()

    return render_template('shared_profile.html', user=user, posts=posts)


# ─── Community Route ────────────────────────────────────

@app.route('/community')
def community():
    page = request.args.get('page', 1, type=int)

    posts = StudyPost.query.filter(
        StudyPost.is_shared == True
    ).order_by(
        StudyPost.updated_at.desc()
    ).paginate(page=page, per_page=20, error_out=False)

    return render_template('community.html', posts=posts)


# Keep old routes as redirects
@app.route('/study/<int:post_id>')
@login_required
def study(post_id):
    return redirect(url_for('workspace', post_id=post_id))


if __name__ == '__main__':
    app.run(debug=True)
