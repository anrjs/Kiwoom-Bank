"""
입력 CSV 포맷 예시:
text,label
"삼성전자, 3분기 실적 서프라이즈...",pos
"회사채 이자 미지급 우려...",neg
"실적 전망은 엇갈려...",neu


label 값은 {pos, neg, neu} 중 하나.
"""
import argparse
import pandas as pd
from datasets import Dataset
from transformers import AutoTokenizer, AutoModelForSequenceClassification, DataCollatorWithPadding, Trainer, TrainingArguments
import evaluate
import numpy as np


LABEL2ID = {"neg":0, "neu":1, "pos":2}
ID2LABEL = {v:k for k,v in LABEL2ID.items()}




def load_data(path: str) -> Dataset:
    df = pd.read_csv(path)
    df = df.dropna(subset=["text","label"]).copy()
    df["label_id"] = df["label"].str.lower().map(LABEL2ID)
    return Dataset.from_pandas(df[["text","label_id"]])




def tokenize_fn(examples, tokenizer):
    return tokenizer(examples["text"], truncation=True, max_length=256)




def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=1)
    acc = (preds == labels).mean()
    # class-wise F1
    import sklearn.metrics as M
    f1_macro = M.f1_score(labels, preds, average="macro")
    return {"accuracy": float(acc), "f1_macro": float(f1_macro)}




def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("train_csv")
    ap.add_argument("valid_csv")
    ap.add_argument("--base_model", default="klue/bert-base")
    ap.add_argument("--out_dir", default="./kofin-sentiment")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=16)
    args = ap.parse_args()


    tokenizer = AutoTokenizer.from_pretrained(args.base_model)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.base_model,
        num_labels=3,
        id2label={0:"neg",1:"neu",2:"pos"},
        label2id={"neg":0,"neu":1,"pos":2}
    )

    train_ds = load_data(args.train_csv)
    valid_ds = load_data(args.valid_csv)


    train_ds = train_ds.map(lambda x: tokenize_fn(x, tokenizer), batched=True)
    valid_ds = valid_ds.map(lambda x: tokenize_fn(x, tokenizer), batched=True)


    collator = DataCollatorWithPadding(tokenizer=tokenizer)


    targs = TrainingArguments(
        output_dir=args.out_dir,
        learning_rate=5e-5,
        per_device_train_batch_size=args.batch,
        per_device_eval_batch_size=args.batch,
        num_train_epochs=args.epochs,
        evaluation_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1_macro",
        logging_steps=50,
        report_to="none"
    )


    trainer = Trainer(
        model=model,
        args=targs,
        train_dataset=train_ds,
        eval_dataset=valid_ds,
        tokenizer=tokenizer,
        data_collator=collator,
        compute_metrics=compute_metrics,
    )


    trainer.train()
    trainer.save_model(args.out_dir)
    tokenizer.save_pretrained(args.out_dir)


if __name__ == "__main__":
    main()