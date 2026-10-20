# 데이터 출처 및 라이선스

확보일: 2026-10-14. 파일별 크기·SHA-256은 [file_inventory.md](file_inventory.md)에 있다.

## A. NASA PCoE Li-ion Battery Aging Dataset

- 공식 페이지: https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/pcoe/pcoe-data-set-repository/
- ZIP: https://phm-datasets.s3.amazonaws.com/NASA/5.+Battery+Data+Set.zip
- 확보 방식: 사용자가 미리 받아 둔 `5.+Battery+Data+Set.zip`(209,708,670 bytes)을 사용. 파일명과 크기는 공식 ZIP과 같지만, 공식 서버의 해시값과는 대조하지 않았다(NASA가 해시를 공개하지 않음). ZIP 내부 CRC 검사는 바깥 ZIP과 안쪽 ZIP 6개 모두 통과했다.
- 권장 인용: B. Saha and K. Goebel (2007). "Battery Data Set", NASA Prognostics Data Repository, NASA Ames Research Center, Moffett Field, CA.
- 라이선스: ZIP 안에 라이선스 파일은 없다. NASA PCoE 저장소는 공개 데이터로 배포되며, 사용할 때 위 형식으로 인용한다.

## B. 실차 10대 충전 시험 데이터 (EV10)

- 저장소: https://github.com/BatICM/Charging-test-data-of-in-service-electric-vehicles
- 커밋: `4882ba95861a278f23b72398c5aeaf8ab71b1ac1` (2025-10-31)
- 논문: Z. Deng, L. Xu, H. Liu, X. Hu, B. Wang, J. Zhou, "Rapid health estimation of in-service battery packs based on limited labels and domain adaptation", *Journal of Energy Chemistry* 89 (2024) 345–354. DOI 10.1016/j.jechem.2023.10.056
- 라이선스: 저장소에 LICENSE 파일이 **없다**. README에 "학술·비상업적 연구 목적으로만 공유하며, 그 밖의 용도는 제1저자(Prof. Zhongwei Deng)에게 문의"라고 적혀 있다.

## C. 실차 20대 장기 충전 데이터 (EV20)

- 저장소: https://github.com/BatICM/battery-charging-data-of-on-road-electric-vehicles
- 커밋: `36fef4bd99f626561e2d138a40ccff3d1f3ddfc2` (2025-03-31)
- 논문: Z. Deng, L. Xu, H. Liu, X. Hu, Z. Duan, Y. Xu, "Prognostics of battery capacity based on charging data and data-driven methods for on-road vehicles", *Applied Energy* 339 (2023) 120954.
- 라이선스: MIT License (Copyright (c) 2023 Michael Teng). README에 "이 데이터로 다른 연구를 하면 위 논문을 인용해야 한다"고 적혀 있다.
- 차량 정보(README 기준): BAIC EU500, CATL NCM 셀, 90직렬, 공칭 145 Ah, 팩 내부 온도센서 32개.
