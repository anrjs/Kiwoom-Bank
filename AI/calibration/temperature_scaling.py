"""
사용법:
python calibration/temperature_scaling.py --logits_csv valid_logits.csv --labels_csv valid_labels.csv


valid_logits.csv: N×3 소프트맥스 이전 로짓 저장 (각 행: [logit_neg, logit_neu, logit_pos])
valid_labels.csv: N개의 정답 라벨 id (0/1/2)


훈련된 T 를 저장하고, 추론 시 softmax(logits / T) 로 보정.
"""
import argparse
import numpy as np
from scipy.optimize import minimize




def nll_with_T(T, logits, labels):
    T = float(T[0])
    z = logits / T
    z = z - z.max(axis=1, keepdims=True)
    expz = np.exp(z)
    probs = expz / expz.sum(axis=1, keepdims=True)
    eps = 1e-12
    nll = -np.log(probs[np.arange(len(labels)), labels] + eps).mean()
    return nll




def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logits_csv", required=True)
    ap.add_argument("--labels_csv", required=True)
    ap.add_argument("--out_file", default="calibration_T.txt")
    args = ap.parse_args()


    logits = np.loadtxt(args.logits_csv, delimiter=",")
    labels = np.loadtxt(args.labels_csv, delimiter=",").astype(int)


    res = minimize(nll_with_T, x0=[1.0], args=(logits, labels), bounds=[(0.05, 5.0)])
    T = float(res.x[0])
    with open(args.out_file, "w") as f:
        f.write(str(T))
    print("Optimal Temperature:", T)


if __name__ == "__main__":
    main()