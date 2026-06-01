import argparse
import json
import os
import sys
import re
import threading
import time
import unicodedata
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

if __package__ is None and __spec__ is None:
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

from src.generation import (
    advanced_guardrails,
    build_rfp_generation_input,
    dedupe_repeated_lines,
    load_rfp_generation_resources,
    postprocess_rfp_generation_answer,
)
from src.generator import HuggingFaceGenerator
from src.pipeline import RAGPipeline


DEFAULT_CHUNKS = "data/processed/chunks_v2_690.jsonl"
DEFAULT_INDEX = "indexes/chroma_kure_v1_chunks_v2_690"
DEFAULT_SOURCE_STORE = "data/processed/source_store_v2_690.jsonl"
DEFAULT_MODEL = "unsloth/Qwen3-8B-bnb-4bit"
DEFAULT_BEST_ADAPTER = "outputs/peft/qwen3_8b_qlora_sft_v2_truncfix/adapter"


APP_HTML = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RFP Assistant</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f6f8;
      --panel: #ffffff;
      --ink: #111827;
      --muted: #667085;
      --line: #d7dde7;
      --soft: #eef2f7;
      --brand: #1d5f9f;
      --brand-dark: #164a7c;
      --warn-bg: #fff7ed;
      --warn-line: #fed7aa;
      --warn-ink: #9a3412;
      --shadow: 0 12px 28px rgba(15, 23, 42, 0.08);
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 15px/1.55 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr auto;
    }
    header {
      height: 64px;
      padding: 0 24px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.96);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      position: sticky;
      top: 0;
      z-index: 4;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }
    .mark {
      width: 34px;
      height: 34px;
      border-radius: 8px;
      background: var(--brand);
      color: #fff;
      display: grid;
      place-items: center;
      font-weight: 800;
    }
    h1 {
      margin: 0;
      font-size: 18px;
      line-height: 1.2;
    }
    .subtitle {
      color: var(--muted);
      font-size: 13px;
      margin-top: 2px;
    }
    .top-actions {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    button {
      border: 0;
      border-radius: 8px;
      min-height: 38px;
      padding: 0 14px;
      background: var(--brand);
      color: #fff;
      font-weight: 750;
      cursor: pointer;
      white-space: nowrap;
    }
    button:hover { background: var(--brand-dark); }
    button:disabled { background: #91a9c3; cursor: wait; }
    .secondary {
      background: #fff;
      color: #263445;
      border: 1px solid var(--line);
    }
    .secondary:hover { background: #f8fafc; }
    main {
      width: min(980px, calc(100vw - 24px));
      margin: 0 auto;
      display: grid;
      grid-template-rows: 1fr;
      min-height: 0;
    }
    .chat {
      padding: 24px 0 18px;
      display: flex;
      flex-direction: column;
      gap: 18px;
      overflow-y: auto;
      min-height: 0;
    }
    .welcome {
      margin: auto;
      width: min(680px, 100%);
      text-align: center;
      padding: 48px 16px;
      color: #344054;
    }
    .welcome h2 {
      margin: 0 0 10px;
      font-size: 28px;
      color: var(--ink);
    }
    .chips {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-top: 24px;
      text-align: left;
    }
    .chip {
      min-height: 70px;
      padding: 12px;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      color: #253244;
      font-weight: 650;
      box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
    }
    .message-row {
      display: grid;
      grid-template-columns: 40px minmax(0, 1fr);
      gap: 12px;
      align-items: start;
    }
    .message-row.user {
      grid-template-columns: minmax(0, 1fr) 40px;
    }
    .avatar {
      width: 36px;
      height: 36px;
      border-radius: 9px;
      display: grid;
      place-items: center;
      font-size: 13px;
      font-weight: 800;
      background: #e8eef6;
      color: #1f344d;
    }
    .assistant .avatar { background: #dbeafe; color: #174677; }
    .user .avatar { background: #e7f5ec; color: #166534; }
    .bubble {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 14px 16px;
      box-shadow: 0 6px 16px rgba(15, 23, 42, 0.04);
      white-space: pre-wrap;
      word-break: break-word;
    }
    .typing {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: #344054;
      font-weight: 650;
    }
    .spinner {
      width: 15px;
      height: 15px;
      border: 2px solid #c9d5e4;
      border-top-color: var(--brand);
      border-radius: 999px;
      animation: spin 0.8s linear infinite;
      flex: 0 0 auto;
    }
    .loading-overlay {
      position: fixed;
      left: 50%;
      bottom: 104px;
      transform: translateX(-50%);
      z-index: 20;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 12px 16px;
      border: 1px solid #b8c8dc;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.98);
      color: #1f344d;
      font-weight: 750;
      box-shadow: 0 14px 34px rgba(15, 23, 42, 0.18);
    }
    .loading-overlay[hidden] { display: none; }
    @keyframes spin { to { transform: rotate(360deg); } }
    .user .bubble {
      background: #eaf4ff;
      border-color: #c7def7;
    }
    .user .avatar { grid-column: 2; }
    .user .bubble { grid-column: 1; grid-row: 1; }
    .meta-line {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      color: var(--muted);
      font-size: 12px;
      margin-top: 10px;
    }
    .pill {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 8px;
      background: #f8fafc;
    }
    details.trace {
      margin-top: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfe;
      overflow: hidden;
    }
    details.trace > summary {
      cursor: pointer;
      padding: 10px 12px;
      font-weight: 750;
      color: #263445;
    }
    .trace-body {
      border-top: 1px solid var(--line);
      padding: 12px;
      display: grid;
      gap: 12px;
    }
    .source {
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
    }
    .source-title { font-weight: 750; margin-bottom: 4px; }
    .source-meta { color: var(--muted); font-size: 12px; margin-bottom: 6px; }
    .warnings {
      border: 1px solid var(--warn-line);
      background: var(--warn-bg);
      color: var(--warn-ink);
      border-radius: 8px;
      padding: 10px;
      white-space: pre-wrap;
    }
    pre {
      margin: 0;
      padding: 10px;
      border-radius: 8px;
      background: #f3f5f8;
      border: 1px solid var(--line);
      overflow: auto;
      max-height: 280px;
      white-space: pre-wrap;
      word-break: break-word;
      font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    footer {
      border-top: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.96);
      padding: 14px 0;
      position: sticky;
      bottom: 0;
      z-index: 3;
    }
    .composer-wrap {
      width: min(980px, calc(100vw - 24px));
      margin: 0 auto;
    }
    .composer {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: end;
      padding: 10px;
      border: 1px solid #bfc9d8;
      border-radius: 12px;
      background: #fff;
      box-shadow: var(--shadow);
    }
    textarea {
      width: 100%;
      min-height: 44px;
      max-height: 160px;
      resize: vertical;
      border: 0;
      outline: 0;
      padding: 9px 8px;
      font: inherit;
      color: var(--ink);
      background: transparent;
    }
    .send-group {
      display: grid;
      width: 96px;
    }
    .status {
      min-height: 20px;
      color: var(--muted);
      font-size: 13px;
      margin-top: 8px;
    }
    .settings {
      margin-top: 10px;
      color: #344054;
    }
    .settings summary {
      cursor: pointer;
      width: fit-content;
      font-weight: 700;
      color: var(--muted);
    }
    .settings-panel {
      margin-top: 10px;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
    }
    .control {
      min-height: 42px;
      display: flex;
      gap: 8px;
      align-items: center;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfe;
    }
    input[type="number"] {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px;
      font: inherit;
    }
    .number-label { display: grid; gap: 5px; font-size: 13px; color: var(--muted); }
    @media (max-width: 760px) {
      header { padding: 0 14px; }
      .subtitle { display: none; }
      .settings-panel { grid-template-columns: 1fr; }
      .message-row, .message-row.user { grid-template-columns: 34px minmax(0, 1fr); }
      .user .avatar { grid-column: 1; }
      .user .bubble { grid-column: 2; }
    }
  </style>
</head>
<body>
  <div class="app">
    <header>
      <div class="brand">
        <div class="mark">R</div>
        <div>
          <h1>RFP Assistant</h1>
          <div class="subtitle">문서 근거 기반 입찰/RFP 질의응답</div>
        </div>
      </div>
      <div class="top-actions">
        <button id="clearBtn" class="secondary">새 대화</button>
      </div>
    </header>

    <main>
      <div id="loadingOverlay" class="loading-overlay" hidden>
        <span class="spinner"></span>
        <span>답변 생성 중입니다. 잠시만 기다려주세요.</span>
      </div>
      <div id="chat" class="chat">
        <div id="welcome" class="welcome">
          <h2>무엇을 확인할까요?</h2>
          <div>RFP 문서 안의 내용을 근거와 함께 답합니다.</div>
        </div>
      </div>
    </main>

    <footer>
      <div class="composer-wrap">
        <div class="composer">
          <textarea id="question" placeholder="질문을 입력하세요. Enter로 보내고 Shift+Enter로 줄바꿈합니다."></textarea>
          <div class="send-group">
            <button id="askBtn">보내기</button>
          </div>
        </div>
        <div id="status" class="status"></div>
      </div>
    </footer>
  </div>

  <script>
    const $ = (id) => document.getElementById(id);
    const askBtn = $("askBtn");
    const clearBtn = $("clearBtn");
    const statusEl = $("status");
    const loadingOverlay = $("loadingOverlay");
    let knownModelLoaded = false;
    const chatHistory = [];

    clearBtn.addEventListener("click", () => {
      chatHistory.length = 0;
      $("chat").innerHTML = "";
      $("chat").appendChild($("welcomeTemplate")?.content?.cloneNode(true) || createWelcome());
      statusEl.textContent = "새 대화를 시작합니다.";
    });

    askBtn.addEventListener("click", () => runAsk(true));
    $("question").addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      if (event.isComposing || event.shiftKey) return;
      event.preventDefault();
      runAsk(true);
    });

    async function runAsk(generateAnswer) {
      const question = $("question").value.trim();
      if (!question) {
        statusEl.textContent = "질문을 입력하세요.";
        return;
      }
      removeWelcome();
      const historyForServer = chatHistory.slice(-8);
      appendUser(question);
      chatHistory.push({role: "user", content: question});
      $("question").value = "";
      const pendingRow = appendLoadingMessage(!knownModelLoaded);
      setBusy(true, generateAnswer, !knownModelLoaded);
      try {
        const res = await fetch("/api/ask", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            question,
            history: historyForServer,
            generate: true,
            use_source_store: true,
            max_new_tokens: 512,
            temperature: 0.1
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "request failed");
        knownModelLoaded = Boolean(data.model_loaded || data.generation_ms > 0 || knownModelLoaded);
        const assistantText = data.answer || "문서에서 확인할 수 없습니다.";
        replaceWithAssistant(pendingRow, data, assistantText);
        chatHistory.push({role: "assistant", content: assistantText});
        statusEl.textContent = "답변 완료";
      } catch (err) {
        replaceWithAssistant(pendingRow, {guardrails: {warnings: [err.message]}}, `오류가 발생했습니다: ${err.message}`);
        statusEl.textContent = `오류: ${err.message}`;
      } finally {
        setBusy(false, generateAnswer);
      }
    }

    function setBusy(isBusy, generateAnswer, isFirstGeneration = false) {
      askBtn.disabled = isBusy;
      askBtn.textContent = isBusy ? "생성 중" : "보내기";
      loadingOverlay.hidden = !isBusy;
      if (isBusy) {
        const message = isFirstGeneration
          ? "답변을 생성 중입니다. 첫 응답은 모델 로딩 때문에 오래 걸릴 수 있습니다."
          : "답변을 생성 중입니다.";
        statusEl.textContent = generateAnswer ? message : "문서를 검색하고 근거를 구성 중입니다.";
        const overlayText = loadingOverlay.querySelector("span:last-child");
        if (overlayText) overlayText.textContent = isFirstGeneration
          ? "답변 생성 중입니다. 첫 응답은 모델 로딩 때문에 오래 걸릴 수 있어요."
          : "답변 생성 중입니다. 잠시만 기다려주세요.";
      }
    }

    function appendUser(text) {
      const row = document.createElement("div");
      row.className = "message-row user";
      row.appendChild(avatar("나"));
      const bubble = document.createElement("div");
      bubble.className = "bubble";
      bubble.textContent = text;
      row.appendChild(bubble);
      appendRow(row);
    }

    function appendLoadingMessage(isFirstGeneration) {
      const row = document.createElement("div");
      row.className = "message-row assistant";
      row.appendChild(avatar("AI"));
      const bubble = document.createElement("div");
      bubble.className = "bubble";
      const loading = document.createElement("div");
      loading.className = "typing";
      const spinner = document.createElement("span");
      spinner.className = "spinner";
      const label = document.createElement("span");
      label.textContent = isFirstGeneration
        ? "답변을 생성하고 있습니다. 첫 응답은 모델 로딩 때문에 오래 걸릴 수 있어요."
        : "답변을 생성하고 있습니다.";
      loading.append(spinner, label);
      bubble.appendChild(loading);
      row.appendChild(bubble);
      appendRow(row);
      return row;
    }

    function replaceWithAssistant(row, data, text) {
      const replacement = buildAssistantRow(data, text);
      row.replaceWith(replacement);
      $("chat").scrollTop = $("chat").scrollHeight;
    }

    function buildAssistantRow(data, text) {
      const row = document.createElement("div");
      row.className = "message-row assistant";
      row.appendChild(avatar("AI"));
      const bubble = document.createElement("div");
      bubble.className = "bubble";
      const answer = document.createElement("div");
      answer.textContent = text;
      bubble.appendChild(answer);
      row.appendChild(bubble);
      return row;
    }

    function appendAssistant(data, text) {
      appendRow(buildAssistantRow(data, text));
    }

    function avatar(text) {
      const el = document.createElement("div");
      el.className = "avatar";
      el.textContent = text;
      return el;
    }

    function appendRow(row) {
      $("chat").appendChild(row);
      $("chat").scrollTop = $("chat").scrollHeight;
    }

    function removeWelcome() {
      const welcome = $("welcome");
      if (welcome) welcome.remove();
    }

    function createWelcome() {
      const wrap = document.createElement("div");
      wrap.id = "welcome";
      wrap.className = "welcome";
      wrap.innerHTML = `<h2>무엇을 확인할까요?</h2><div>RFP 문서 안의 내용을 근거와 함께 답합니다.</div>`;
      return wrap;
    }
  </script>
</body>
</html>
"""


class ServiceState:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.pipeline: RAGPipeline | None = None
        self.generator: HuggingFaceGenerator | None = None
        self.generator_key: tuple[Any, ...] | None = None
        self.init_lock = threading.Lock()
        self.generation_lock = threading.Lock()
        self.output_dir = Path(args.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def ask(
        self,
        question: str,
        *,
        history: list[dict[str, str]] | None = None,
        generate: bool,
        use_source_store: bool,
        max_new_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        total_started = time.perf_counter()
        clean_history = normalize_history(history)
        history_state = build_history_state(clean_history)
        standalone_question = build_standalone_question(question, clean_history)

        history_only_answer = answer_from_history_fast_path(question, history_state)
        if history_only_answer:
            payload = {
                "question": question,
                "model_loaded": self.generator is not None,
                "standalone_question": standalone_question,
                "history_turns_used": len(clean_history),
                "history": clean_history,
                "history_state": history_state,
                "answer": history_only_answer,
                "raw_answer": "",
                "retrieval_ms": 0,
                "context_ms": 0,
                "generation_ms": 0,
                "total_ms": int((time.perf_counter() - total_started) * 1000),
                "context_mode": self.args.context_mode,
                "generation_model": self.args.model,
                "adapter_path": self.adapter_path(),
                "load_in_4bit": self.load_in_4bit(),
                "question_analysis": {"history_fast_path": True},
                "context_char_count": 0,
                "guardrails": {"confidence": "high", "warnings": []},
                "retrieved_top5": [],
                "used_evidence_ids": [],
                "used_evidence_refs": [],
                "used_source_store_ids": [],
                "context_text": "",
            }
            output_path = self.save_payload(payload)
            payload["output_path"] = str(output_path)
            return payload

        pipeline = self.get_pipeline()
        retrieval_started = time.perf_counter()
        retrieved = pipeline.retrieve(standalone_question)
        retrieval_ms = int((time.perf_counter() - retrieval_started) * 1000)

        context_started = time.perf_counter()
        row = {"id": "service_query", "question": standalone_question, "retrieved_contexts": retrieved}
        resources = load_rfp_generation_resources(
            [row],
            chunks_path=self.resource_chunks_path(),
            source_store_path=self.args.source_store_path,
            use_source_store=use_source_store,
        )
        generation_input = build_rfp_generation_input(
            question=standalone_question,
            retrieved_contexts=retrieved,
            resources=resources,
            context_mode=self.args.context_mode,
            use_source_store=use_source_store,
        )
        if clean_history and standalone_question != question:
            inject_conversation_note(generation_input, clean_history, question)
        context_ms = int((time.perf_counter() - context_started) * 1000)

        answer = ""
        raw_answer = ""
        guardrails: dict[str, Any] = {"confidence": "not_run", "warnings": ["generation_not_run"]}
        generation_ms = 0

        if is_source_question(question):
            answer = compact_source_answer(retrieved, generation_input)
            guardrails = {"confidence": "high", "warnings": []}
            generate = False
        elif is_usage_question(question):
            answer = compact_usage_answer(history_state, retrieved, generation_input)
            guardrails = {"confidence": "high", "warnings": []}
            generate = False
        elif is_amount_recall_question(question, history_state):
            answer = compact_amount_recall_answer(history_state)
            guardrails = {"confidence": "high", "warnings": []}
            generate = False
        elif is_repeat_question(question, history_state):
            answer = history_state.get("last_assistant") or "문서에서 확인할 수 없습니다."
            guardrails = {"confidence": "high", "warnings": []}
            generate = False

        if generate:
            gen_started = time.perf_counter()
            generator = self.get_generator(max_new_tokens=max_new_tokens, temperature=temperature)
            with self.generation_lock:
                raw_answer = generator.generate_prompt(
                    generation_input.prompt,
                    system_prompt=generation_input.system_prompt,
                )
            processed = postprocess_rfp_generation_answer(raw_answer, generation_input)
            detailed_answer = dedupe_repeated_lines(str(processed.get("answer") or ""))
            answer = compact_service_answer(detailed_answer, generation_input)
            generation_input.extra_payload["raw_answer"] = raw_answer
            generation_input.extra_payload["detailed_answer"] = detailed_answer
            generation_input.extra_payload["advanced_answer"] = processed
            guardrails = advanced_guardrails(processed)
            generation_ms = int((time.perf_counter() - gen_started) * 1000)

        payload = {
            "question": question,
            "model_loaded": self.generator is not None,
            "standalone_question": standalone_question,
            "history_turns_used": len(clean_history),
            "history": clean_history,
            "history_state": history_state,
            "answer": answer,
            "raw_answer": raw_answer,
            "retrieval_ms": retrieval_ms,
            "context_ms": context_ms,
            "generation_ms": generation_ms,
            "total_ms": int((time.perf_counter() - total_started) * 1000),
            "context_mode": self.args.context_mode,
            "generation_model": self.args.model,
            "adapter_path": self.adapter_path(),
            "load_in_4bit": self.load_in_4bit(),
            "question_analysis": generation_input.extra_payload.get("question_analysis"),
            "context_char_count": generation_input.extra_payload.get("context_char_count"),
            "guardrails": guardrails,
            "retrieved_top5": [
                summarize_retrieved(item, rank) for rank, item in enumerate(retrieved[:5], 1)
            ],
            "used_evidence_ids": generation_input.extra_payload.get("used_evidence_ids", []),
            "used_evidence_refs": generation_input.extra_payload.get("used_evidence_refs", []),
            "used_source_store_ids": generation_input.extra_payload.get("used_source_store_ids", []),
            "context_text": generation_input.context_text,
        }
        output_path = self.save_payload(payload)
        payload["output_path"] = str(output_path)
        return payload

    def get_pipeline(self) -> RAGPipeline:
        if self.pipeline is not None:
            return self.pipeline
        with self.init_lock:
            if self.pipeline is None:
                self.pipeline = RAGPipeline(
                    chunk_path=self.args.chunks,
                    retriever_type="dense",
                    top_k=self.args.top_k,
                    index_dir=self.args.index_dir,
                    embedding_preset=self.args.embedding_preset,
                    vector_store_type="chroma",
                    chroma_collection=self.args.chroma_collection,
                    build_dense_index=False,
                    query_decomposition=True,
                    decomposition_conditional=True,
                    decomposition_candidates_per_query=self.args.retrieval_candidates,
                    decomposition_max_queries=8,
                    decomposition_selection="round_robin",
                    document_scoring=True,
                    doc_score_candidates=self.args.doc_score_candidates,
                    doc_score_method="mean_top_n",
                    doc_score_top_n=3,
                    target_aware=True,
                    target_candidates=self.args.target_candidates,
                    target_quota=1,
                    target_min_count=2,
                    target_max_count=5,
                )
        return self.pipeline

    def get_generator(self, *, max_new_tokens: int, temperature: float) -> HuggingFaceGenerator:
        key = (
            self.args.model,
            self.args.device,
            self.args.torch_dtype,
            self.load_in_4bit(),
            self.adapter_path(),
            max_new_tokens,
            temperature,
        )
        if self.generator is not None and self.generator_key == key:
            return self.generator
        with self.init_lock:
            if self.generator is None or self.generator_key != key:
                self.generator = HuggingFaceGenerator(
                    model_name=self.args.model,
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    device=self.args.device,
                    torch_dtype=self.args.torch_dtype,
                    load_in_4bit=self.load_in_4bit(),
                    enable_thinking=False,
                    adapter_path=self.adapter_path(),
                )
                self.generator_key = key
        return self.generator

    def adapter_path(self) -> str | None:
        return DEFAULT_BEST_ADAPTER if self.args.use_best_adapter else self.args.adapter_path

    def load_in_4bit(self) -> bool:
        return bool(self.args.load_in_4bit or self.args.use_best_adapter)

    def resource_chunks_path(self) -> str:
        index_chunks = Path(self.args.index_dir) / "chunks.json"
        if index_chunks.exists():
            return str(index_chunks)
        return self.args.chunks

    def save_payload(self, payload: dict[str, Any]) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        output_path = self.output_dir / f"rag_service_web_{stamp}.json"
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path


FOLLOWUP_MARKERS = (
    "그", "그럼", "그거", "해당", "위", "방금", "이 사업", "이 문서",
    "같은", "또", "추가", "비교", "둘", "각각", "그러면", "이번에는",
)


def normalize_history(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    cleaned: list[dict[str, str]] = []
    for item in value[-10:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = " ".join(str(item.get("content") or "").split())
        if role not in {"user", "assistant"} or not content:
            continue
        cleaned.append({"role": role, "content": content[:1200]})
    return cleaned[-8:]


def build_standalone_question(question: str, history: list[dict[str, str]]) -> str:
    question = question.strip()
    if not history or not looks_like_followup(question):
        return question
    state = build_history_state(history)
    focus = state.get("focus_subject") or ""
    if focus:
        return f"대상 사업/문서: {focus}\n현재 질문: {question}"
    recent_user_turns = [turn["content"] for turn in history if turn.get("role") == "user"]
    if not recent_user_turns:
        return question
    previous_focus = recent_user_turns[-1]
    return f"이전 질문 맥락: {previous_focus}\n현재 후속 질문: {question}"


def build_history_state(history: list[dict[str, str]]) -> dict[str, Any]:
    last_user = next((turn["content"] for turn in reversed(history) if turn.get("role") == "user"), "")
    last_assistant = next((turn["content"] for turn in reversed(history) if turn.get("role") == "assistant"), "")
    focus_subject = subject_from_history(history)
    recent_amount = ""
    for turn in reversed(history):
        if turn.get("role") != "assistant":
            continue
        recent_amount = extract_amount(turn.get("content") or "")
        if recent_amount:
            break
    return {
        "last_user": last_user,
        "last_assistant": last_assistant,
        "focus_subject": focus_subject,
        "recent_amount": recent_amount,
        "recent_docs": docs_from_history(history),
    }


def docs_from_history(history: list[dict[str, str]]) -> list[str]:
    docs: list[str] = []
    doc_pattern = re.compile(r"([^\s,;]+(?:\s[^,;]+){0,8}\.(?:pdf|hwp|hwpx))", re.IGNORECASE)
    for turn in reversed(history):
        content = unicodedata.normalize("NFC", turn.get("content") or "")
        for match in doc_pattern.finditer(content):
            doc = clean_source_file(match.group(1))
            if doc and doc not in docs:
                docs.append(doc)
            if len(docs) >= 3:
                return docs
    return docs


def looks_like_followup(question: str) -> bool:
    compact = " ".join(question.split())
    if len(compact) <= 28:
        return True
    return any(marker in compact for marker in FOLLOWUP_MARKERS)


def format_history_note(history: list[dict[str, str]], question: str) -> str:
    state = build_history_state(history)
    lines = ["[대화 이력 요약]", "아래 정보는 현재 질문의 지시어와 생략된 대상을 해석하기 위한 참고 정보입니다."]
    if state.get("focus_subject"):
        lines.append(f"- 현재 대화 대상: {state['focus_subject']}")
    if state.get("recent_amount"):
        lines.append(f"- 최근 확인 금액: {state['recent_amount']}")
    if state.get("recent_docs"):
        lines.append("- 최근 확인 문서: " + ", ".join(state["recent_docs"][:2]))
    if state.get("last_user"):
        lines.append(f"- 최근 사용자 질문: {state['last_user']}")
    if state.get("last_assistant"):
        lines.append(f"- 최근 답변 요약: {state['last_assistant'][:320]}")
    lines.append(f"- 현재 사용자 질문: {question}")
    return "\n".join(lines)


def inject_conversation_note(
    generation_input: Any,
    history: list[dict[str, str]],
    original_question: str,
) -> None:
    note = format_history_note(history, original_question)
    generation_input.context_text = note + "\n\n" + generation_input.context_text
    generation_input.prompt = generation_input.prompt.replace(
        "[Context]",
        note + "\n\n[Context]",
        1,
    )
    generation_input.extra_payload["conversation_history_used"] = history[-6:]
    generation_input.extra_payload["original_question"] = original_question


def summarize_retrieved(item: dict[str, Any], rank: int) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    text = str(item.get("text") or item.get("content") or "")
    return {
        "rank": rank,
        "score": item.get("score"),
        "chunk_id": item.get("chunk_id") or metadata.get("chunk_id"),
        "doc_id": item.get("doc_id") or metadata.get("doc_id"),
        "source_file": item.get("source_file") or metadata.get("source_file"),
        "section_path": metadata.get("section_path") or item.get("section_path"),
        "preview": " ".join(text.split())[:320],
    }



AMOUNT_PATTERNS = (
    re.compile(r"정규화 금액\s*[: ]\s*([0-9][0-9,]*원)"),
    re.compile(r"원문 금액\s*[: ]\s*([0-9][0-9,]*원)"),
    re.compile(r"사업(?:예산|금액|비)\s*[: ]\s*([0-9][0-9,]*원)"),
    re.compile(r"([0-9][0-9,]*원)"),
)



SOURCE_QUESTION_MARKERS = (
    "어떤 문서", "무슨 문서", "어느 문서", "출처", "근거 문서", "어디서 확인",
    "어디에서 확인", "문서에서 확인", "확인할 수 있어", "확인 가능",
)


USAGE_QUESTION_MARKERS = (
    "어디에 쓰", "어디에 사용", "어디 쓰", "어디 사용", "뭐에 쓰", "무엇에 쓰",
    "사용처", "용도", "쓰기로 했", "쓰기로했", "사용 목적",
)

AMOUNT_RECALL_MARKERS = ("얼마", "금액", "예산", "사업비", "몇 원", "몇원")
REPEAT_QUESTION_MARKERS = ("다시 말", "다시 알려", "한번 더", "한 번 더", "방금 답", "아까 답", "다시 설명")
AMBIGUOUS_SUBJECT_MARKERS = ("그", "그거", "그건", "그게", "해당", "이거", "이건", "그러면", "방금", "아까")


def is_source_question(question: str) -> bool:
    compact = " ".join(str(question or "").split())
    return any(marker in compact for marker in SOURCE_QUESTION_MARKERS)


def is_usage_question(question: str) -> bool:
    compact = " ".join(str(question or "").split())
    return any(marker in compact for marker in USAGE_QUESTION_MARKERS)


def is_amount_recall_question(question: str, history_state: dict[str, Any]) -> bool:
    if not history_state.get("recent_amount"):
        return False
    compact = " ".join(str(question or "").split())
    if not any(marker in compact for marker in AMOUNT_RECALL_MARKERS):
        return False
    return len(compact) <= 28 or any(marker in compact for marker in AMBIGUOUS_SUBJECT_MARKERS)


def is_repeat_question(question: str, history_state: dict[str, Any]) -> bool:
    if not history_state.get("last_assistant"):
        return False
    compact = " ".join(str(question or "").split())
    return len(compact) <= 28 and any(marker in compact for marker in REPEAT_QUESTION_MARKERS)


def answer_from_history_fast_path(question: str, history_state: dict[str, Any]) -> str:
    if is_usage_question(question) and history_state.get("focus_subject"):
        return f"그 예산은 {history_state['focus_subject']}에 쓰이는 예산입니다."
    if is_amount_recall_question(question, history_state):
        return compact_amount_recall_answer(history_state)
    if is_repeat_question(question, history_state):
        return history_state.get("last_assistant") or ""
    return ""


def compact_source_answer(retrieved: list[dict[str, Any]], generation_input: Any) -> str:
    docs: list[str] = []
    for item in retrieved:
        source = source_name_from_item(item)
        if not source:
            continue
        if source not in docs:
            docs.append(source)
        if len(docs) >= 2:
            break
    if not docs:
        refs = generation_input.extra_payload.get("used_evidence_refs") or []
        for ref in refs:
            source = clean_source_file(ref.get("source_file") or "")
            if source and source not in docs:
                docs.append(source)
            if len(docs) >= 2:
                break
    if not docs:
        return "문서에서 확인할 수 없습니다."
    if len(docs) == 1:
        return f"{docs[0]}에서 확인할 수 있습니다."
    return f"{docs[0]}에서 확인할 수 있습니다. 같은 내용은 {docs[1]}에서도 확인됩니다."


def compact_usage_answer(
    history_state: dict[str, Any],
    retrieved: list[dict[str, Any]],
    generation_input: Any,
) -> str:
    subject = history_state.get("focus_subject") or ""
    if not subject:
        analysis = generation_input.extra_payload.get("question_analysis") or {}
        subject = extract_subject("", "", analysis)
    if not subject or subject == "해당 사업":
        for item in retrieved:
            subject = clean_subject(source_name_from_item(item))
            if subject and subject != "해당 사업":
                break
    if not subject or subject == "해당 사업":
        return "문서에서 확인할 수 없습니다."
    return f"그 예산은 {subject}에 쓰이는 예산입니다."


def compact_amount_recall_answer(history_state: dict[str, Any]) -> str:
    amount = history_state.get("recent_amount") or ""
    if not amount:
        return "문서에서 확인할 수 없습니다."
    subject = history_state.get("focus_subject") or "해당 사업"
    return f"{subject}의 예산은 {amount_with_korean_hint(amount)}입니다."


def subject_from_history(history: list[dict[str, str]]) -> str:
    for turn in reversed(history):
        if turn.get("role") != "assistant":
            continue
        content = unicodedata.normalize("NFC", turn.get("content") or "")
        patterns = (
            r"(.+?)의\s*(?:사업)?예산은\s*[0-9][0-9,]*원",
            r"그\s*예산은\s*(.+?)에\s*쓰이는",
            r"해당\s*예산은\s*(.+?)에\s*쓰이는",
            r"(.+?)에서 확인할 수 있습니다",
        )
        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                return clean_subject(match.group(1))
    for turn in reversed(history):
        if turn.get("role") != "user":
            continue
        content = unicodedata.normalize("NFC", turn.get("content") or "")
        prefix = re.split(r"(?:의)?\s*(?:사업예산|예산|사업비|사업금액|금액|제출서류|마감|기간)", content, maxsplit=1)[0].strip()
        if prefix and not is_ambiguous_subject(prefix):
            return clean_subject(prefix)
    return ""


def source_name_from_item(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    source = item.get("source_file") or metadata.get("source_file_nfc") or metadata.get("source_file") or ""
    return clean_source_file(source)


def clean_source_file(value: str) -> str:
    value = unicodedata.normalize("NFC", str(value or "")).strip()
    value = value.replace("_", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def compact_service_answer(answer: str, generation_input: Any) -> str:
    answer = normalize_answer_text(answer)
    if not answer:
        return "문서에서 확인할 수 없습니다."
    if "문서에서 확인할 수 없습니다" in answer:
        return first_sentence_or_line(answer)

    analysis = generation_input.extra_payload.get("question_analysis") or {}
    answer_type = str(analysis.get("answer_type") or "")
    question = str(generation_input.extra_payload.get("original_question") or generation_input.question or "")

    if answer_type == "budget" or any(word in question for word in ("예산", "사업비", "사업금액", "금액")):
        return compact_budget_answer(answer, question, analysis)

    return trim_to_service_answer(answer)


def compact_budget_answer(answer: str, question: str, analysis: dict[str, Any]) -> str:
    if any(word in question for word in ("더 작은", "더 큰", "비교", "차이", "합산", "합계")):
        return compact_comparison_answer(answer)

    amount = extract_amount(answer)
    subject = extract_subject(question, answer, analysis)
    if amount:
        display_amount = amount_with_korean_hint(amount)
        return f"{subject}의 예산은 {display_amount}입니다."
    return trim_to_service_answer(answer)


def compact_comparison_answer(answer: str) -> str:
    lines = [line.strip(" -") for line in answer.splitlines() if line.strip()]
    if not lines:
        return "문서에서 확인할 수 없습니다."
    first = lines[0]
    if not first.endswith((".", "다.", "요.")):
        first += "."
    amount_lines = [line for line in lines[1:] if "원" in line][:2]
    if amount_lines:
        cleaned = [clean_line_for_chat(line) for line in amount_lines]
        return first + " " + " ".join(cleaned)
    return first



def amount_with_korean_hint(amount: str) -> str:
    won = int(re.sub(r"[^0-9]", "", amount or "") or 0)
    if won < 100_000_000:
        return amount
    return f"{amount}({korean_won_approx(won)})"


def korean_won_approx(won: int) -> str:
    eok = won // 100_000_000
    man = (won % 100_000_000) // 10_000
    if man:
        if man % 1000 == 0:
            man_text = f"{man // 1000}천만"
        else:
            man_text = f"{man:,}만"
        return f"약 {eok}억 {man_text} 원"
    return f"약 {eok}억 원"


def extract_amount(text: str) -> str:
    for pattern in AMOUNT_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return ""


def extract_subject(question: str, answer: str, analysis: dict[str, Any]) -> str:
    slots = analysis.get("target_slots") or []
    for slot in slots:
        label = str(slot.get("target_label") or "").strip()
        if label:
            return clean_subject(label)

    doc_match = re.search(r"문서명\s*[: ]\s*([^|\n]+)", answer)
    if doc_match:
        return clean_subject(doc_match.group(1))

    source_match = re.search(r"-\s*([^:\n]+\.(?:pdf|hwp|hwpx))\s*:", answer, flags=re.IGNORECASE)
    if source_match:
        return clean_subject(source_match.group(1))

    prefix = re.split(r"(?:의)?\s*(?:사업예산|예산|사업비|사업금액|금액)", question, maxsplit=1)[0].strip()
    if prefix and not is_ambiguous_subject(prefix):
        return clean_subject(prefix)
    return "해당 사업"


def is_ambiguous_subject(value: str) -> bool:
    compact = " ".join(str(value or "").split())
    if not compact:
        return True
    if compact in AMBIGUOUS_SUBJECT_MARKERS:
        return True
    return any(compact.startswith(marker) for marker in AMBIGUOUS_SUBJECT_MARKERS)


def clean_subject(value: str) -> str:
    value = unicodedata.normalize("NFC", str(value)).strip()
    value = re.sub(r"\.(pdf|hwp|hwpx)$", "", value, flags=re.IGNORECASE)
    value = value.replace("_", " ").replace("  ", " ").strip()
    value = re.sub(r"\s*재공고$", "", value).strip()
    if value == "고려대":
        return "고려대학교"
    return value or "해당 사업"


def normalize_answer_text(answer: str) -> str:
    text = unicodedata.normalize("NFC", str(answer or ""))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def first_sentence_or_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return clean_line_for_chat(line)
    return "문서에서 확인할 수 없습니다."


def trim_to_service_answer(text: str) -> str:
    lines = []
    stop_prefixes = ("근거", "문서명", "비교 금액", "계산 과정", "판단", "기준 사업예산")
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if lines:
                break
            continue
        if any(line.startswith(prefix) for prefix in stop_prefixes) and lines:
            break
        lines.append(clean_line_for_chat(line))
        if len(" ".join(lines)) >= 180:
            break
    if not lines:
        return "문서에서 확인할 수 없습니다."
    result = " ".join(lines).strip()
    return result[:260].rstrip()


def clean_line_for_chat(line: str) -> str:
    line = unicodedata.normalize("NFC", str(line))
    line = re.sub(r"\([^)]*chunk[^)]*\)", "", line, flags=re.IGNORECASE)
    line = line.replace("원문 금액", "원문").replace("정규화 금액", "정규화")
    return " ".join(line.split())


class RAGRequestHandler(BaseHTTPRequestHandler):
    state: ServiceState

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self.send_bytes(APP_HTML.encode("utf-8"), content_type="text/html; charset=utf-8")
            return
        if path == "/health":
            self.send_json({"ok": True, "service": "rag_service_web"})
            return
        self.send_error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/ask":
            self.send_error(HTTPStatus.NOT_FOUND, "not found")
            return
        try:
            body = self.read_json_body()
            question = str(body.get("question") or "").strip()
            if not question:
                self.send_json({"error": "question is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            payload = self.state.ask(
                question,
                history=normalize_history(body.get("history")),
                generate=bool(body.get("generate", True)),
                use_source_store=bool(body.get("use_source_store", True)),
                max_new_tokens=clamp_int(body.get("max_new_tokens", 512), 64, 1024),
                temperature=clamp_float(body.get("temperature", 0.1), 0.0, 1.0),
            )
            self.send_json(payload)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("JSON body must be an object")
        return parsed

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_bytes(
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            status=status,
            content_type="application/json; charset=utf-8",
        )

    def send_bytes(
        self,
        data: bytes,
        *,
        status: HTTPStatus = HTTPStatus.OK,
        content_type: str = "application/octet-stream",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("[rag-service] " + format % args + "\n")


def clamp_int(value: Any, lower: int, upper: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = lower
    return max(lower, min(upper, parsed))


def clamp_float(value: Any, lower: float, upper: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = lower
    return max(lower, min(upper, parsed))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local web UI for the RAG QA service.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--chunks", default=DEFAULT_CHUNKS)
    parser.add_argument("--index-dir", default=DEFAULT_INDEX)
    parser.add_argument("--source-store-path", default=DEFAULT_SOURCE_STORE)
    parser.add_argument("--context-mode", default="rfp_service_route_v3")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--retrieval-candidates", type=int, default=75)
    parser.add_argument("--doc-score-candidates", type=int, default=300)
    parser.add_argument("--target-candidates", type=int, default=30)
    parser.add_argument("--embedding-preset", default="kure")
    parser.add_argument("--chroma-collection", default="rfp_chunks")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--device")
    parser.add_argument("--load-in-4bit", action="store_true")
    parser.add_argument("--adapter-path")
    parser.add_argument(
        "--use-best-adapter",
        action="store_true",
        default=True,
        help=f"Use the current best PEFT adapter: {DEFAULT_BEST_ADAPTER}",
    )
    parser.add_argument("--no-best-adapter", action="store_false", dest="use_best_adapter")
    parser.add_argument("--torch-dtype", default="auto")
    parser.add_argument("--output-dir", default="outputs/service_runs")
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()
    RAGRequestHandler.state = ServiceState(args)
    server = ThreadingHTTPServer((args.host, args.port), RAGRequestHandler)
    print(f"[rag-service] listening on http://{args.host}:{args.port}")
    print("[rag-service] first generated answer will load the local model and may take a while")
    server.serve_forever()


if __name__ == "__main__":
    main()
