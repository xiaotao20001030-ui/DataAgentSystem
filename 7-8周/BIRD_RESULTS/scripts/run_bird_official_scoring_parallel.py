#!/usr/bin/env python3
from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


ROOT = Path("/root/fsas/home/xiaotao/xiaotao/MINIDEV")
PYTHON = Path("/root/fsas/home/xiaotao/.conda/envs/grast-sql/bin/python")
SCORER = ROOT / "BIRD_RESULTS" / "scripts" / "score_predictions_official.py"
PREDICTION_ROOT = ROOT / "BIRD_RESULTS" / "predictions"
SCORE_ROOT = ROOT / "BIRD_RESULTS" / "scores_official"
LOG_ROOT = ROOT / "BIRD_RESULTS" / "logs" / "official_scoring_parallel"
MAIN_VARIANTS = ROOT / "perturbations" / "output" / "mini_dev_perturbations.jsonl"
REAL_VARIANTS = (
    ROOT
    / "perturbations"
    / "output"
    / "real_synonym_sensitivity"
    / "mini_dev_add_real_synonym_20.jsonl"
)

CONDITIONS = (
    ("base", PREDICTION_ROOT / "base", MAIN_VARIANTS, SCORE_ROOT / "base"),
    (
        "random5",
        PREDICTION_ROOT / "random" / "level_5",
        MAIN_VARIANTS,
        SCORE_ROOT / "random" / "level_5",
    ),
    (
        "random10",
        PREDICTION_ROOT / "random" / "level_10",
        MAIN_VARIANTS,
        SCORE_ROOT / "random" / "level_10",
    ),
    (
        "random20",
        PREDICTION_ROOT / "random" / "level_20",
        MAIN_VARIANTS,
        SCORE_ROOT / "random" / "level_20",
    ),
    (
        "random50",
        PREDICTION_ROOT / "random" / "level_50",
        MAIN_VARIANTS,
        SCORE_ROOT / "random" / "level_50",
    ),
    (
        "synonym5",
        PREDICTION_ROOT / "synonym" / "level_5",
        MAIN_VARIANTS,
        SCORE_ROOT / "synonym" / "level_5",
    ),
    (
        "synonym10",
        PREDICTION_ROOT / "synonym" / "level_10",
        MAIN_VARIANTS,
        SCORE_ROOT / "synonym" / "level_10",
    ),
    (
        "synonym20",
        PREDICTION_ROOT / "synonym" / "level_20",
        MAIN_VARIANTS,
        SCORE_ROOT / "synonym" / "level_20",
    ),
    (
        "synonym50",
        PREDICTION_ROOT / "synonym" / "level_50",
        MAIN_VARIANTS,
        SCORE_ROOT / "synonym" / "level_50",
    ),
    (
        "real20",
        PREDICTION_ROOT / "real_synonym" / "level_20",
        REAL_VARIANTS,
        SCORE_ROOT / "real_synonym" / "level_20",
    ),
    ("missing", PREDICTION_ROOT / "missing", MAIN_VARIANTS, SCORE_ROOT / "missing"),
)
MODEL_ORDER = (
    "api_control",
    "qwen3_0_6b",
    "qwen3_1_7b",
    "qwen3_4b",
    "qwen2_5_coder_1_5b",
)


def run_job(job: dict) -> dict:
    log_path = LOG_ROOT / f"{job['group']}__{job['model']}.log"
    command = [
        str(PYTHON),
        "-u",
        str(SCORER),
        "--predictions",
        str(job["prediction"]),
        "--variants",
        str(job["variants"]),
        "--data-root",
        str(ROOT),
        "--output-dir",
        str(job["output"]),
        "--prediction-timeout",
        "30",
        "--gold-timeout",
        "30",
        "--progress-every",
        "25",
    ]
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"started={datetime.now().isoformat()}\n")
        log.flush()
        process = subprocess.run(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
        log.write(
            f"finished={datetime.now().isoformat()} "
            f"status={process.returncode}\n"
        )
    return {**job, "returncode": process.returncode}


def main() -> None:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    jobs = []
    for group, prediction_dir, variants, output_dir in CONDITIONS:
        output_dir.mkdir(parents=True, exist_ok=True)
        for model in MODEL_ORDER:
            prediction = prediction_dir / f"{model}.jsonl"
            if not prediction.exists():
                raise FileNotFoundError(prediction)
            jobs.append(
                {
                    "group": group,
                    "model": model,
                    "prediction": prediction,
                    "variants": variants,
                    "output": output_dir,
                }
            )

    failures = []
    with ThreadPoolExecutor(max_workers=24) as pool:
        futures = {pool.submit(run_job, job): job for job in jobs}
        for index, future in enumerate(as_completed(futures), 1):
            result = future.result()
            print(
                f"[{index}/{len(jobs)}] {result['group']} "
                f"{result['model']} status={result['returncode']}",
                flush=True,
            )
            if result["returncode"] != 0:
                failures.append(result)

    if failures:
        raise SystemExit(f"Failed jobs: {failures}")


if __name__ == "__main__":
    main()
