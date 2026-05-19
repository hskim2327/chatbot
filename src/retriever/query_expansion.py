import os

from openai import OpenAI


class OpenAIQueryExpander:
    def __init__(self, api_key: str | None = None, model: str = "gpt-5-mini", num_queries: int = 3):
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.model = model
        self.num_queries = num_queries

    def expand(self, query: str) -> list[str]:
        if self.num_queries <= 1:
            return [query]

        prompt = f"""
아래 RFP 검색 질문을 같은 의미의 검색 질의 {self.num_queries - 1}개로 바꿔라.
기관명, 사업명, 금액, 날짜 같은 핵심 고유명사는 유지해라.
각 줄에는 질의만 써라.

[원 질문]
{query}
""".strip()
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "검색 질의 확장 전문가"},
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content or ""
        variants = [line.strip(" -0123456789.	") for line in content.splitlines()]
        variants = [line for line in variants if line]

        queries = [query]
        for variant in variants:
            if variant not in queries:
                queries.append(variant)
            if len(queries) >= self.num_queries:
                break
        return queries


class StaticQueryExpander:
    def expand(self, query: str) -> list[str]:
        return [query]
