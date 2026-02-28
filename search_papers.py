import os
import json
import datetime
import google.generativeai as genai

# API 설정
api_key = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=api_key)

LOG_FILE = "papers_log.md"

# 기존 리스트 읽기 (최근 1000자만 읽어 토큰 사용 최소화 및 중복 방지)
existing_papers = ""
if os.path.exists(LOG_FILE):
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        content = f.read()
        existing_papers = content[-1000:] if len(content) > 1000 else content

# 토큰 절약을 위해 간결한 구조의 프롬프트 작성
prompt = f"""
Find 2 semiconductor papers. 
P1: Historically significant MOSFET device physics paper for deep theoretical understanding.
P2: Post-2020 high-industrial-impact DRAM or logic process integration paper.
Exclude any papers mentioned here: {existing_papers}

Output STRICTLY in the following JSON array format, without any additional text:
[
  {{"title": "", "author": "", "doi": "", "summary_kr": ""}},
  {{"title": "", "author": "", "doi": "", "summary_kr": ""}}
]
"""

# 지정된 모델 사용
model = genai.GenerativeModel("gemini-2.5-flash")
response = model.generate_content(prompt)

try:
    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    
    papers = json.loads(text.strip())
    
    # 텍스트 파일 지속 업데이트 (매일 한 줄씩 추가)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        if os.stat(LOG_FILE).st_size == 0:
            f.write("| Date | Title | 1st Author | DOI | Summary (KR) |\n")
            f.write("|---|---|---|---|---|\n")
            
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        
        for p in papers:
            title = p.get('title', '')
            author = p.get('author', '')
            doi = p.get('doi', '')
            summary = p.get('summary_kr', '')
            
            line = f"| {date_str} | {title} | {author} | [{doi}](https://doi.org/{doi}) | {summary} |\n"
            f.write(line)

except Exception as e:
    print(f"Error parsing or writing data: {e}")

    print(f"Raw response: {response.text}")
