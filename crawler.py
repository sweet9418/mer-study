import requests
from bs4 import BeautifulSoup


def crawl_url(url):
    """Crawl a URL and extract the main text content."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        response.encoding = response.apparent_encoding

        soup = BeautifulSoup(response.text, 'html.parser')

        # Remove script, style, nav, footer elements
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
            tag.decompose()

        # Try to find the main content area
        title = ''
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.get_text(strip=True)

        # Try common content containers
        content = ''
        for selector in ['article', 'main', '.post-content', '.entry-content',
                         '.article-body', '#content', '.content']:
            element = soup.select_one(selector)
            if element:
                content = element.get_text(separator='\n', strip=True)
                break

        if not content:
            body = soup.find('body')
            if body:
                content = body.get_text(separator='\n', strip=True)

        # Clean up content - remove excessive blank lines
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        content = '\n'.join(lines)

        # Limit content length
        if len(content) > 5000:
            content = content[:5000] + '...'

        return {
            'title': title,
            'content': content,
            'url': url,
            'success': True
        }

    except requests.RequestException as e:
        return {
            'title': '',
            'content': '',
            'url': url,
            'success': False,
            'error': str(e)
        }
