#!/usr/bin/env python3
"""Compare a base 4bit model with a PEFT adapter on the prepared SFT set."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import torch
from peft import PeftModel
from torch.utils.data import DataLoader

from run_peft_smoke_train import (
    ChatSftDataset,
    Collator,
    evaluate_loss,
    format_prompt,
    load_jsonl,
    load_model,
    load_tokenizer,
    split_messages,
    token_overlap,
    truncate_prompt_ids,
    write_jsonl,
)


DEFAULT_MODEL = "unsloth/Qwen3-8B-bnb-4bit"
DEFAULT_VALID = Path("outputs/peft/raw_resolved/sft_valid_messages.jsonl")
DEFAULT_ADAPTER = Path("outputs/peft/qwen3_8b_qlora_sft_v1/adapter")
DEFAULT_OUTPUT = Path("outputs/peft/qwen3_8b_qlora_sft_v1/eval_compare")


@torch.inference_mode()
def generate_one(model, tokenizer, row: dict[str, Any], max_new_tokens: int) -> dict[str, Any]:
    prompt_messages, gold_answer = split_messages(row["messages"])
    prompt_text = format_prompt(tokenizer, prompt_messages)
    prompt_ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
    prompt_ids = truncate_prompt_ids(prompt_ids, 1536)
    encoded = {
        "input_ids": torch.tensor([prompt_ids], dtype=torch.long, device=model.device),
        "attention_mask": torch.ones((1, len(prompt_ids)), dtype=torch.long, device=model.device),
    }
    started = time.time()
    generated = model.generate(
        **encoded,
        max_new_tokens=max_new_tokens,
        do_sample=False,
        pad_token_id=tokenizer.pad_token_id,
        eos_token_id=tokenizer.eos_token_id,
    )
    elapsed = time.time() - started
    new_tokens = generated[0, encoded["input_ids"].shape[1] :]
    answer = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
    return {
        "generated_answer": answer,
        "gold_answer": gold_answer,
        "token_overlap_with_gold": token_overlap(answer, gold_answer),
        "latency_sec": round(elapsed, 3),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--valid-path", type=Path, default=DEFAULT_VALID)
    parser.add_argument("--adapter-dir", type=Path, default=DEFAULT_ADAPTER)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-length", type=int, default=1024)
    parser.add_argument("--loss-batches", type=int, default=10)
    parser.add_argument("--sample-count", type=int, default=1)
    parser.add_argument("--max-new-tokens", type=int, default=64)
    parser.add_argument("--skip-generation", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = load_jsonl(args.valid_path)
    tokenizer = load_tokenizer(args.model)
    collator = Collator(pad_token_id=tokenizer.pad_token_id)
    valid_ds = ChatSftDataset(rows, tokenizer, args.max_length)
    valid_loader = DataLoader(valid_ds, batch_size=1, shuffle=False, collate_fn=collator)

    model = load_model(args.model)
    base_loss = evaluate_loss(model, valid_loader, max_batches=args.loss_batches)
    sample_rows = rows[: args.sample_count]
    comparisons: list[dict[str, Any]] = []

    if not args.skip_generation:
        model.eval()
        for row in sample_rows:
            item = {
                "question_id": row.get("question_id"),
                "task_family": row.get("task_family"),
                "base": generate_one(model, tokenizer, row, args.max_new_tokens),
            }
            comparisons.append(item)

    model = PeftModel.from_pretrained(model, args.adapter_dir)
    adapter_loss = evaluate_loss(model, valid_loader, max_batches=args.loss_batches)

    if not args.skip_generation:
        model.eval()
        for item, row in zip(comparisons, sample_rows):
            item["adapter"] = generate_one(model, tokenizer, row, args.max_new_tokens)

    summary = {
        "model": args.model,
        "adapter_dir": str(args.adapter_dir),
        "valid_path": str(args.valid_path),
        "valid_rows": len(rows),
        "loss_batches": min(args.loss_batches, len(rows)),
        "base_valid_loss": base_loss,
        "adapter_valid_loss": adapter_loss,
        "loss_delta": adapter_loss - base_loss,
        "loss_improvement_ratio": (base_loss - adapter_loss) / base_loss if base_loss else None,
        "sample_count": 0 if args.skip_generation else len(comparisons),
    }
    (args.output_dir / "comparison_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if comparisons:
        write_jsonl(args.output_dir / "generation_comparison.jsonl", comparisons)

    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
