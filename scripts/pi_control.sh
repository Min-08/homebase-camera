#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_NAME="${HOMEBASE_SERVICE_NAME:-homebase-camera.service}"
DASHBOARD_URL="${HOMEBASE_DASHBOARD_URL:-http://127.0.0.1:8501}"
LIVE_URL="${HOMEBASE_LIVE_URL:-http://127.0.0.1:8502}"
PID_FILE="$PROJECT_DIR/data/homebase-camera.pid"
LOG_FILE="$PROJECT_DIR/data/homebase-camera-launcher.log"

ACTION="${1:-start}"
if [[ "$#" -gt 0 ]]; then
  shift
fi

PAUSE_ON_EXIT=0
for arg in "$@"; do
  case "$arg" in
    --pause)
      PAUSE_ON_EXIT=1
      ;;
    -h|--help)
      ACTION="help"
      ;;
    *)
      echo "알 수 없는 옵션: $arg" >&2
      exit 2
      ;;
  esac
done

pause_before_close() {
  local exit_code=$?
  if [[ "$PAUSE_ON_EXIT" == "1" ]]; then
    echo
    read -r -p "창을 닫으려면 Enter 키를 누르세요..." _ || true
  fi
  return "$exit_code"
}
trap pause_before_close EXIT

info() {
  printf '[Homebase] %s\n' "$*"
}

warn() {
  printf '[Homebase 경고] %s\n' "$*" >&2
}

die() {
  printf '[Homebase 오류] %s\n' "$*" >&2
  exit 1
}

show_help() {
  cat <<'EOF'
Homebase Camera Raspberry Pi 실행 도구

사용법:
  ./homebase [명령]

명령:
  start       전체 시스템을 시작하고 대시보드를 엽니다. (기본값)
  zones       라이브 조닝 편집기를 엽니다.
  health      서비스, 카메라, 프레임, 분석 상태를 점검합니다.
  baseline    현재 빈 좌석 화면을 기준 이미지로 저장합니다.
  logs        실시간 서비스 로그를 표시합니다.
  restart     전체 시스템을 재시작하고 대시보드를 엽니다.
  stop        전체 시스템을 종료합니다.
  menu        위 명령을 선택할 수 있는 메뉴를 엽니다.
  help        이 도움말을 표시합니다.

예:
  ./homebase
  ./homebase zones
  ./homebase health
EOF
}

require_curl() {
  command -v curl >/dev/null 2>&1 || die "curl이 없습니다. sudo apt install curl 명령으로 설치하세요."
}

has_systemd_service() {
  command -v systemctl >/dev/null 2>&1 && systemctl cat "$SERVICE_NAME" >/dev/null 2>&1
}

service_is_active() {
  has_systemd_service && systemctl is-active --quiet "$SERVICE_NAME"
}

run_systemctl() {
  local operation="$1"
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    systemctl "$operation" "$SERVICE_NAME"
  elif command -v sudo >/dev/null 2>&1; then
    if sudo -n true >/dev/null 2>&1; then
      sudo -n systemctl "$operation" "$SERVICE_NAME"
    else
      info "서비스 제어를 위해 Raspberry Pi 암호를 입력하세요."
      sudo systemctl "$operation" "$SERVICE_NAME"
    fi
  else
    die "서비스를 $operation 하려면 root 권한 또는 sudo가 필요합니다."
  fi
}

fallback_is_active() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  local command_line
  pid="$(tr -dc '0-9' < "$PID_FILE")"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" >/dev/null 2>&1 || return 1
  command_line="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  [[ "$command_line" == *"streamlit run app.py"* || "$command_line" == *"$PROJECT_DIR/run_app.sh"* ]]
}

