import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, StudyPost, QAEntry
from crawler import crawl_url
from ai_helper import generate_summary, generate_study_notes, suggest_tags, answer_question

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
    if current_user.is_authenticated:
        return redirect(url_for('workspace'))
    return render_template('index.html')


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

    return render_template('workspace.html', posts=posts, active_post=active_post, qa_entries=qa_entries)


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

    QAEntry.query.filter_by(post_id=post.id).delete()
    db.session.delete(post)
    db.session.commit()
    flash('삭제되었습니다.', 'success')
    return redirect(url_for('workspace'))


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


# Keep old study route as redirect
@app.route('/study/<int:post_id>')
@login_required
def study(post_id):
    return redirect(url_for('workspace', post_id=post_id))


if __name__ == '__main__':
    app.run(debug=True)
