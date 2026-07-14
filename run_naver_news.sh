#!/bin/bash
# Script to run the main news analysis script in an isolated environment
# This script must be executable (chmod +x)

# 1. 가상환경 활성화
source /home/chlwodud0327/workspaces/MAIL_NAVER_NEWS/.venv/bin/activate

# 2. 현재 스크립트 디렉토리로 이동 (실행 안정성 확보)
cd /home/chlwodud0327/workspaces/MAIL_NAVER_NEWS

# 3. Python 스크립트 실행
# 이 실행은 스크립트의 모든 로직 (DB 초기화, 수집, 분석, DB 기록)을 실행합니다.
python main.py

# 4. 가상환경 비활성화
deactivate
exit 0