import os
import re
import json
import requests


def _call_claude_api(prompt, max_tokens=1024):
    """Call Claude API if API key is available, otherwise return None."""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return None

    try:
        resp = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': api_key,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json',
            },
            json={
                'model': 'claude-haiku-4-5-20251001',
                'max_tokens': max_tokens,
                'messages': [{'role': 'user', 'content': prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data['content'][0]['text']
    except Exception:
        return None


def answer_question(selected_text, question, full_context=''):
    """Answer a question about the selected text from a blog post."""
    prompt = f"""당신은 학습 도우미 AI입니다. 사용자가 블로그 글의 일부를 선택하고 질문했습니다.
한국어로 답변해주세요. 명확하고 이해하기 쉽게 설명해주세요.

## 선택한 텍스트
{selected_text}

## 전체 글 맥락 (참고용)
{full_context[:2000]}

## 사용자 질문
{question}

위 내용을 바탕으로 질문에 대해 상세하게 답변해주세요."""

    result = _call_claude_api(prompt)
    if result:
        return result

    # Fallback: simple keyword-based response
    return _fallback_answer(selected_text, question)


def _fallback_answer(selected_text, question):
    """Provide a basic fallback answer when no API key is available."""
    lines = []
    lines.append(f'**선택한 텍스트에 대한 분석:**\n')

    if not selected_text.strip():
        lines.append('텍스트를 선택하지 않았습니다. 글에서 궁금한 부분을 드래그하여 선택한 후 질문해주세요.')
        return '\n'.join(lines)

    words = selected_text.split()
    lines.append(f'선택한 텍스트는 약 {len(words)}개 단어로 구성되어 있습니다.\n')

    if '?' in question or '뭐' in question or '무엇' in question or '어떻게' in question:
        lines.append(f'> "{selected_text[:100]}..."\n')
        lines.append('이 부분은 다음과 같이 이해할 수 있습니다:')
        lines.append(f'- 핵심 내용: {selected_text[:150]}')
        lines.append('')
        lines.append('**참고:** ANTHROPIC_API_KEY 환경변수를 설정하면 Claude AI가 더 정확한 답변을 제공합니다.')
    else:
        lines.append(f'질문: {question}')
        lines.append(f'\n선택한 텍스트를 기반으로 분석하면:')
        lines.append(f'- {selected_text[:200]}')
        lines.append('')
        lines.append('**참고:** ANTHROPIC_API_KEY 환경변수를 설정하면 Claude AI가 더 정확한 답변을 제공합니다.')

    return '\n'.join(lines)


def generate_summary(content, max_sentences=5):
    """Generate a simple extractive summary from content."""
    if not content:
        return ''

    prompt = f"다음 글을 5문장 이내로 요약해주세요:\n\n{content[:3000]}"
    result = _call_claude_api(prompt, max_tokens=512)
    if result:
        return result

    sentences = re.split(r'[.!?。]\s+', content)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
    if not sentences:
        return content[:300]
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

    key_points = []
    for line in lines:
        line = line.strip()
        if not line or len(line) < 10:
            continue
        if 10 <= len(line) <= 200:
            key_points.append(line)

    for point in key_points[:10]:
        notes.append(f'- {point}')

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
