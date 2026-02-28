import os
import json
import datetime
import time
import urllib.request
import urllib.parse
import difflib
from urllib.error import HTTPError, URLError
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted

def verify_with_crossref(title, author):
    """
    Crossref API를 사용하여 논문을 검색하고, 제목 유사도가 80% 이상일 경우
    실제 데이터베이스에 등록된 공식 제목, 저자, URL을 반환합니다.
    """
    # title과 author를 분리하여 검색 정확도 향상
    encoded_title = urllib.parse.quote(title)
    encoded_author = urllib.parse.quote(author)
    
    # 정확도 비교를 위해 상위 3개 결과를 가져옴
    url = f"https://api.crossref.org/works?query.title={encoded_title}&query.author={encoded_author}&select=title,URL,author&rows=3"
    
    req = urllib.request.Request(
        url, 
        headers={'User-Agent': 'PaperBot/1.0 (mailto:github-actions@example.com)'}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.getcode() == 200:
                data = json.loads(response.read().decode('utf-8'))
                items = data.get('message', {}).get('items', [])
                
                if not items:
                    return None
                
                for item in items:
                    found_title_list = item.get('title', [])
                    if not found_title_list:
                        continue
                        
                    found_title = found_title_list[0]
                    found_url = item.get('URL', '')
                    
                    # 공식 저자명 추출 (첫 번째 저자의 성과 이름 결합)
                    authors = item.get('author', [])
                    found_author = ""
                    if authors:
                        family = authors[0].get('family', '')
                        given = authors[0].get('given', '')
                        found_author = f"{family}, {given}".strip(', ')
                    
                    # difflib을 이용한 정밀 문자열 유사도 검사 (80% 이상 일치 요구)
                    similarity = difflib.SequenceMatcher(None, title.lower(), found_title.lower()).ratio()
                    
                    if similarity >= 0.80:
                        return {
                            "verified_title": found_title,
                            "verified_author": found_author if found_author else author,
                            "verified_url": found_url
                        }
    except (HTTPError, URLError) as e:
        print(f"[Network/API Error] Crossref 연결 실패: {e}")
    except json.JSONDecodeError:
        print("[Parse Error] Crossref 응답 처리 실패")
    except Exception as e:
        print(f"[Unexpected Error] {e}")
        
    return None

# API 설정
api_key = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=api_key)

LOG_FILE = "papers_log.md"

existing_papers = ""
if os.path.exists(LOG_FILE):
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        content = f.read()
        existing_papers = content[-1500:] if len(content) > 1500 else content

prompt = f"""
Provide EXACTLY 2 semiconductor papers that ACTUALLY EXIST in academic databases. Do not hallucinate.
1. A historically significant MOSFET device physics paper for deep theoretical understanding. (Set "category" as "[Historic]")
2. A post-2020 high-industrial-impact DRAM or logic process integration paper. (Set "category" as "[Latest]")

Exclude any papers mentioned here: 
{existing_papers}

You MUST output a JSON array containing exactly 2 objects. 
Keys required: "category", "title", "author", "summary_kr".
Provide the exact official title and the first author's full name.
"""

model = genai.GenerativeModel("gemini-flash-latest")

max_retries = 5 
retry_delay_seconds = 40
success = False

for attempt in range(max_retries):
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
            )
        )
        
        text = response.text.strip()
        papers = json.loads(text)
        
        if len(papers) != 2:
            raise ValueError(f"Expected 2 papers, but got {len(papers)}.")
            
        verified_papers = []
        
        for p in papers:
            title = p.get('title', '')
            author = p.get('author', '')
            
            # 교차 검증 실행
            verification_result = verify_with_crossref(title, author)
            
            if not verification_result:
                raise ValueError(f"Crossref 검증 실패 (존재하지 않거나 정확도 미달): {title}")
            
            # LLM 생성 데이터를 공식 데이터로 완전 교체
            p['title'] = verification_result['verified_title']
            p['author'] = verification_result['verified_author']
            p['url'] = verification_result['verified_url']
            
            verified_papers.append(p)
                
        success = True
        
        # 텍스트 파일 업데이트
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            if os.stat(LOG_FILE).st_size == 0:
                f.write("| Date | Title | 1st Author | URL | Summary (KR) |\n")
                f.write("|---|---|---|---|---|\n")
                
            date_str = datetime.datetime.now().strftime("%Y-%m-%d")
            
            for p in verified_papers:
                category = p.get('category', '')
                title = p.get('title', '')
                author = p.get('author', '')
                url = p.get('url', '')
                summary = p.get('summary_kr', '')
                
                full_summary = f"{category} {summary}".strip()
                url_link = f"[Link]({url})"
                
                line = f"| {date_str} | {title} | {author} | {url_link} | {full_summary} |\n"
                f.write(line)
                
        print("Successfully updated papers_log.md with strictly verified papers.")
        break

    except ResourceExhausted:
        print(f"API Quota Exceeded. Retrying in {retry_delay_seconds} seconds... (Attempt {attempt + 1}/{max_retries})")
        time.sleep(retry_delay_seconds)
    except ValueError as e:
        print(f"Validation Error: {e}. Retrying... (Attempt {attempt + 1}/{max_retries})")
        time.sleep(5)
    except json.JSONDecodeError as e:
        print(f"JSON Parsing Error: {e}. Retrying... (Attempt {attempt + 1}/{max_retries})")
        time.sleep(5)
    except Exception as e:
        print(f"Unexpected Error: {e}")
        break

if not success:
    import sys
    sys.exit(1)



