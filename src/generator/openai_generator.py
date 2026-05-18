import os

from openai import OpenAI


class OpenAIGenerator:
    def __init__(self, api_key=None, model="gpt-5-mini"):
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.model = model

    def generate(self, query, contexts):
        context_text = "\n\n".join(contexts)

        prompt = f"""
너는 RFP 문서 분석 전문가다.

아래 문맥을 기반으로만 답변해라.
문맥에는 문서 본문과 문서 메타데이터가 포함될 수 있다.
예산, 발주기관, 사업명 같은 값은 문서 메타데이터도 근거로 사용해라.
문맥에 없는 내용은 추측하지 말고 모른다고 답해라.

[문맥]
{context_text}

[질문]
{query}
"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "정확하게 답변하는 AI"},
                {"role": "user", "content": prompt}
            ]
        )

        return response.choices[0].message.content