import os
import json
import datetime
import time
import urllib.request
import urllib.parse
from urllib.error import HTTPError, URLError
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted

def verify_with_crossref(title, author):
    """
    Crossref API를 사용하여 논문의 실존 여부를 교차 검증하고 공식 URL을 반환합니다.
    """
    # 검색 쿼리 생성
    query_str = f"{title} {author}"
    encoded_query = urllib.parse.quote(query_str)
    
    # Crossref API Endpoint (정확도를 높이기 위해 상위 1개 결과만 요청)
    url = f"https://api.crossref.org/works?query={encoded_query}&select=title,URL,author&rows=1"
    
    # Crossref의 Polite Pool 사용 권장에 따라 User-Agent 설정 (github actions 환경에서 안정적)
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
                    
                best_match = items[0]
                found_title = best_match.get('title', [''])[0].lower()
                
                # 모델 생성 제목과 Crossref 검색 제목의 단어 교집합 비율 확인 (환각 방지)
                query_words = set(title.lower().replace('-', ' ').split())
                found_words = set(found_title.replace('-', ' ').split())
                
                if len(query_words) > 0:
                    overlap_ratio = len(query_words.intersection(found_words)) / len(query_words)
                    # 단어 일치율이 30% 이상인 경우 유효한 논문으로 간주
                    if overlap_ratio >= 0.3:
                        return best_match.get('URL')
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

# 기존 리스트 읽기
existing_papers = ""
if os.path.exists(LOG_FILE):
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        content = f.read()
        existing_papers = content[-1500:] if len(content) > 1500 else content

# 프롬프트: 모델에게 URL 생성을 요구하지 않고 메타데이터의 정확성에 집중하도록 수정
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

model = genai.GenerativeModel("gemini-2.5-flash")

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
        
        # Crossref API를 통한 교차 검증 수행
        for p in papers:
            title = p.get('title', '')
            author = p.get('author', '')
            
            verified_url = verify_with_crossref(title, author)
            
            if not verified_url:
                raise ValueError(f"Crossref 검증 실패 (존재하지 않거나 제목이 불일치함): {title}")
            
            p['url'] = verified_url
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
                
        print("Successfully updated papers_log.md with Crossref-verified papers.")
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
