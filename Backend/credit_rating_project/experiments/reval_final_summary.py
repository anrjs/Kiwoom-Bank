# -*- coding: utf-8 -*-
"""
experiments/reval_final_summary.py — ACI 재검증 [5. 최종 정리]

앞 단계(1~4) 산출 CSV들을 모아 하나의 요약표로 만들고,
자소서에 쓸 때 과장이 될 수 있는 부분을 데이터 기반으로 지적합니다.

전제: 아래 파일들이 --out_dir 안에 이미 존재해야 합니다 (각 단계 스크립트 실행 후).
  - stage1_corrected_labels.csv     (reval_label_audit_crawler.py)
  - stage2_corrected_rerun_summary.csv  (reval_corrected_rerun.py)
  - stage3_histgb_baseline.csv      (reval_histgb_baseline.py)
  - stage4_accuracy_check.csv, stage4_class_counts.csv (reval_accuracy_check.py)

사용법:
  python experiments/reval_final_summary.py --out_dir experiments_out
"""
import argparse
import os

import pandas as pd


def safe_read(path):
    if not os.path.exists(path):
        print(f"  ⚠ 없음: {path} (해당 단계를 먼저 실행하세요)")
        return None
    return pd.read_csv(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", type=str, default="experiments_out")
    args = parser.parse_args()

    print("=" * 70)
    print("[5단계] 최종 정리")
    print("=" * 70)

    labels = safe_read(os.path.join(args.out_dir, "stage1_corrected_labels.csv"))
    rerun = safe_read(os.path.join(args.out_dir, "stage2_corrected_rerun_summary.csv"))
    histgb = safe_read(os.path.join(args.out_dir, "stage3_histgb_baseline.csv"))
    acc = safe_read(os.path.join(args.out_dir, "stage4_accuracy_check.csv"))
    classes = safe_read(os.path.join(args.out_dir, "stage4_class_counts.csv"))

    print("\n" + "-" * 70)
    print("1. 라벨 감사 요약")
    print("-" * 70)
    if labels is not None:
        n_total = len(labels)
        n_no_grade = labels["교정라벨"].isna().sum()
        n_compared = n_total - n_no_grade
        n_mismatch = (labels["원래라벨_교정라벨_일치"] == False).sum()  # noqa: E712
        print(f"전체 {n_total}건 / 등급없음 {n_no_grade}건 / 비교가능 {n_compared}건 중 불일치 {n_mismatch}건")

        # 투자/투기 전환 건수 계산 (RATING_ORDER 기준, BBB- 컷오프)
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from experiments.common import is_investment_grade
        comparable = labels[labels["교정라벨"].notna() & labels["원래라벨"].notna()].copy()

        def _safe_inv(x):
            try:
                return is_investment_grade(x)
            except ValueError:
                return None

        comparable["원래_투자여부"] = comparable["원래라벨"].map(_safe_inv)
        comparable["교정_투자여부"] = comparable["교정라벨"].map(_safe_inv)
        flipped = comparable[
            comparable["원래_투자여부"].notna() & comparable["교정_투자여부"].notna() &
            (comparable["원래_투자여부"] != comparable["교정_투자여부"])
        ]
        print(f"투자/투기 구분이 바뀐 건수: {len(flipped)}건")
        if len(flipped):
            print(flipped[["회사명", "원래라벨", "교정라벨"]].to_string(index=False))
    else:
        n_mismatch = n_no_grade = n_total = None

    print("\n" + "-" * 70)
    print("2. 교정 라벨 재실험 비교")
    print("-" * 70)
    if rerun is not None:
        print(rerun.to_string(index=False))

    print("\n" + "-" * 70)
    print("3. HistGradientBoosting 공정비교 베이스라인 (교정 라벨)")
    print("-" * 70)
    histgb_qwk_mean = histgb_qwk_std = None
    if histgb is not None:
        histgb_qwk_mean, histgb_qwk_std = histgb["qwk"].mean(), histgb["qwk"].std(ddof=1)
        print(f"HistGB QWK: {histgb_qwk_mean:.4f} ± {histgb_qwk_std:.4f}")
        if rerun is not None:
            catboost_corr_base = rerun[(rerun["label_set"] == "교정라벨") & (rerun["method"] == "baseline")]
            if len(catboost_corr_base):
                cb_qwk = catboost_corr_base.iloc[0]["qwk_mean"]
                print(f"CatBoost(증강+가중치+단조제약, baseline) QWK: {cb_qwk:.4f}  "
                      f"→ HistGB 대비 차이: {cb_qwk - histgb_qwk_mean:+.4f}")

    print("\n" + "-" * 70)
    print("4. 정확도 검증 (원래 라벨 기준)")
    print("-" * 70)
    if acc is not None:
        print(acc.to_string(index=False))
    if classes is not None:
        print("\n등급별 표본 수:")
        print(classes.to_string(index=False))

    # ──────────────────────────────────────────────
    # 최종 통합 요약표
    # ──────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("최종 통합 요약표")
    print("=" * 70)
    master_rows = []
    if labels is not None:
        master_rows.append({"항목": "라벨 불일치 건수", "값": f"{n_mismatch}/{n_total - n_no_grade}건 (등급없음 {n_no_grade}건 제외)"})
    if rerun is not None:
        for _, r in rerun.iterrows():
            master_rows.append({
                "항목": f"[{r['label_set']}/{r['method']}] QWK",
                "값": f"{r['qwk_mean']:.4f} ± {r['qwk_std']:.4f} (n={r['n_mean']:.0f})",
            })
            master_rows.append({
                "항목": f"[{r['label_set']}/{r['method']}] 투기recall",
                "값": f"{r['spec_recall_mean']:.4f} ± {r['spec_recall_std']:.4f}",
            })
    if histgb_qwk_mean is not None:
        master_rows.append({"항목": "HistGB(교정라벨) QWK", "값": f"{histgb_qwk_mean:.4f} ± {histgb_qwk_std:.4f}"})
    if acc is not None:
        row = acc.iloc[0]
        master_rows.append({"항목": "정확일치 정확도 (원래라벨)", "값": f"{row['exact_match_accuracy']:.4f}"})
        master_rows.append({"항목": "최빈등급 baseline 정확도", "값": f"{row['majority_baseline_accuracy']:.4f}"})

    master_df = pd.DataFrame(master_rows)
    print(master_df.to_string(index=False))
    out_path = os.path.join(args.out_dir, "stage5_final_summary.csv")
    master_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n저장: {out_path}")

    # ──────────────────────────────────────────────
    # 과장 위험 체크리스트 (데이터 기반 자동 생성)
    # ──────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("⚠ 자소서 작성 시 과장 위험 체크리스트")
    print("=" * 70)
    warns = []

    if acc is not None:
        row = acc.iloc[0]
        if row["exact_match_accuracy"] < row["majority_baseline_accuracy"]:
            warns.append(
                f"정확 일치 정확도({row['exact_match_accuracy']:.1%})가 '최빈 등급 하나로만 찍는' "
                f"베이스라인({row['majority_baseline_accuracy']:.1%})보다 낮습니다. QWK가 높다고 "
                "'정확도가 높다'는 식으로 쓰면 명백한 과장/오해입니다. QWK와 exact accuracy는 "
                "다른 지표임을 반드시 구분해서 표기하세요."
            )

    if labels is not None and n_mismatch is not None and (n_total - n_no_grade) > 0:
        mismatch_rate = n_mismatch / (n_total - n_no_grade)
        if mismatch_rate > 0.1:
            warns.append(
                f"학습에 쓴 라벨 중 {mismatch_rate:.1%}가 NICE 이력과 불일치합니다. "
                "원 데이터의 라벨 신뢰도 자체에 의문이 있다는 뜻이므로, 'OOF QWK'를 곧바로 "
                "'모델 성능'이라고 자소서에 쓰면 라벨 노이즈로 인한 착시일 수 있습니다. "
                "교정 라벨 기준 수치도 함께 병기하는 것을 권장합니다."
            )
        if n_no_grade > 0:
            warns.append(
                f"NICE에 등급이 없는 기업이 {n_no_grade}건 있습니다. 즉 원본 라벨 중 일부는 "
                "애초에 공개 신용등급이 존재하지 않는 기업일 수 있어, 라벨 출처 자체를 다시 "
                "점검할 필요가 있습니다."
            )

    if rerun is not None:
        orig_base = rerun[(rerun["label_set"] == "원래라벨") & (rerun["method"] == "baseline")]
        corr_base = rerun[(rerun["label_set"] == "교정라벨") & (rerun["method"] == "baseline")]
        if len(orig_base) and len(corr_base):
            d_qwk = corr_base.iloc[0]["qwk_mean"] - orig_base.iloc[0]["qwk_mean"]
            if abs(d_qwk) > 0.03:
                direction = "높아집니다" if d_qwk > 0 else "낮아집니다"
                warns.append(
                    f"라벨을 교정하면 baseline QWK가 {d_qwk:+.4f} 만큼 {direction}. "
                    "즉 원래 자소서에 쓰려던 QWK 수치는 '검증되지 않은 라벨' 기준값이었을 "
                    "가능성이 있으므로, 교정 라벨 기준 수치를 최종값으로 쓰는 것이 안전합니다."
                )

    if histgb_qwk_mean is not None and rerun is not None:
        corr_base = rerun[(rerun["label_set"] == "교정라벨") & (rerun["method"] == "baseline")]
        if len(corr_base):
            gap = corr_base.iloc[0]["qwk_mean"] - histgb_qwk_mean
            if gap < 0.05:
                warns.append(
                    f"기본 설정 HistGradientBoosting 대비 CatBoost+증강+가중치+단조제약 조합의 "
                    f"QWK 개선폭이 {gap:+.4f}로 크지 않습니다. '정교한 파이프라인 설계로 성능을 "
                    "끌어올렸다'는 식의 문장은, 실제로는 모델을 바꾸기만 해도 비슷한 수준이 "
                    "나온다는 이 비교 결과와 함께 신중하게 써야 합니다."
                )
            else:
                warns.append(
                    f"CatBoost 파이프라인이 기본 HistGB보다 QWK가 {gap:+.4f} 높습니다. 다만 n이 "
                    "작아(60여 건) 이 차이가 통계적으로 안정적인지는 추가 검증이 필요합니다."
                )

    warns.append(
        "모든 QWK/precision/recall은 2-fold, n≈66(또는 교정 후 다른 n)의 매우 작은 표본 기준입니다. "
        "자소서에 절대 수치를 쓸 때는 반드시 표본 크기와 fold 수를 함께 명시하세요."
    )

    for w in warns:
        print(f"  ⚠ {w}")


if __name__ == "__main__":
    main()
