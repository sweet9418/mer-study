import re


def generate_summary(content, max_sentences=5):
    """Generate a simple extractive summary from content."""
    if not content:
        return ''

    # Split into sentences
    sentences = re.split(r'[.!?。]\s+', content)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

    if not sentences:
        return content[:300]

    # Return first N meaningful sentences as summary
    summary_sentences = sentences[:max_sentences]
    return '. '.join(summary_sentences) + '.'


def generate_study_notes(content, title=''):
    """Generate structured study notes from content."""
    if not content:
        return ''

    lines = content.split('\n')
    notes = []

    if title:
        notes.append(f'# {title}')
        notes.append('')

    notes.append('## 핵심 내용')
    notes.append('')

    # Extract key points (lines that seem important)
    key_points = []
    for line in lines:
        line = line.strip()
        if not line or len(line) < 10:
            continue
        # Skip very short or very long lines
        if 10 <= len(line) <= 200:
            key_points.append(line)

    # Take top key points
    for point in key_points[:10]:
        notes.append(f'- {point}')

    notes.append('')
    notes.append('## 요약')
    notes.append('')
    notes.append(generate_summary(content))

    notes.append('')
    notes.append('## 나의 메모')
    notes.append('')
    notes.append('> 여기에 자신만의 메모를 추가하세요.')

    return '\n'.join(notes)


def suggest_tags(content, title=''):
    """Suggest tags based on content keywords."""
    text = f'{title} {content}'.lower()

    tag_keywords = {
        'python': ['python', 'django', 'flask', 'pip'],
        'javascript': ['javascript', 'js', 'node', 'react', 'vue'],
        'web': ['html', 'css', 'web', '웹', 'frontend', 'backend'],
        'database': ['sql', 'database', 'db', '데이터베이스', 'mongodb'],
        'ai': ['ai', 'machine learning', '머신러닝', '인공지능', 'deep learning'],
        'devops': ['docker', 'kubernetes', 'aws', 'deploy', '배포'],
        'algorithm': ['algorithm', '알고리즘', 'sort', 'search', '자료구조'],
        'security': ['security', '보안', 'auth', 'encryption'],
        'mobile': ['android', 'ios', 'flutter', 'react native', '모바일'],
        'git': ['git', 'github', 'version control'],
    }

    tags = []
    for tag, keywords in tag_keywords.items():
        if any(kw in text for kw in keywords):
            tags.append(tag)

    return tags[:5]
