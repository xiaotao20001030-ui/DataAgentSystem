#!/usr/bin/env python3
"""Generate SQL predictions for BIRD perturbation variants."""

import argparse
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


SYSTEM_PROMPT = """You are an expert SQLite SQL generator.
Use only tables and columns present in the provided schema.
Return exactly one executable SQLite query and no explanation."""


def parse_args():
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variants",
        type=Path,
        default=project_root / "perturbations" / "output"
        / "mini_dev_perturbations.jsonl",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=project_root / "model_eval" / "model_matrix.json",
    )
    parser.add_argument("--model-key", required=True)
    parser.add_argument(
        "--families",
        default="base,add_random_20,add_synonym_20",
        help="Comma-separated perturbation family[:level] values.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "model_eval" / "predictions",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--dtype", default="auto")
    parser.add_argument("--api-base", default=None)
    parser.add_argument(
        "--api-key-env",
        default="OPENAI_API_KEY",
        help="Environment variable containing the API key.",
    )
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20261019)
    return parser.parse_args()


def family_name(record):
    perturbation = record["perturbation"]
    if perturbation["level"] is None:
        return perturbation["family"]
    return f"{perturbation['family']}_{perturbation['level']}"


def parse_family_filter(value):
    return {item.strip() for item in value.split(",") if item.strip()}


def load_variants(path, family_filter, limit):
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    selected = [record for record in records if family_name(record) in family_filter]
    if limit is not None:
        selected = selected[:limit]
    return selected


def build_prompt(record):
    schema_lines = []
    for table in record["schema"]:
        columns = ", ".join(
            f"{column['name']} {column['type']}"
            + (" PRIMARY KEY" if column["primary_key"] else "")
            for column in table["columns"]
        )
        schema_lines.append(f"- {table['table']}({columns})")
    evidence = record.get("evidence") or ""
    user_prompt = (
        "SQLite schema:\n"
        + "\n".join(schema_lines)
        + "\n\nQuestion:\n"
        + record["question"]
    )
    if evidence:
        user_prompt += "\n\nEvidence:\n" + evidence
    user_prompt += "\n\nReturn one SQLite query."
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def extract_sql(text):
    if not text:
        return ""
    fenced = re.search(
        r"```(?:sql|sqlite)?\s*(.*?)```",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    candidate = fenced.group(1) if fenced else text
    candidate = candidate.strip()
    start_match = re.search(r"\b(SELECT|WITH)\b", candidate, flags=re.IGNORECASE)
    if start_match:
        candidate = candidate[start_match.start():]
    semicolon = candidate.find(";")
    if semicolon >= 0:
        candidate = candidate[: semicolon + 1]
    return candidate.strip()


def message_content(response):
    content = response["choices"][0]["message"]["content"]
    if isinstance(content, list):
        return "".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict)
        )
    return content or ""


def seed_everything(seed, torch):
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


class TransformerGenerator:
    def __init__(self, config, args):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.config = config
        seed_everything(args.seed, torch)
        if args.device == "auto":
            if torch.cuda.is_available():
                self.device = "cuda"
            elif torch.backends.mps.is_available():
                self.device = "mps"
            else:
                self.device = "cpu"
        else:
            self.device = args.device

        if args.dtype == "auto":
            dtype = torch.bfloat16 if self.device == "cpu" else torch.float16
        else:
            dtype = getattr(torch, args.dtype)

        model_name = config["model"]
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            local_files_only=args.local_files_only,
            trust_remote_code=True,
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            local_files_only=args.local_files_only,
            trust_remote_code=True,
            torch_dtype=dtype,
            low_cpu_mem_usage=True,
        )
        self.model.to(self.device)
        self.model.eval()
        self.max_new_tokens = args.max_new_tokens

    def generate(self, messages):
        template_kwargs = {
            "tokenize": True,
            "add_generation_prompt": True,
            "return_tensors": "pt",
            "return_dict": True,
        }
        try:
            inputs = self.tokenizer.apply_chat_template(
                messages,
                enable_thinking=False,
                **template_kwargs,
            )
        except TypeError:
            inputs = self.tokenizer.apply_chat_template(
                messages,
                **template_kwargs,
            )
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        prompt_length = inputs["input_ids"].shape[-1]
        with self.torch.no_grad():
            generated = self.model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
                pad_token_id=self.tokenizer.eos_token_id,
            )
        return self.tokenizer.decode(
            generated[0][prompt_length:],
            skip_special_tokens=True,
        )


class OpenAIChatGenerator:
    def __init__(self, config, args):
        self.model_name = config["model"]
        if self.model_name in {"", "SET_ME"}:
            raise ValueError(
                "Set the API model name in model_eval/model_matrix.json."
            )
        self.base_url = (
            args.api_base or config.get("api_base") or "https://api.openai.com/v1"
        ).rstrip("/")
        self.api_key = os.environ.get(args.api_key_env, "")
        self.temperature = args.temperature
        self.max_new_tokens = args.max_new_tokens
        self.retries = args.retries
        self.seed = args.seed

    def generate(self, messages):
        payload_data = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_new_tokens,
        }
        if self.seed is not None:
            payload_data["seed"] = self.seed
        payload = json.dumps(payload_data).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers=headers,
            method="POST",
        )

        last_error = None
        for attempt in range(self.retries):
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    return message_content(json.loads(response.read()))
            except (urllib.error.URLError, TimeoutError, KeyError) as error:
                last_error = error
                time.sleep(min(2 ** attempt, 20))
        raise RuntimeError(f"API request failed after {self.retries} attempts: {last_error}")


def create_generator(config, args):
    provider = config["provider"]
    if provider == "transformers":
        return TransformerGenerator(config, args)
    if provider == "openai_compatible":
        return OpenAIChatGenerator(config, args)
    raise ValueError(f"Unsupported provider: {provider}")


def load_existing_ids(path):
    if not path.exists():
        return set()
    return {
        json.loads(line)["variant_id"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def main():
    args = parse_args()
    configs = json.loads(args.config.read_text(encoding="utf-8"))
    config_by_key = {item["key"]: item for item in configs}
    if args.model_key not in config_by_key:
        raise SystemExit(f"Unknown model key: {args.model_key}")
    config = config_by_key[args.model_key]

    records = load_variants(
        args.variants,
        parse_family_filter(args.families),
        args.limit,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"{args.model_key}.jsonl"
    existing_ids = load_existing_ids(output_path)
    pending = [record for record in records if record["variant_id"] not in existing_ids]

    generator = create_generator(config, args)
    with output_path.open("a", encoding="utf-8") as output:
        for index, record in enumerate(pending, start=1):
            messages = build_prompt(record)
            try:
                raw_response = generator.generate(messages)
                error = None
            except Exception as exception:
                raw_response = ""
                error = f"{type(exception).__name__}: {exception}"
            prediction = {
                "variant_id": record["variant_id"],
                "question_id": record["question_id"],
                "db_id": record["db_id"],
                "family": family_name(record),
                "model_key": args.model_key,
                "model": config["model"],
                "raw_response": raw_response,
                "predicted_sql": extract_sql(raw_response),
                "error": error,
            }
            output.write(
                json.dumps(prediction, ensure_ascii=False, separators=(",", ":"))
            )
            output.write("\n")
            output.flush()
            print(f"[{index}/{len(pending)}] {record['variant_id']}")

    print(f"Predictions: {output_path}")


if __name__ == "__main__":
    main()
