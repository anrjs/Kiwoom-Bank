Kiwoom Bank – Local Setup Guide
================================

This document explains how to bootstrap the Kiwoom Bank API server on a clean
machine. Follow the steps below to ensure all dependencies, external API keys,
and model assets are configured consistently across environments.

1. Prerequisites
----------------
- Python 3.9 or later (3.10+ recommended)
- Git
- Google Chrome or Chromium (required for the NICE crawler via Selenium)
- Enough disk space (~6 GB) for the FinBERT model and Torch runtime caches

2. Clone & Virtual Environment
-------------------------------
```bash
# Clone and enter the project
git clone <repo-url>
cd Kiwoom-Bank

# Create & activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Upgrade pip before installing packages
python -m pip install --upgrade pip
```

3. Install Dependencies
-----------------------
The project is packaged as a standard Python module. You can install everything
with editable mode (for development) or by using the flat requirements list.

**Option A – recommended for development**
```bash
pip install -e .
```

**Option B – traditional requirements file**
```bash
pip install -r requirements.txt
```

> The dependency lists in `pyproject.toml` and `requirements.txt` are now kept in
> sync. Choose one installation method to avoid duplicate installs.

4. Configure Environment Variables
----------------------------------
Copy the template below into a new `.env` file at the project root and fill in
your secrets. The FastAPI app automatically reads this file on startup.

```
# Required – OpenDART API key
DART_API_KEY=your_dart_api_key

# Optional – Naver News search (improves news sentiment features)
NAVER_CLIENT_ID=your_naver_client_id
NAVER_CLIENT_SECRET=your_naver_client_secret

# Optional – Translation via OpenAI (FinBERT works without translation)
OPENAI_API_KEY=your_openai_key
OPENAI_TRANSLATE_MODEL=gpt-4o-mini
OPENAI_TRANSLATE_TEMPERATURE=0.0
OPENAI_TRANSLATE_BATCH=20
```

Environment variables can also be exported in the shell, but the `.env` file is
the easiest way to share configuration.

5. Run the API Server
---------------------
```bash
# Activate the environment first if not already active
source .venv/bin/activate

# Start FastAPI through uvicorn
python run_server.py
# or: uvicorn api.app:app --host 0.0.0.0 --port 8000 --reload
```

Once the server starts you can inspect the interactive docs:
- Open <http://127.0.0.1:8000/docs> for Swagger UI.
- Use the `/features/ping` endpoint to confirm that local directories resolve
  correctly.

6. Model & Data Artifacts
-------------------------
- `credit_rating_project/artifacts_signal/` contains the serialized credit
  rating pipeline (`model.joblib` + label mappings). Ensure these files are
  present; otherwise credit scoring endpoints will raise `CreditModelNotReady`.
- `comp_features/` is created automatically to store uploaded feature CSV files.
- FinBERT (used by `news_analytics`) downloads on first run and is cached under
  the user’s Hugging Face directory (typically `~/.cache/huggingface`).

7. Selenium / NICE Ratings Crawler
----------------------------------
The credit rating crawler (`nice_rating`) relies on Selenium. During runtime it
will download a matching ChromeDriver via `webdriver-manager`. Ensure Chrome is
installed and accessible in the PATH. For headless operation no extra steps are
required.

8. Optional Utilities
---------------------
The repository includes command-line utilities under `tools/` and
`credit_rating_project/`. They assume the same virtual environment and
configuration. Refer to in-file docstrings for usage details.

9. Troubleshooting
------------------
- Missing `DART_API_KEY` will prevent the server from starting; check the log
  output on startup.
- Slow startup is expected the first time FinBERT and Torch are downloaded.
- If Selenium cannot find Chrome, install Chrome or adjust the `ChromeDriver` path
  via environment variables described in `nice_rating/crawler_impl.py`.

With the steps above, any teammate can set up the Kiwoom Bank API server on a
fresh machine and obtain identical behavior.

# Kiwoom Bank – 로컬 설정 가이드

이 문서는 Kiwoom Bank API 서버를 **초기 상태의 머신에서 부트스트랩하는 방법**을 안내합니다. 아래 단계들을 따르면, 의존성 설치, 외부 API 키 등록, 모델 자산 설정 등을 환경 간에 일관되게 구성할 수 있습니다.

---

## 1. 사전 준비 사항

- Python 3.9 이상 (권장: 3.10 이상)
- Git
- Google Chrome 또는 Chromium (Selenium 기반 NICE 크롤러에 필요)
- FinBERT 모델 및 Torch 캐시를 위한 디스크 공간 약 6GB

---

## 2. 클론 및 가상환경 설정

```bash
# 프로젝트 클론 및 디렉터리 진입
git clone <repo-url>
cd Kiwoom-Bank

# 가상환경 생성 및 활성화
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# pip 업그레이드
python -m pip install --upgrade pip