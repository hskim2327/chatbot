# Local Data Folder

이 폴더에는 원본 RFP, 평가 CSV, PDF 변환본처럼 용량이 크거나 공유 방식이 별도로 정해진 데이터를 로컬에만 배치합니다.

GitHub에는 데이터 파일을 올리지 않습니다.

권장 배치 예시는 아래와 같습니다.

```text
data/
├─ eval/
│  └─ eval_batch_01.csv ~ eval_batch_25.csv
├─ original_data_list/
│  └─ files_advanced/
└─ pdf_186/
```

노트북을 Colab/GCP에서 실행할 때는 같은 구조를 Google Drive 또는 VM 디스크에 만든 뒤, 노트북 상단의 `PROJECT_ROOT_OVERRIDE`만 해당 경로로 맞춥니다.
