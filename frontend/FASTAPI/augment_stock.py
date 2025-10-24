import pandas as pd
import numpy as np

# 1️⃣ 원본 데이터 로드
df = pd.read_excel("stock.xlsx")

# 2️⃣ 각 등급별 최소 데이터 개수 설정
TARGET_PER_CLASS = 10  # 각 등급당 최소 10개씩

augmented = df.copy()
numeric_cols = df.select_dtypes(include=np.number).columns

# 3️⃣ 등급별 샘플 확장
for rating, group in df.groupby("credit_ratings"):
    count = len(group)
    if count < TARGET_PER_CLASS:
        need = TARGET_PER_CLASS - count
        print(f"{rating} 등급 → 더미 {need}개 생성")
        for _ in range(need):
            sample = group.sample(1, replace=True)
            dummy = sample.copy()
            dummy["company_name"] = sample["company_name"].iloc[0] + "_dummy_" + str(np.random.randint(1000))
            for col in numeric_cols:
                dummy[col] = sample[col].iloc[0] * np.random.uniform(0.85, 1.15)
            augmented = pd.concat([augmented, dummy], ignore_index=True)

# 4️⃣ 섞기 및 저장
augmented = augmented.sample(frac=1, random_state=42).reset_index(drop=True)
augmented.to_excel("stock_augmented.xlsx", index=False)
print("✅ stock_augmented.xlsx 생성 완료 (총 데이터 수:", len(augmented), ")")