start_backend() {
  mkdir -p "$PROJECT_DIR/data"

  if service_is_active; then
    stop_fallback
    info "systemd 서비스가 이미 실행 중입니다."
    return
  fi

  if has_systemd_service; then
    stop_fallback
    info "systemd 서비스를 시작합니다."
    run_systemctl start
    return
  fi

  if fallback_is_active; then
    info "직접 실행 프로세스가 이미 실행 중입니다."
    return
  fi

  [[ -x "$PROJECT_DIR/run_app.sh" ]] || die "run_app.sh 실행 권한이 없습니다. ./setup_raspberry_pi.sh를 먼저 실행하세요."
  [[ -x "$PROJECT_DIR/.venv/bin/python" ]] || die ".venv가 없습니다. ./setup_raspberry_pi.sh를 먼저 실행하세요."

  info "systemd 서비스가 없어 백그라운드에서 직접 실행합니다."
  nohup "$PROJECT_DIR/run_app.sh" >> "$LOG_FILE" 2>&1 &
  echo "$!" > "$PID_FILE"
}

stop_fallback() {
  if ! fallback_is_active; then
    rm -f "$PID_FILE"
    return
  fi

  local pid
  pid="$(tr -dc '0-9' < "$PID_FILE")"
  info "직접 실행 프로세스(PID $pid)를 종료합니다."
  kill "$pid" >/dev/null 2>&1 || true

  for _ in {1..20}; do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      break
    fi
    sleep 0.25
  done
  rm -f "$PID_FILE"
}

stop_backend() {
  if service_is_active; then
    info "systemd 서비스를 종료합니다."
    run_systemctl stop
  fi
  stop_fallback
}

restart_backend() {
  if has_systemd_service; then
    info "systemd 서비스를 재시작합니다."
    run_systemctl restart
  else
    stop_fallback
    start_backend
  fi
}

url_is_ready() {
  curl --fail --silent --show-error --max-time 2 "$1" >/dev/null 2>&1
}

wait_for_url() {
  local url="$1"
  local label="$2"
  local timeout_seconds="${3:-45}"
  local deadline=$((SECONDS + timeout_seconds))

  while (( SECONDS < deadline )); do
    if url_is_ready "$url"; then
      info "$label 준비 완료"
      return 0
    fi
    sleep 1
  done
  return 1
}

open_url() {
  local url="$1"

  if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    warn "그래픽 데스크톱 세션을 찾지 못했습니다. 브라우저에서 직접 여세요: $url"
    return 1
  fi

  if command -v xdg-open >/dev/null 2>&1; then
    nohup xdg-open "$url" >/dev/null 2>&1 &
    return 0
  fi
  if command -v gio >/dev/null 2>&1; then
    nohup gio open "$url" >/dev/null 2>&1 &
    return 0
  fi

  warn "브라우저 실행 명령을 찾지 못했습니다. 직접 여세요: $url"
  return 1
}

ensure_dashboard() {
  require_curl
  start_backend
  wait_for_url "$DASHBOARD_URL/_stcore/health" "대시보드" 60 || {
    if [[ -f "$LOG_FILE" ]]; then
      tail -n 30 "$LOG_FILE" >&2 || true
    fi
    die "대시보드가 60초 안에 시작되지 않았습니다. ./homebase logs로 로그를 확인하세요."
  }
}

ensure_live_service() {
  ensure_dashboard
  if url_is_ready "$LIVE_URL/health"; then
    return
  fi

  info "카메라 공유 서비스를 깨우기 위해 대시보드를 엽니다."
  open_url "$DASHBOARD_URL/" || true
  wait_for_url "$LIVE_URL/health" "카메라 공유 서비스" 45 || \
    die "카메라 공유 서비스가 시작되지 않았습니다. 대시보드를 한 번 연 뒤 ./homebase health를 실행하세요."
}

