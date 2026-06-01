from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class HuggingFaceGenerationConfig:
    model_name: str = "Qwen/Qwen3-4B-Instruct-2507"
    max_new_tokens: int = 512
    temperature: float = 0.1
    top_p: float = 0.9
    repetition_penalty: float = 1.05
    device: str | None = None
    torch_dtype: str = "auto"
    load_in_4bit: bool = False
    bnb_4bit_compute_dtype: str = "float16"
    enable_thinking: bool | None = None
    adapter_path: str | None = None


class HuggingFaceGenerator:
    """Local Hugging Face chat generator for retrieval-grounded answers."""

    def __init__(
        self,
        model_name: str = "Qwen/Qwen3-4B-Instruct-2507",
        max_new_tokens: int = 512,
        temperature: float = 0.1,
        top_p: float = 0.9,
        repetition_penalty: float = 1.05,
        device: str | None = None,
        torch_dtype: str = "auto",
        load_in_4bit: bool = False,
        bnb_4bit_compute_dtype: str = "float16",
        enable_thinking: bool | None = None,
        adapter_path: str | None = None,
    ):
        self.config = HuggingFaceGenerationConfig(
            model_name=model_name,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            repetition_penalty=repetition_penalty,
            device=device,
            torch_dtype=torch_dtype,
            load_in_4bit=load_in_4bit,
            bnb_4bit_compute_dtype=bnb_4bit_compute_dtype,
            enable_thinking=enable_thinking,
            adapter_path=adapter_path,
        )
        self._tokenizer = None
        self._model = None
        self._device = None

    def generate(self, query: str, contexts: list[str] | str, system_prompt: str | None = None) -> str:
        prompt = self._coerce_prompt(query=query, contexts=contexts)
        return self.generate_prompt(prompt, system_prompt=system_prompt)

    def generate_prompt(self, prompt: str, system_prompt: str | None = None) -> str:
        tokenizer, model = self._load()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        if getattr(tokenizer, "chat_template", None):
            chat_kwargs: dict[str, Any] = {
                "tokenize": False,
                "add_generation_prompt": True,
            }
            if self.config.enable_thinking is not None:
                chat_kwargs["enable_thinking"] = self.config.enable_thinking
            try:
                input_text = tokenizer.apply_chat_template(messages, **chat_kwargs)
            except TypeError:
                chat_kwargs.pop("enable_thinking", None)
                input_text = tokenizer.apply_chat_template(messages, **chat_kwargs)
        else:
            input_text = self._fallback_chat_text(messages)

        inputs = tokenizer(input_text, return_tensors="pt")
        inputs = {key: value.to(self._device) for key, value in inputs.items()}
        do_sample = self.config.temperature > 0

        generation_kwargs: dict[str, Any] = {
            "max_new_tokens": self.config.max_new_tokens,
            "do_sample": do_sample,
            "repetition_penalty": self.config.repetition_penalty,
            "pad_token_id": tokenizer.eos_token_id,
        }
        if do_sample:
            generation_kwargs["temperature"] = self.config.temperature
            generation_kwargs["top_p"] = self.config.top_p

        import torch

        with torch.inference_mode():
            output_ids = model.generate(**inputs, **generation_kwargs)

        prompt_length = inputs["input_ids"].shape[-1]
        generated_ids = output_ids[0][prompt_length:]
        return tokenizer.decode(generated_ids, skip_special_tokens=True).strip()

    def _load(self):
        if self._tokenizer is not None and self._model is not None:
            return self._tokenizer, self._model

        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        device = self.config.device or ("cuda" if torch.cuda.is_available() else "cpu")
        dtype = self._resolve_torch_dtype(device)

        tokenizer = AutoTokenizer.from_pretrained(self.config.model_name, trust_remote_code=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        model_kwargs: dict[str, Any] = {
            "trust_remote_code": True,
        }
        if self.config.load_in_4bit:
            from transformers import BitsAndBytesConfig

            compute_dtype = self._resolve_bnb_compute_dtype()
            model_kwargs.update(
                {
                    "quantization_config": BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=compute_dtype,
                        bnb_4bit_quant_type="nf4",
                        bnb_4bit_use_double_quant=True,
                    ),
                    "device_map": {"": device} if device != "cpu" else None,
                }
            )
        else:
            model_kwargs["torch_dtype"] = dtype

        model = AutoModelForCausalLM.from_pretrained(self.config.model_name, **model_kwargs)
        if self.config.adapter_path:
            from peft import PeftModel

            model = PeftModel.from_pretrained(model, self.config.adapter_path)
        if not self.config.load_in_4bit:
            model.to(device)
        model.eval()

        self._tokenizer = tokenizer
        self._model = model
        self._device = device
        return tokenizer, model

    def _resolve_torch_dtype(self, device: str):
        import torch

        if self.config.torch_dtype != "auto":
            return getattr(torch, self.config.torch_dtype)
        if device == "cuda":
            return torch.float16
        return torch.float32

    def _resolve_bnb_compute_dtype(self):
        import torch

        return getattr(torch, self.config.bnb_4bit_compute_dtype)

    @staticmethod
    def _coerce_prompt(query: str, contexts: list[str] | str) -> str:
        if isinstance(contexts, str):
            context_text = contexts
        else:
            context_text = "\n\n".join(contexts)
        return f"[질문]\n{query}\n\n[Context]\n{context_text}"

    @staticmethod
    def _fallback_chat_text(messages: list[dict[str, str]]) -> str:
        parts = []
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            parts.append(f"[{role}]\n{content}")
        parts.append("[assistant]\n")
        return "\n\n".join(parts)
