import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split

FEATURES = ("requests", "median_ms", "variation_ms", "moves", "clicks", "age_seconds",
            "failed_holds", "burst", "abandoned")


def dataset():
    rng = np.random.default_rng(5200)
    # Include fast humans and slower bots so individual thresholds overlap.
    profiles = [
        (0, 2200, [4, 2100, 720, 25, 4, 70, .2, 2, .1]),
        (0, 600, [13, 370, 230, 5, 3, 17, 1, 6, .4]),
        (1, 1350, [43, 105, 32, 3, 16, 8, 4, 21, 2]),
        (1, 800, [12, 630, 140, 7, 8, 42, 1.8, 5, 1.3]),
    ]
    x, y = [], []
    for label, size, means in profiles:
        center = np.asarray(means)
        samples = np.maximum(0, rng.normal(center, center * .55 + .12, (size, len(center))))
        x.extend(samples)
        y.extend([label] * size)
    return np.asarray(x), np.asarray(y)


def train():
    x, y = dataset()
    train_x, test_x, train_y, test_y = train_test_split(x, y, test_size=.25, random_state=52, stratify=y)
    model = RandomForestClassifier(n_estimators=48, max_depth=10, min_samples_leaf=4, random_state=52, n_jobs=1)
    model.fit(train_x, train_y)
    predictions = model.predict(test_x)
    report = {"precision": precision_score(test_y, predictions), "recall": recall_score(test_y, predictions),
              "f1": f1_score(test_y, predictions), "confusion_matrix": confusion_matrix(test_y, predictions).tolist(),
              "train_samples": len(train_y), "test_samples": len(test_y), "data": "synthetic"}
    folder = Path(__file__).resolve().parent
    joblib.dump(model, folder / "bot_model.joblib", compress=3)
    (folder / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    train()
