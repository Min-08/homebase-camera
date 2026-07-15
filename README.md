# Homebase Camera

라즈베리파이 카메라 한 대로 좌석별 사람 유무를 실시간 표시하는 프로젝트입니다.
얼굴 인식이나 개인 식별은 하지 않습니다.

## 판정 기준

상태는 두 개뿐입니다.

```text
0 = 사람 없음
1 = 사람 있음
```

최종 상태 `1`은 YOLO 사람 검출 결과가 좌석 구역과 겹칠 때만 발생합니다. 픽셀 변화는
사람 검사를 빨리 호출하는 신호로만 사용하며, 손·가방·책 같은 물체만으로는 `1`이 되지
않습니다. YOLO가 실행되지 않았거나 기준 이미지가 유효하지 않으면 기존 상태를 보존하고
화면에 `판정 보류`를 표시합니다.

판정 흐름:

```text
카메라 프레임
  -> 빈 좌석 기준 이미지와 빠른 변화 비교(기본 1초)
  -> 변화 발생 또는 기존 점유 좌석이면 비동기 YOLO 사람 검사
  -> 사람 박스의 중심·하체 기준점·좌석 겹침으로 좌석 배정
  -> 0/1 안정화 후 SQLite 저장
  -> MJPEG, 발표 화면, Streamlit 화면에 공유
```

YOLO는 별도 작업 스레드에서 실행되므로 추론 중에도 카메라 스트림과 빠른 변화 검사가
멈추지 않습니다.

## 라즈베리파이 설치

```bash
git clone https://github.com/Min-08/homebase-camera.git
cd homebase-camera
chmod +x setup_raspberry_pi.sh homebase scripts/*.sh
./setup_raspberry_pi.sh --install-system-packages --install-yolo-model --install-launchers
```

기존 설치를 갱신할 때:

```bash
cd ~/homebase-camera
git pull
./setup_raspberry_pi.sh --install-yolo-model --install-launchers
```

모델 설치기는 고정된 ONNX 파일을 내려받고 SHA-256을 검증합니다. 모델 바이너리는 Git에
포함하지 않습니다.

## 원클릭 실행

라즈베리파이 바탕화면의 주요 아이콘:

- **Homebase Camera**: 전체 서비스와 대시보드 실행
- **Homebase Presentation**: 조작 버튼이 없는 발표 전용 화면
- **Homebase Presentation Check**: 카메라, 프레임, 분석, 구역, 기준 이미지, YOLO, DB 점검
- **Homebase Zone Editor**: 실시간 영상 위에 좌석 다각형 편집
- **Homebase Empty Baseline**: 모든 좌석이 비었을 때 기준 이미지 저장
- **Homebase Health**: 상세 실행 상태 확인
- **Homebase Restart / Stop / Logs**: 재시작, 종료, 로그 확인

터미널에서도 같은 기능을 실행할 수 있습니다.

```bash
./homebase                         # 전체 실행
./homebase presentation            # 발표 화면
./homebase doctor                  # 발표 사전 점검
./homebase zones                   # 좌석 구역 편집
./homebase baseline                # 빈 좌석 기준 이미지 저장
./homebase health                  # 상세 상태
./homebase restart                 # 재시작
./homebase logs                    # 실시간 로그
./homebase stop                    # 종료
```

## 접속 주소

같은 네트워크의 PC에서 `<PI-IP>`를 라즈베리파이 주소로 바꿉니다.

```text
대시보드:       http://<PI-IP>:8501/
발표 화면:      http://<PI-IP>:8502/presentation
좌석 구역 편집: http://<PI-IP>:8502/zone-editor
사전 점검 API:  http://<PI-IP>:8502/api/preflight
상태 API:       http://<PI-IP>:8502/api/status
MJPEG 스트림:   http://<PI-IP>:8502/stream.mjpg
```

RealVNC로 파이 화면을 직접 조작해도 되고, 다른 PC 브라우저에서 위 주소를 열어도 됩니다.

### 유선 직결

```bash
sudo ./scripts/configure_direct_ethernet.sh
```

Windows Ethernet IPv4를 `192.168.250.1/24`로 설정한 뒤 다음 주소를 사용합니다.

```text
RealVNC:        192.168.250.2
대시보드:       http://192.168.250.2:8501/
발표 화면:      http://192.168.250.2:8502/presentation
```

