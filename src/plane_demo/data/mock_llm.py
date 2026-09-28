"""Deterministic OpenAI-compatible chat backend for offline local data planes."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from plane_demo.data.llm_gateway import ChatMessage
from plane_demo.shared.http import base_app
from plane_demo.shared.settings import Settings


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: Annotated[str, Field(min_length=1, max_length=128)]
    messages: Annotated[list[ChatMessage], Field(min_length=1, max_length=32)]


def create_app(settings: Settings):
    app = base_app(settings)

    @app.post("/v1/chat/completions")
    def chat_completion(request: ChatCompletionRequest):
        prompt = request.messages[-1].content
        # Echoing lets response guardrails be observed with synthetic data.
        reply = f"[{request.model}] echo: {prompt}"
        prompt_tokens = sum(len(message.content.split()) for message in request.messages)
        completion_tokens = len(reply.split())
        return {
            "id": "chatcmpl-plane-demo-mock",
            "object": "chat.completion",
            "created": 0,
            "model": request.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": reply},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }

    return app


def main() -> None:
    import uvicorn

    settings = Settings.from_env("mock_llm")
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.listen_port, access_log=False)


if __name__ == "__main__":
    main()
