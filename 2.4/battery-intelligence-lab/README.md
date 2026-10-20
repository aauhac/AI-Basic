# Battery Intelligence Lab — NASA 데이터 기반 리튬이온 배터리 SOH·RUL 예측과 실차 적용

AI기초프로젝트 레벨 2 (2.4).

NASA 배터리 노화 데이터(B0005·B0006·B0007·B0018)로 SOH·RUL 회귀 모델 5종을 만들어 비교하고, 같은 모델을 실제 전기차 데이터(EV10, EV20)에 적용해 본 프로젝트다. Linear Regression, Random Forest, SVR, XGBoost, Stacking을 사용했다.

## 먼저 읽을 문서
| 문서 | 내용 |
|---|---|
| [docs/project_final_summary.md](docs/project_final_summary.md) | 최종 요약 |
| [docs/presentation_outline.md](docs/presentation_outline.md) | 발표 구성안 (12장) |
| [docs/experiment_report.md](docs/experiment_report.md) | NASA SOH·RUL 실험 보고서 (감사 반영본) |
| [docs/transfer_experiment_report.md](docs/transfer_experiment_report.md) | NASA → 실차 정규화·보정 확장 실험 |
| [docs/final_validation_report.md](docs/final_validation_report.md) | 최종 검증 (충전 진행률 좌표, IR 보정 타당성) |
| [docs/dataset_report.md](docs/dataset_report.md), [docs/data_sources.md](docs/data_sources.md) | 데이터 구조, 출처, 라이선스 |

## 주요 결과
| 항목 | 결과 |
|---|---|
| NASA 현재 SOH, 시간순 분할 | 학습 데이터로 선정한 Linear Regression MAE 0.0239 |
| NASA 현재 SOH, 미학습 배터리 | 학습 데이터로 선정한 모델 평균 MAE 0.0374 |
| NASA 모델 → EV10 실차 (9대) | MAE 0.2187, 정규화 후 0.2451 (개선되지 않음, 기준선 0.1388) |
| EV20 장기 기록 | 감소 추세 방향만 일치, SOH 값 추정에는 쓸 수 없음 |

## 폴더 구성
```
src/            데이터 로더, 특징 추출, 모델(zoo.py), 검증·선정·RUL 도구
experiments/    실험 스크립트 (run_all.py가 전체를 순서대로 실행)
tests/          자동 테스트 (55개)
results/        실험 결과 CSV·JSON·그래프·로그, runtime.json
results_archive/ 단계별 결과 보관본 (감사 전, 전이 실험 전, 최종 검증 전)
data/processed/ 원본에서 계산한 특징·세션 표
docs/           보고서
```

## 실행 방법
원본 데이터는 용량과 라이선스(EV10: 학술·비상업 연구용) 때문에 저장소에 포함하지 않았다. 출처는 [docs/data_sources.md](docs/data_sources.md)에 있다.

1. **NASA:** `5.+Battery+Data+Set.zip`을 이 폴더의 상위 폴더에 두고 아래 명령으로 추출한다.
   ```
   python -I src/data/extract_nasa.py "../5.+Battery+Data+Set.zip"
   ```
2. **EV10, EV20:** 아래 두 GitHub 저장소를 `external/` 아래에 clone한다. EV20의 `#N.rar`은 `data/raw/ev_20/`에 압축을 푼다.
   - `BatICM/Charging-test-data-of-in-service-electric-vehicles`
   - `BatICM/battery-charging-data-of-on-road-electric-vehicles`
3. **환경 구성과 실행:** Python 3.12 기준.
   ```
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   .venv\Scripts\python -m experiments.run_all
   ```
   전체 실행에 CPU 기준 약 14분이 걸린다.
