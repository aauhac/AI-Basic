# nasa — 압축 해제본

- 압축 원본: 상위 작업 폴더의 `5.+Battery+Data+Set.zip` (209,708,670 bytes, 수정하지 않음)
- 추출: `python -I src/data/extract_nasa.py "../5.+Battery+Data+Set.zip"`
  - 바깥 ZIP 안의 ZIP 6개를 메모리에서 읽어 하위 폴더별로 추출
  - 2번·3번 ZIP에 똑같이 들어 있는 B0025~B0028(SHA-256 동일)은 2번 폴더에만 저장
- `manifest.json`: 추출한 파일별 크기·SHA-256과 생략한 중복 파일 목록
- 고유 셀 34개: B0005–B0007, B0018, B0025–B0034, B0036, B0038–B0056 (B0035·B0037은 원본에 없음)
