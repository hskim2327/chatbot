"""Phase 4 문서와 환경 설정 파일 테스트."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVALUATION_ROOT = PROJECT_ROOT / "eval" / "evaluation"


def test_phase3_metric_guide_and_phase4_plan_exist():
    assert (EVALUATION_ROOT / "docs" / "phase3_domain_metric_guide.md").exists()
    assert (EVALUATION_ROOT / "docs" / "phase4_llm_judge_plan.md").exists()


def test_env_example_exists_without_real_key():
    env_example = EVALUATION_ROOT / ".env.example"
    text = env_example.read_text(encoding="utf-8")

    assert "OPENAI_API_KEY=" in text
    assert "sk-" not in text


def test_gitignore_excludes_env_but_allows_example():
    gitignore = PROJECT_ROOT / ".gitignore"
    text = gitignore.read_text(encoding="utf-8")

    assert ".env" in text
    assert "!.env.example" in text


def test_requirements_include_python_dotenv():
    text = (EVALUATION_ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "python-dotenv" in text