pretty_json_url() {
  local url="$1"
  if [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
    curl --fail --silent --show-error --max-time 5 "$url" | "$PROJECT_DIR/.venv/bin/python" -m json.tool
  else
    curl --fail --silent --show-error --max-time 5 "$url"
    echo
  fi
}

start_action() {
  ensure_dashboard
  info "대시보드를 엽니다: $DASHBOARD_URL/"
  if open_url "$DASHBOARD_URL/"; then
    if ! wait_for_url "$LIVE_URL/health" "카메라 공유 서비스" 45; then
      warn "대시보드는 실행됐지만 카메라 공유 서비스 확인이 지연되고 있습니다. ./homebase health로 확인하세요."
    fi
  fi
}

zones_action() {
  ensure_live_service
  info "라이브 조닝 편집기를 엽니다: $LIVE_URL/zone-editor"
  open_url "$LIVE_URL/zone-editor" || true
}

presentation_action() {
  ensure_live_service
  info "발표 전용 화면을 엽니다: $LIVE_URL/presentation"
  open_url "$LIVE_URL/presentation" || true
}

seat_demo_action() {
  ensure_live_service
  info "5석 좌석 데모를 엽니다: $LIVE_URL/seat-demo"
  open_url "$LIVE_URL/seat-demo" || true
}

doctor_action() {
  ensure_live_service
  echo
  echo "=== Homebase 발표 사전 점검 ==="
  curl --fail --silent --show-error --max-time 10 "$LIVE_URL/api/preflight" | \
    "$PROJECT_DIR/.venv/bin/python" -c '
import json, sys
data = json.load(sys.stdin)
def friendly(message):
    text = str(message or "")
    if "All seat zones changed heavily" in text:
        return "카메라 위치 또는 기준 이미지가 현재 장면과 다릅니다. 빈 좌석 기준 이미지를 다시 저장하세요."
    return text
for check in data.get("checks", []):
    mark = "OK" if check.get("ok") else "FAIL"
    print("[{:<4}] {}: {}".format(mark, check.get("label"), friendly(check.get("detail"))))
print("\n결과:", "발표 준비 완료" if data.get("ready") else "조치 필요")
raise SystemExit(0 if data.get("ready") else 1)
'
}

health_action() {
  ensure_dashboard

  if ! url_is_ready "$LIVE_URL/health"; then
    info "카메라 상태 확인을 위해 대시보드를 엽니다."
    open_url "$DASHBOARD_URL/" || true
    wait_for_url "$LIVE_URL/health" "카메라 공유 서비스" 20 || true
  fi

  echo
  echo "=== 실행 상태 ==="
  if service_is_active; then
    systemctl --no-pager --full status "$SERVICE_NAME" 2>/dev/null | sed -n '1,12p' || true
  elif fallback_is_active; then
    echo "직접 실행 프로세스: 동작 중 (PID $(tr -dc '0-9' < "$PID_FILE"))"
  else
    echo "실행 프로세스: 확인되지 않음"
  fi

  echo
  echo "=== 대시보드 ==="
  echo "정상: $DASHBOARD_URL/"

  echo
  echo "=== 카메라/프레임/분석 상태 ==="
  if url_is_ready "$LIVE_URL/health"; then
    pretty_json_url "$LIVE_URL/health"
  else
    warn "카메라 공유 서비스가 아직 응답하지 않습니다. 대시보드를 브라우저에서 연 뒤 다시 점검하세요."
  fi

  echo
  echo "=== 좌석 상태 API ==="
  if url_is_ready "$LIVE_URL/api/status"; then
    pretty_json_url "$LIVE_URL/api/status"
  else
    warn "좌석 상태 API가 아직 응답하지 않습니다."
  fi
}

baseline_action() {
  ensure_live_service

  echo
  warn "기준 이미지를 저장할 때는 모든 좌석과 조닝 구역이 비어 있어야 합니다."
  read -r -p "현재 모든 좌석이 비어 있습니까? [y/N] " answer
  case "$answer" in
    y|Y|yes|YES|Yes)
      ;;
    *)
      info "기준 이미지 저장을 취소했습니다."
      return
      ;;
  esac

  echo
  echo "=== 기준 이미지 저장 결과 ==="
  if [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
    curl --fail --silent --show-error --max-time 15 -X POST "$LIVE_URL/api/baseline" \
      | "$PROJECT_DIR/.venv/bin/python" -m json.tool
  else
    curl --fail --silent --show-error --max-time 15 -X POST "$LIVE_URL/api/baseline"
    echo
  fi
}

