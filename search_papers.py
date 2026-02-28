import os
import json
import datetime
import time
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted

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

# 프롬프트 수정: category 키 추가 및 [Historic], [Latest] 값 지정
prompt = f"""
Provide EXACTLY 2 semiconductor papers.
1. A historically significant MOSFET device physics paper for deep theoretical understanding. (Set "category" as "[Historic]")
2. A post-2020 high-industrial-impact DRAM or logic process integration paper. (Set "category" as "[Latest]")

Exclude any papers mentioned here: 
{existing_papers}

You MUST output a JSON array containing exactly 2 objects. 
Keys required: "category", "title", "author", "doi", "summary_kr".
"""

model = genai.GenerativeModel("gemini-2.5-flash")

max_retries = 3
retry_delay_seconds = 40
success = False

for attempt in range(max_retries):
    try:
        # JSON 포맷 출력을 시스템 레벨에서 강제
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
            )
        )
        
        text = response.text.strip()
        papers = json.loads(text)
        
        # 반환된 논문 개수 검증
        if len(papers) != 2:
            raise ValueError(f"Expected 2 papers, but got {len(papers)}.")
            
        success = True
        
        # 텍스트 파일 업데이트
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            if os.stat(LOG_FILE).st_size == 0:
                f.write("| Date | Title | 1st Author | DOI | Summary (KR) |\n")
                f.write("|---|---|---|---|---|\n")
                
            date_str = datetime.datetime.now().strftime("%Y-%m-%d")
            
            for p in papers:
                category = p.get('category', '')
                title = p.get('title', '')
                author = p.get('author', '')
                doi = p.get('doi', '')
                summary = p.get('summary_kr', '')
                
                # 태그와 요약문 결합
                full_summary = f"{category} {summary}".strip()
                
                doi_link = f"[{doi}](https://doi.org/{doi})" if not doi.startswith("http") else f"[Link]({doi})"
                
                line = f"| {date_str} | {title} | {author} | {doi_link} | {full_summary} |\n"
                f.write(line)
                
        print("Successfully updated papers_log.md with 2 papers including tags.")
        break

    except ResourceExhausted:
        print(f"API Quota Exceeded. Retrying in {retry_delay_seconds} seconds... (Attempt {attempt + 1}/{max_retries})")
        time.sleep(retry_delay_seconds)
    except ValueError as e:
        print(f"Validation Error: {e}. Retrying... (Attempt {attempt + 1}/{max_retries})")
        time.sleep(10)
    except json.JSONDecodeError as e:
        print(f"JSON Parsing Error: {e}. Retrying... (Attempt {attempt + 1}/{max_retries})")
        time.sleep(10)
    except Exception as e:
        print(f"Unexpected Error: {e}")
        break

if not success:
    import sys
    sys.exit(1)