PoE HAT/허브 구성에서도 네트워크 인터페이스에 IP가 할당되면 동일하게 접속합니다.

## 최초 카메라 설정

1. 카메라가 실제 좌석 전체를 보도록 단단히 고정합니다.
2. `./homebase zones`에서 각 좌석의 앉는 영역을 다각형으로 지정합니다.
3. 모든 좌석과 구역이 빈 상태인지 직접 확인합니다.
4. `./homebase baseline`으로 기준 이미지를 저장합니다.
5. `./homebase doctor`가 `발표 준비 완료`를 출력하는지 확인합니다.

카메라 위치, 해상도, 조명 방향이 바뀌면 구역과 기준 이미지를 다시 설정해야 합니다.
흰색·검은색 빈 파일은 기준 이미지로 인정하지 않습니다.

## 발표 직전 체크리스트

```bash
./homebase restart
./homebase doctor
```

- 실제 카메라 화면이 현재 교실을 향하는지 확인
- 모든 좌석이 빈 상태에서 전부 `0`인지 확인
- 각 좌석에 한 명씩 앉아 `1`로 바뀌는지 확인
- 사람이 나간 뒤 `0`으로 복귀하는지 확인
- 가방만 올렸을 때 `0`을 유지하는지 확인
- 발표 PC에서 스트림이 30초 이상 끊기지 않는지 확인
- 파이 온도가 75 C 미만인지 확인

`doctor`가 실패하면 발표 화면도 상단에 `점검 필요`를 표시합니다. 기준 장면이 어긋난
상태에서는 이전 숫자를 확정 결과처럼 보여주지 않고 `판정 보류`로 가립니다.

## PC 데모

Windows:

```bat
setup_pc.bat
run_demo.bat
```

macOS/Linux:

```bash
./setup_pc.sh
./run_demo.sh
```

데모는 하드웨어 없이 화면 흐름과 구역 편집을 시연하기 위한 합성 자료입니다. 실제 정확도
근거로 사용하지 않습니다. 데모 이미지와 타임라인 재생성:

```bash
python tools/generate_demo_assets.py --force
```

## 주요 설정

`config/settings.toml`:

```toml
[detection]
diff_interval_seconds = 1
yolo_enabled = true
yolo_interval_seconds = 8
yolo_model = "data/models/yolov8n.onnx"
empty_required_hits = 2
person_required_hits = 1
person_confidence_threshold = 0.25
diff_threshold = 30
change_ratio_threshold = 0.04

[streaming]
fps = 10
jpeg_quality = 75
```

설정을 바꾼 뒤 서비스를 재시작합니다. `yolo_interval_seconds`는 변화가 지속되는 동안의
최소 재검사 간격이며, 변화가 새로 발생하면 즉시 검사를 요청합니다.

## 데이터와 개인정보

- 원본 영상 녹화 없음
- 얼굴 인식 및 신원 식별 없음
- 상태 변화는 로컬 SQLite에 저장
- 스냅샷 저장은 `[privacy].save_snapshots = false`로 끌 수 있음
- 공유 공간에서는 카메라 안내문과 운영 기관의 개인정보 규정을 확인해야 함

## 개발 검증

```bash
python -m pytest -q
python -m compileall -q app.py homebase_camera tools tests
git diff --check
bash -n homebase setup_raspberry_pi.sh run_app.sh run_mock.sh setup_pc.sh run_demo.sh \
  scripts/pi_control.sh scripts/install_desktop_launcher.sh scripts/configure_direct_ethernet.sh
```

시험 근거와 남은 물리 검증 항목은 `docs/simulation_report.md`에 기록합니다.

## 제한 사항

- 사람 검출 모델은 가림, 역광, 매우 작은 사람, 좌석 밖에 서 있는 사람을 놓칠 수 있습니다.
- 카메라가 움직이거나 기준 장면이 바뀌면 판정을 보류하고 재설정을 요구합니다.
- 라즈베리파이 4B CPU 추론은 GPU 장비보다 느립니다.
- 최종 발표 전에는 실제 설치 각도에서 좌석별 입장·퇴장·가방 테스트가 반드시 필요합니다.
- 모델 및 관련 소프트웨어의 라이선스는 배포 목적에 맞게 별도로 확인해야 합니다.
