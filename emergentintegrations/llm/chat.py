import os
from openai import OpenAI


class UserMessage:
    def __init__(self, content: str):
        self.content = content


class LlmChat:
    def __init__(self, model: str = "gpt-4o-mini"):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set")

        self.client = OpenAI(api_key=api_key)
        self.model = model

    async def run(self, messages):
        formatted_messages = [
            {"role": "user", "content": m.content}
            for m in messages
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=formatted_messages
        )

        return response.choices[0].message.content
