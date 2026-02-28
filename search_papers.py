import os
import json
import datetime
import time
import urllib.request
import urllib.parse
import difflib
import random
from urllib.error import HTTPError, URLError
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted

def verify_with_crossref(title, author):
    encoded_title = urllib.parse.quote(title)
    
    url = f"https://api.crossref.org/works?query.title={encoded_title}&select=title,URL,author&rows=5"
    
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
                    
                    authors = item.get('author', [])
                    found_author = ""
                    if authors:
                        family = authors[0].get('family', '')
                        given = authors[0].get('given', '')
                        found_author = f"{family}, {given}".strip(', ')
                    
                    similarity = difflib.SequenceMatcher(None, title.lower(), found_title.lower()).ratio()
                    
                    if similarity >= 0.65:
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

def is_duplicate(new_title, existing_titles):
    for ext_title in existing_titles:
        if difflib.SequenceMatcher(None, new_title.lower(), ext_title.lower()).ratio() > 0.85:
            return True
    return False

# 외부 토픽 파일 로드 함수
def load_topics(file_path="topics.json"):
    default_historic = ["MOSFET device physics general"]
    default_latest = ["DRAM logic process integration general"]
    
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                historic = data.get("historic_topics", default_historic)
                latest = data.get("latest_topics", default_latest)
                return historic, latest
        except json.JSONDecodeError as e:
            print(f"[File Error] topics.json 파싱 실패. 기본값을 사용합니다: {e}")
            return default_historic, default_latest
    else:
        print(f"[File Info] {file_path} 파일이 없습니다. 기본값을 사용합니다.")
        return default_historic, default_latest

# API 설정
api_key = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=api_key)

LOG_FILE = "papers_log.md"

# 1. 기존에 등록된 논문 제목 추출 (중복 방지)
existing_titles = set()
if os.path.exists(LOG_FILE):
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
        for line in lines:
            if line.startswith("|") and not line.startswith("| Date") and not line.startswith("|---"):
                parts = line.split("|")
                if len(parts) >= 4:
                    title = parts[2].strip()
                    existing_titles.add(title)

exclusion_list_text = "\n".join(f"- {t}" for t in existing_titles)

# 2. 외부 JSON 파일에서 토픽 로드
historic_topics, latest_topics = load_topics()

model = genai.GenerativeModel("gemini-flash-latest")

max_retries = 50 
retry_delay_seconds = 40
success = False
attempt = 1

while attempt <= max_retries:
    try:
        # 프롬프트 동적 생성 (선택된 랜덤 토픽 주입)
        prompt = f"""
        Provide EXACTLY 2 semiconductor papers that ACTUALLY EXIST in academic databases. Do not hallucinate.
        
        CRITICAL INSTRUCTION: You MUST EXCLUDE any papers that match the following titles. Do not generate them:
        {exclusion_list_text}
        
        1. A historically significant MOSFET device physics paper focusing on: {random.choice(historic_topics)}. (Set "category" as "[Historic]")
        2. A post-2020 high-industrial-impact DRAM or logic process integration paper focusing on: {random.choice(latest_topics)}. (Set "category" as "[Latest]")

        You MUST output a JSON array containing exactly 2 objects. 
        Keys required: "category", "title", "author", "summary_kr".
        Provide the exact official title and the first author's full name.
        """

        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.7 
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
            
            if is_duplicate(title, existing_titles):
                raise ValueError(f"중복 논문 생성 감지됨: {title}")
            
            verification_result = verify_with_crossref(title, author)
            
            if not verification_result:
                raise ValueError(f"Crossref 검증 실패 (존재하지 않거나 정확도 미달): {title}")
            
            verified_title = verification_result['verified_title']
            
            if is_duplicate(verified_title, existing_titles):
                raise ValueError(f"공식 제목 변환 후 중복 논문 감지됨: {verified_title}")
            
            p['title'] = verified_title
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
        print(f"API Quota Exceeded. Retrying in {retry_delay_seconds} seconds... (Attempt {attempt}/{max_retries})")
        time.sleep(retry_delay_seconds)
        attempt += 1
    except ValueError as e:
        print(f"Validation Error: {e}. Retrying... (Attempt {attempt}/{max_retries})")
        time.sleep(5)
        attempt += 1
    except json.JSONDecodeError as e:
        print(f"JSON Parsing Error: {e}. Retrying... (Attempt {attempt}/{max_retries})")
        time.sleep(5)
        attempt += 1
    except Exception as e:
        print(f"Unexpected Error: {e}")
        time.sleep(5)
        attempt += 1

if not success:
    import sys
    sys.exit(1)
