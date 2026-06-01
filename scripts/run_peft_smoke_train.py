#!/usr/bin/env python3
"""Run a small QLoRA PEFT smoke test on the prepared RAG SFT dataset.

The script is intentionally dependency-light: it uses Transformers + PEFT and a
manual training loop instead of TRL/datasets. It writes all outputs under a new
directory and does not modify the source dataset.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig


DEFAULT_MODEL = "unsloth/Qwen3-8B-bnb-4bit"
DEFAULT_TRAIN = Path("outputs/peft/raw_resolved/sft_train_messages.jsonl")
DEFAULT_VALID = Path("outputs/peft/raw_resolved/sft_valid_messages.jsonl")
DEFAULT_OUTPUT = Path("outputs/peft/qwen3_8b_qlora_smoke")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def compact(value: str, max_chars: int = 500) -> str:
    value = " ".join(str(value).split())
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 18].rstrip() + " ...[truncated]"


def load_tokenizer(model_name: str):
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"
    return tokenizer


def load_model(model_name: str):
    quant_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        bnb_4bit_use_double_quant=True,
    )
    return AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config=quant_config,
        device_map="auto",
        trust_remote_code=True,
    )


def split_messages(messages: list[dict[str, str]]) -> tuple[list[dict[str, str]], str]:
    if not messages or messages[-1].get("role") != "assistant":
        raise ValueError("Each SFT row must end with an assistant message.")
    return messages[:-1], messages[-1].get("content", "")


def format_prompt(tokenizer, messages: list[dict[str, str]]) -> str:
    if hasattr(tokenizer, "apply_chat_template"):
        return tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
    return "\n".join(f"{m['role']}: {m['content']}" for m in messages) + "\nassistant: "


def format_full(tokenizer, messages: list[dict[str, str]]) -> str:
    if hasattr(tokenizer, "apply_chat_template"):
        return tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=False,
            enable_thinking=False,
        )
    return "\n".join(f"{m['role']}: {m['content']}" for m in messages)


def truncate_prompt_ids(prompt_ids: list[int], max_prompt_len: int, suffix_tokens: int = 160) -> list[int]:
    """Keep the question/front context and the final assistant prompt marker."""
    if len(prompt_ids) <= max_prompt_len:
        return prompt_ids
    if max_prompt_len <= suffix_tokens:
        return prompt_ids[-max_prompt_len:]
    prefix_len = max_prompt_len - suffix_tokens
    return prompt_ids[:prefix_len] + prompt_ids[-suffix_tokens:]


class ChatSftDataset(Dataset):
    def __init__(self, rows: list[dict[str, Any]], tokenizer, max_length: int):
        self.rows = rows
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, idx: int) -> dict[str, Any]:
        row = self.rows[idx]
        messages = row["messages"]
        prompt_messages, answer = split_messages(messages)
        prompt_text = format_prompt(self.tokenizer, prompt_messages)
        full_text = format_full(self.tokenizer, messages)

        prompt_ids = self.tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
        full_ids = self.tokenizer(full_text, add_special_tokens=False)["input_ids"]
        answer_ids = self.tokenizer(answer + (self.tokenizer.eos_token or ""), add_special_tokens=False)[
            "input_ids"
        ]

        # Prefer preserving the answer labels. The prompt/context is clipped from
        # the right only when needed.
        max_prompt_len = max(32, self.max_length - len(answer_ids))
        if len(prompt_ids) > max_prompt_len:
            prompt_ids = truncate_prompt_ids(prompt_ids, max_prompt_len)
            input_ids = prompt_ids + answer_ids
        else:
            input_ids = full_ids[: self.max_length]
            if len(input_ids) < len(prompt_ids):
                input_ids = prompt_ids[:max_prompt_len] + answer_ids

        input_ids = input_ids[: self.max_length]
        prompt_len = min(len(prompt_ids), len(input_ids))
        labels = [-100] * prompt_len + input_ids[prompt_len:]
        if len(labels) < len(input_ids):
            labels.extend(input_ids[len(labels) :])
        labels = labels[: len(input_ids)]

        return {
            "question_id": row.get("question_id"),
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "attention_mask": torch.ones(len(input_ids), dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
        }


@dataclass
class Collator:
    pad_token_id: int

    def __call__(self, batch: list[dict[str, Any]]) -> dict[str, torch.Tensor]:
        max_len = max(item["input_ids"].shape[0] for item in batch)
        input_ids, attention_mask, labels = [], [], []
        for item in batch:
            pad_len = max_len - item["input_ids"].shape[0]
            input_ids.append(torch.cat([item["input_ids"], torch.full((pad_len,), self.pad_token_id)]))
            attention_mask.append(torch.cat([item["attention_mask"], torch.zeros(pad_len, dtype=torch.long)]))
            labels.append(torch.cat([item["labels"], torch.full((pad_len,), -100, dtype=torch.long)]))
        return {
            "input_ids": torch.stack(input_ids),
            "attention_mask": torch.stack(attention_mask),
            "labels": torch.stack(labels),
        }


def token_overlap(prediction: str, target: str) -> float:
    pred_tokens = set(prediction.replace("\n", " ").split())
    target_tokens = set(target.replace("\n", " ").split())
    if not target_tokens:
        return 0.0
    return len(pred_tokens & target_tokens) / len(target_tokens)


@torch.inference_mode()
def generate_samples(model, tokenizer, rows: list[dict[str, Any]], max_new_tokens: int) -> list[dict[str, Any]]:
    model.eval()
    outputs: list[dict[str, Any]] = []
    for row in rows:
        prompt_messages, gold_answer = split_messages(row["messages"])
        prompt_text = format_prompt(tokenizer, prompt_messages)
        prompt_ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
        prompt_ids = truncate_prompt_ids(prompt_ids, 2048)
        encoded = {
            "input_ids": torch.tensor([prompt_ids], dtype=torch.long, device=model.device),
            "attention_mask": torch.ones((1, len(prompt_ids)), dtype=torch.long, device=model.device),
        }
        started = time.time()
        generated = model.generate(
            **encoded,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            temperature=None,
            top_p=None,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
        elapsed = time.time() - started
        new_tokens = generated[0, encoded["input_ids"].shape[1] :]
        answer = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
        outputs.append(
            {
                "question_id": row.get("question_id"),
                "task_family": row.get("task_family"),
                "question": compact(prompt_messages[-1]["content"].split("[QUESTION]", 1)[-1], 700),
                "generated_answer": answer,
                "gold_answer": gold_answer,
                "token_overlap_with_gold": token_overlap(answer, gold_answer),
                "latency_sec": round(elapsed, 3),
            }
        )
    return outputs


def build_peft_model(model, lora_r: int, lora_alpha: int, lora_dropout: float):
    model = prepare_model_for_kbit_training(model)
    model.config.use_cache = False
    if hasattr(model, "gradient_checkpointing_enable"):
        model.gradient_checkpointing_enable()
    config = LoraConfig(
        r=lora_r,
        lora_alpha=lora_alpha,
        lora_dropout=lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )
    peft_model = get_peft_model(model, config)
    peft_model.print_trainable_parameters()
    return peft_model


def evaluate_loss(model, loader: DataLoader, max_batches: int = 4) -> float:
    model.eval()
    losses: list[float] = []
    with torch.no_grad():
        for idx, batch in enumerate(loader):
            if idx >= max_batches:
                break
            batch = {key: value.to(model.device) for key, value in batch.items()}
            out = model(**batch)
            losses.append(float(out.loss.detach().cpu()))
    model.train()
    return float(sum(losses) / max(1, len(losses)))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--train-path", type=Path, default=DEFAULT_TRAIN)
    parser.add_argument("--valid-path", type=Path, default=DEFAULT_VALID)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--max-length", type=int, default=1536)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=4)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--lora-r", type=int, default=8)
    parser.add_argument("--lora-alpha", type=int, default=16)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--eval-samples", type=int, default=3)
    parser.add_argument("--max-new-tokens", type=int, default=192)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--skip-generation", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    train_rows = load_jsonl(args.train_path)
    valid_rows = load_jsonl(args.valid_path)
    eval_rows = valid_rows[: args.eval_samples]

    manifest = {
        "model": args.model,
        "train_path": str(args.train_path),
        "valid_path": str(args.valid_path),
        "output_dir": str(args.output_dir),
        "train_rows": len(train_rows),
        "valid_rows": len(valid_rows),
        "max_steps": args.max_steps,
        "max_length": args.max_length,
        "batch_size": args.batch_size,
        "grad_accum": args.grad_accum,
        "lr": args.lr,
        "lora_r": args.lora_r,
        "lora_alpha": args.lora_alpha,
        "lora_dropout": args.lora_dropout,
    }
    (args.output_dir / "run_config.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    tokenizer = load_tokenizer(args.model)
    model = load_model(args.model)

    before: list[dict[str, Any]] = []
    if not args.skip_generation:
        before = generate_samples(model, tokenizer, eval_rows, args.max_new_tokens)
        write_jsonl(args.output_dir / "before_samples.jsonl", before)

    model = build_peft_model(model, args.lora_r, args.lora_alpha, args.lora_dropout)

    train_ds = ChatSftDataset(train_rows, tokenizer, args.max_length)
    valid_ds = ChatSftDataset(valid_rows, tokenizer, args.max_length)
    collator = Collator(pad_token_id=tokenizer.pad_token_id)
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, collate_fn=collator)
    valid_loader = DataLoader(valid_ds, batch_size=args.batch_size, shuffle=False, collate_fn=collator)

    trainable_params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(trainable_params, lr=args.lr)
    log_rows: list[dict[str, Any]] = []
    step = 0
    micro_step = 0
    accum_loss = 0.0
    start = time.time()
    model.train()
    optimizer.zero_grad(set_to_none=True)

    while step < args.max_steps:
        for batch in train_loader:
            batch = {key: value.to(model.device) for key, value in batch.items()}
            out = model(**batch)
            loss = out.loss / args.grad_accum
            loss.backward()
            micro_step += 1
            accum_loss += float(loss.detach().cpu()) * args.grad_accum
            if micro_step % args.grad_accum == 0:
                torch.nn.utils.clip_grad_norm_(trainable_params, 1.0)
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                step += 1
                row = {
                    "step": step,
                    "train_loss": accum_loss / args.grad_accum,
                    "elapsed_sec": round(time.time() - start, 3),
                }
                if step == 1 or step == args.max_steps or step % 4 == 0:
                    row["valid_loss"] = evaluate_loss(model, valid_loader, max_batches=3)
                log_rows.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
                accum_loss = 0.0
                if step >= args.max_steps:
                    break
        if step >= args.max_steps:
            break

    adapter_dir = args.output_dir / "adapter"
    model.save_pretrained(adapter_dir)
    tokenizer.save_pretrained(adapter_dir)

    after: list[dict[str, Any]] = []
    if not args.skip_generation:
        after = generate_samples(model, tokenizer, eval_rows, args.max_new_tokens)
        write_jsonl(args.output_dir / "after_samples.jsonl", after)
    write_jsonl(args.output_dir / "training_log.jsonl", log_rows)

    summary = {
        **manifest,
        "adapter_dir": str(adapter_dir),
        "before_avg_overlap": (
            sum(r["token_overlap_with_gold"] for r in before) / len(before) if before else None
        ),
        "after_avg_overlap": (
            sum(r["token_overlap_with_gold"] for r in after) / len(after) if after else None
        ),
        "final_train_loss": log_rows[-1]["train_loss"] if log_rows else None,
        "final_valid_loss": next((r["valid_loss"] for r in reversed(log_rows) if "valid_loss" in r), None),
        "total_elapsed_sec": round(time.time() - start, 3),
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    print("[OK] PEFT smoke test complete")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
