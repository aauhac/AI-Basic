# ev_20 — 압축 해제본

- 압축 원본: `external/battery-charging-data-of-on-road-electric-vehicles/#1.rar` ~ `#20.rar` (Git 저장소에 그대로 보존)
- 이 폴더: 각 RAR에서 Windows 기본 `tar`(bsdtar 3.8.8)로 추출한 `#N.csv` 20개 (총 약 1.09 GB)
- 로더: `src/data/ev20.py`
- 재추출: `tar -xf "external/battery-charging-data-of-on-road-electric-vehicles/#N.rar" -C data/raw/ev_20`
