# ☁️ 클라우드 개발 및 배포 가이드

이 문서는 **GitHub Codespaces**와 **Streamlit Community Cloud**를 활용하여, **어떤 PC에서든 웹 브라우저만으로** 이 주식 분석 앱을 개발하고 실행하는 방법을 안내합니다.

---

## 1. 사전 준비 (Local PC)

이미 필요한 설정 파일(`requirements.txt`, `.gitignore`)은 생성해 두었습니다. 이제 코드를 클라우드(GitHub)에 업로드해야 합니다.

### 1-A. GitHub 가입 및 저장소 생성
1. [GitHub](https://github.com/)에 회원가입/로그인합니다.
2. 우측 상단 `+` 버튼 -> **New repository** 클릭.
3. 저장소 이름(예: `stock-analysis-app`) 입력.
4. **Public** (공개) 선택 (Private도 가능하나 Streamlit 배포 시 설정이 더 필요할 수 있음).
5. **Create repository** 버튼 클릭.

### 1-B. 코드 업로드 (초보자용: 웹 업로드 방식)
Git 명령어가 익숙하지 않다면, 웹 브라우저를 통해 파일을 직접 업로드할 수 있습니다.

1. 생성된 GitHub 저장소 페이지에서 **uploading an existing file** 링크 클릭.
2. 내 PC의 프로젝트 폴더(`c:\Users\mycom\Documents\antigravity_test_1`)에 있는 **모든 파일**을 드래그 앤 드롭합니다.
   - **주의**: `.streamlit` 폴더는 통째로 드래그하세요. 단, `.gitignore` 설정 덕분에 `secrets.toml` 파일은 업로드되지 않아야 정상입니다. (보안상 중요!)
3. 아래 **Commit changes** 버튼 클릭.

---

## 2. 어디서나 개발하기 (GitHub Codespaces)

이제 집, 회사, PC방 어디서든 개발 환경을 열 수 있습니다.

1. GitHub 저장소 메인 페이지에서 **Code** (초록색 버튼) -> **Codespaces** 탭 클릭.
2. **Create codespace on main** 버튼 클릭.
3. 브라우저에 VS Code와 유사한 편집기가 열립니다.
4. (선택) 터미널(하단)에서 라이브러리 설치:
   ```bash
   pip install -r requirements.txt
   ```
5. 파일 수정 후, 좌측 **Source Control** 아이콘을 통해 변경사항을 Commit & Push 하여 저장합니다.

---

## 3. 전 세계에 배포하기 (Streamlit Cloud)

만든 앱을 인터넷 주소(URL)로 누구나 접속하게 할 수 있습니다.

1. [Streamlit Cloud](https://streamlit.io/cloud)에 접속 및 GitHub 계정으로 로그인.
2. **New app** 버튼 클릭.
3. **Use existing repo** 선택 후, 방금 만든 GitHub 저장소(`stock-analysis-app`) 선택.
4. **Main file path**에 `app.py` 입력.
5. **Deploy!** 버튼 클릭.

### 🔑 중요: API 키 설정 (Secrets)
배포된 앱에서 Gemini AI 기능을 쓰려면 API 키를 클라우드에 등록해야 합니다.

1. 배포된 앱 화면 우측 하단 **Manage app** -> 우측 상단 **Settings** (점 3개) -> **Secrets**.
2. 아래 내용을 복사해서 붙여넣고 저장하세요.
   ```toml
   [gemini]
   api_key = "여기에_원래_쓰던_API_키를_넣으세요"
   ```
   *(참고: 내 PC의 `.streamlit/secrets.toml` 파일을 열어 키를 확인할 수 있습니다.)*

3. 앱이 자동으로 재실행되며 정상 작동합니다.

---

## 요약
- **개발**: GitHub Codespaces (브라우저 편집기)
- **배포/실행**: Streamlit Cloud (웹사이트 URL)
- **코드 저장**: GitHub Repository
