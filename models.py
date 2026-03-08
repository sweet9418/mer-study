from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    bio = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_public = db.Column(db.Boolean, default=True)

    posts = db.relationship('StudyPost', backref='author', lazy=True)

    def __repr__(self):
        return f'<User {self.username}>'


class StudyPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    source_url = db.Column(db.String(500), default='')
    original_content = db.Column(db.Text, default='')
    study_notes = db.Column(db.Text, default='')
    summary = db.Column(db.Text, default='')
    tags = db.Column(db.String(200), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    def get_tags_list(self):
        if not self.tags:
            return []
        return [tag.strip() for tag in self.tags.split(',') if tag.strip()]

    def __repr__(self):
        return f'<StudyPost {self.title}>'


class QAEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('study_post.id'), nullable=False)
    selected_text = db.Column(db.Text, default='')
    question = db.Column(db.Text, nullable=False)
    ai_answer = db.Column(db.Text, default='')
    my_note = db.Column(db.Text, default='')
    is_saved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    post = db.relationship('StudyPost', backref=db.backref('qa_entries', lazy=True, order_by='QAEntry.created_at.desc()'))

    def __repr__(self):
        return f'<QAEntry {self.id}>'
