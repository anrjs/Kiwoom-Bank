from api.credit_model import load_feature_rows, predict_from_dataframe, find_latest_feature_file

company = "삼성전자"
feature_file = find_latest_feature_file(company)

if feature_file is None:
    raise FileNotFoundError(f"❌ feature file not found for {company}")

print(f"📄 사용한 피처 파일: {feature_file}")
df = load_feature_rows(feature_file)
predictions = predict_from_dataframe(df)

print("\n✅ CatBoost 모델 예측 결과:")
for pred in predictions:
    print(pred)