logs_action() {
  if has_systemd_service; then
    info "최근 100줄부터 실시간 로그를 표시합니다. 종료: Ctrl+C"
    if journalctl --no-pager -u "$SERVICE_NAME" -n 1 >/dev/null 2>&1; then
      journalctl -u "$SERVICE_NAME" -n 100 -f
    elif command -v sudo >/dev/null 2>&1; then
      sudo journalctl -u "$SERVICE_NAME" -n 100 -f
    else
      die "서비스 로그를 읽을 권한이 없습니다."
    fi
  else
    mkdir -p "$(dirname "$LOG_FILE")"
    touch "$LOG_FILE"
    info "직접 실행 로그를 표시합니다. 종료: Ctrl+C"
    tail -n 100 -f "$LOG_FILE"
  fi
}

restart_action() {
  require_curl
  restart_backend
  wait_for_url "$DASHBOARD_URL/_stcore/health" "대시보드" 60 || \
    die "재시작 후 대시보드가 응답하지 않습니다. ./homebase logs로 확인하세요."
  open_url "$DASHBOARD_URL/" || true
}

stop_action() {
  stop_backend
  info "Homebase Camera를 종료했습니다."
}

menu_action() {
  while true; do
    cat <<'EOF'

=== Homebase Camera 실행 메뉴 ===
1. 전체 실행 / 대시보드
2. 라이브 조닝 편집기
3. 상태 점검
4. 빈 좌석 기준 이미지 저장
5. 실시간 로그
6. 전체 재시작
7. 전체 종료
0. 메뉴 닫기
EOF
    read -r -p "선택: " choice
    case "$choice" in
      1) start_action ;;
      2) zones_action ;;
      3) health_action ;;
      4) baseline_action ;;
      5) logs_action ;;
      6) restart_action ;;
      7) stop_action ;;
      0) return ;;
      *) warn "0부터 7 사이의 번호를 입력하세요." ;;
    esac
  done
}

show_help() {
  cat <<'EOF'
Homebase Camera 실행 도구

사용법:
  ./homebase [명령]

명령:
  start          전체 서비스와 대시보드 실행
  presentation   발표 전용 화면 열기
  seats          5석 좌석 데모 열기
  doctor         발표 사전 점검 실행
  zones          실시간 좌석 구역 편집기 열기
  baseline       현재 빈 좌석 화면을 기준 이미지로 저장
  health         상세 실행 상태 출력
  logs           실시간 서비스 로그 출력
  restart        전체 서비스 재시작
  stop           전체 서비스 종료
  menu           번호 선택 메뉴
  help           도움말
EOF
}

menu_action() {
  while true; do
    cat <<'EOF'

=== Homebase Camera 메뉴 ===
1. 전체 실행 / 대시보드
2. 발표 전용 화면
3. 발표 사전 점검
4. 좌석 구역 편집
5. 빈 좌석 기준 이미지 저장
6. 상세 상태
7. 실시간 로그
8. 전체 재시작
9. 전체 종료
0. 메뉴 닫기
EOF
    read -r -p "선택: " choice
    case "$choice" in
      1) start_action ;;
      2) presentation_action ;;
      3) doctor_action ;;
      4) zones_action ;;
      5) baseline_action ;;
      6) health_action ;;
      7) logs_action ;;
      8) restart_action ;;
      9) stop_action ;;
      0) return ;;
      *) warn "0부터 9 사이의 번호를 입력하세요." ;;
    esac
  done
}

case "$ACTION" in
  start) start_action ;;
  zones|zone) zones_action ;;
  presentation|present) presentation_action ;;
  seats|seat-demo|seatdemo) seat_demo_action ;;
  doctor|preflight) doctor_action ;;
  health|status|check) health_action ;;
  baseline) baseline_action ;;
  logs|log) logs_action ;;
  restart) restart_action ;;
  stop) stop_action ;;
  menu) menu_action ;;
  help|-h|--help) show_help ;;
  *)
    show_help >&2
    die "알 수 없는 명령: $ACTION"
    ;;
esac
