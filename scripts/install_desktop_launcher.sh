#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -n "${HOMEBASE_DESKTOP_DIR:-}" ]]; then
  DESKTOP_DIR="$HOMEBASE_DESKTOP_DIR"
elif command -v xdg-user-dir >/dev/null 2>&1; then
  DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
fi
DESKTOP_DIR="${DESKTOP_DIR:-$HOME/Desktop}"
APPLICATIONS_DIR="${HOMEBASE_APPLICATIONS_DIR:-$HOME/.local/share/applications}"

case "$PROJECT_DIR" in
  *$'\n'*|*\"*|*%*)
    echo "프로젝트 경로에 데스크톱 실행 아이콘이 처리할 수 없는 문자(줄바꿈, 큰따옴표, %)가 있습니다." >&2
    exit 1
    ;;
esac

mkdir -p "$DESKTOP_DIR" "$APPLICATIONS_DIR"
chmod +x "$PROJECT_DIR/homebase" "$PROJECT_DIR/run_app.sh" "$PROJECT_DIR/scripts/pi_control.sh"

install_launcher() {
  local file_name="$1"
  local english_name="$2"
  local korean_name="$3"
  local korean_comment="$4"
  local action="$5"
  local icon="$6"
  local pause="${7:-0}"
  local pause_arg=""
  local desktop_file="$DESKTOP_DIR/$file_name"
  local application_file="$APPLICATIONS_DIR/$file_name"

  if [[ "$pause" == "1" ]]; then
    pause_arg=" --pause"
  fi

  cat > "$desktop_file" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=$english_name
Name[ko]=$korean_name
Comment=$korean_comment
Exec=/bin/bash "$PROJECT_DIR/scripts/pi_control.sh" $action$pause_arg
Path=$PROJECT_DIR
Icon=$icon
Terminal=true
StartupNotify=true
Categories=Utility;
EOF

  chmod +x "$desktop_file"
  cp "$desktop_file" "$application_file"
  chmod +x "$application_file"

  if command -v gio >/dev/null 2>&1; then
    gio set "$desktop_file" metadata::trusted true >/dev/null 2>&1 || true
  fi
}

install_launcher \
  "Homebase Camera.desktop" \
  "Homebase Camera" \
  "Homebase 전체 실행" \
  "카메라와 대시보드를 시작합니다" \
  "start" \
  "camera-video"

install_launcher \
  "Homebase Zone Editor.desktop" \
  "Homebase Zone Editor" \
  "Homebase 라이브 조닝" \
  "실시간 영상을 보면서 좌석 구역을 편집합니다" \
  "zones" \
  "applications-graphics"

install_launcher \
  "Homebase Health.desktop" \
  "Homebase Health Check" \
  "Homebase 상태 점검" \
  "서비스, 카메라, 프레임, 분석 상태를 점검합니다" \
  "health" \
  "utilities-system-monitor" \
  "1"

install_launcher \
  "Homebase Empty Baseline.desktop" \
  "Homebase Empty Baseline" \
  "Homebase 빈 기준 저장" \
  "모든 좌석이 비었을 때 기준 이미지를 저장합니다" \
  "baseline" \
  "camera-photo" \
  "1"

install_launcher \
  "Homebase Logs.desktop" \
  "Homebase Live Logs" \
  "Homebase 실시간 로그" \
  "카메라 서비스 로그를 실시간으로 표시합니다" \
  "logs" \
  "text-x-log"

install_launcher \
  "Homebase Restart.desktop" \
  "Restart Homebase Camera" \
  "Homebase 전체 재시작" \
  "카메라와 대시보드 서비스를 재시작합니다" \
  "restart" \
  "view-refresh" \
  "1"

install_launcher \
  "Homebase Stop.desktop" \
  "Stop Homebase Camera" \
  "Homebase 전체 종료" \
  "카메라와 대시보드 서비스를 종료합니다" \
  "stop" \
  "process-stop" \
  "1"

install_launcher \
  "Homebase Menu.desktop" \
  "Homebase Camera Menu" \
  "Homebase 실행 메뉴" \
  "전체 기능을 번호로 선택해서 실행합니다" \
  "menu" \
  "preferences-system"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true
fi

echo
echo "Homebase Camera 실행 아이콘 설치 완료"
echo "바탕화면: $DESKTOP_DIR"
echo "애플리케이션 메뉴: $APPLICATIONS_DIR"
echo
echo "바탕화면에서 'Homebase 전체 실행' 아이콘을 더블클릭하세요."
echo "처음 실행할 때 확인 창이 나오면 '실행' 또는 '실행 허용'을 선택하세요."
