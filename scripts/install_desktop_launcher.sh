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
    echo "프로젝트 경로에 실행 아이콘에서 처리할 수 없는 문자가 있습니다." >&2
    exit 1
    ;;
esac

mkdir -p "$DESKTOP_DIR" "$APPLICATIONS_DIR"
chmod +x "$PROJECT_DIR/homebase" "$PROJECT_DIR/run_app.sh" "$PROJECT_DIR/scripts/pi_control.sh"

install_launcher() {
  local file_name="$1" english_name="$2" korean_name="$3" comment="$4" action="$5" icon="$6" pause="${7:-0}"
  local pause_arg="" desktop_file="$DESKTOP_DIR/$file_name" application_file="$APPLICATIONS_DIR/$file_name"
  [[ "$pause" == "1" ]] && pause_arg=" --pause"
  cat > "$desktop_file" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=$english_name
Name[ko]=$korean_name
Comment=$comment
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
  command -v gio >/dev/null 2>&1 && gio set "$desktop_file" metadata::trusted true >/dev/null 2>&1 || true
}

install_launcher "Homebase Camera.desktop" "Homebase Camera" "Homebase 전체 실행" "카메라와 대시보드를 시작합니다" "start" "camera-video"
install_launcher "Homebase Presentation.desktop" "Homebase Presentation" "Homebase 발표 화면" "읽기 전용 실시간 좌석 현황을 엽니다" "presentation" "video-display"
install_launcher "Homebase Seat Demo.desktop" "Homebase Seat Demo" "Homebase 좌석 데모" "5개 좌석의 실시간 점유 변화만 표시합니다" "seats" "view-grid"
install_launcher "Homebase Preflight.desktop" "Homebase Presentation Check" "Homebase 발표 사전 점검" "카메라, 스트림, 판정 모델과 데이터베이스를 점검합니다" "doctor" "dialog-information" "1"
install_launcher "Homebase Zone Editor.desktop" "Homebase Zone Editor" "Homebase 좌석 구역 편집" "실시간 영상에서 좌석 구역을 편집합니다" "zones" "applications-graphics"
install_launcher "Homebase Health.desktop" "Homebase Health Check" "Homebase 상태 점검" "서비스와 카메라 상태를 출력합니다" "health" "utilities-system-monitor" "1"
install_launcher "Homebase Empty Baseline.desktop" "Homebase Empty Baseline" "Homebase 빈 좌석 기준 저장" "모든 좌석이 빈 현재 화면을 기준 이미지로 저장합니다" "baseline" "camera-photo" "1"
install_launcher "Homebase Logs.desktop" "Homebase Live Logs" "Homebase 실시간 로그" "서비스 로그를 실시간으로 표시합니다" "logs" "text-x-log"
install_launcher "Homebase Restart.desktop" "Restart Homebase Camera" "Homebase 전체 재시작" "카메라와 대시보드 서비스를 재시작합니다" "restart" "view-refresh" "1"
install_launcher "Homebase Stop.desktop" "Stop Homebase Camera" "Homebase 전체 종료" "카메라와 대시보드 서비스를 종료합니다" "stop" "process-stop" "1"
install_launcher "Homebase Menu.desktop" "Homebase Camera Menu" "Homebase 실행 메뉴" "모든 기능을 번호로 선택합니다" "menu" "preferences-system"

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true

echo "Homebase Camera 실행 아이콘 설치 완료"
echo "바탕화면: $DESKTOP_DIR"
echo "애플리케이션 메뉴: $APPLICATIONS_DIR"
