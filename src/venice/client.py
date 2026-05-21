"""Venice AI API client for A0T stakers."""

import httpx
from typing import Any, AsyncGenerator
import json

from src.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class VeniceClient:
    """Client for Venice AI API using A0T staking credits."""

    def __init__(self):
        self.base_url = settings.venice_base_url
        self.api_key = settings.venice_api_key.get_secret_value()
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=60.0,
        )

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str = "llama-3.3-70b",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stream: bool = False,
        venice_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any] | AsyncGenerator[str, None]:
        """Send a chat completion request to Venice AI.

        Args:
            messages: List of message dicts with role and content
            model: Model identifier (default: llama-3.3-70b)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            stream: Whether to stream the response
            venice_parameters: Venice-specific parameters

        Returns:
            Response dict or async generator for streaming
        """
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        if venice_parameters:
            payload["venice_parameters"] = venice_parameters

        try:
            if stream:
                return self._stream_chat(payload)

            response = await self.client.post(
                "/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            # Log usage for monitoring
            usage = data.get("usage", {})
            logger.info(
                "venice_chat_completion",
                model=model,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
            )

            return data

        except httpx.HTTPStatusError as e:
            logger.error(
                "venice_api_error",
                status_code=e.response.status_code,
                response=e.response.text,
            )
            raise
        except Exception as e:
            logger.error("venice_request_failed", error=str(e))
            raise

    async def _stream_chat(
        self,
        payload: dict[str, Any],
    ) -> AsyncGenerator[str, None]:
        """Stream chat completion from Venice AI."""
        async with self.client.stream(
            "POST",
            "/chat/completions",
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0].get("delta", {})
                        if "content" in delta:
                            yield delta["content"]
                    except (json.JSONDecodeError, KeyError):
                        continue

    async def analyze_opportunity(
        self,
        token_data: dict[str, Any],
        holder_data: dict[str, Any],
        volume_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Use Venice AI to analyze a trading opportunity.

        Focuses on holder behavior and volume patterns before price signals.
        """
        system_prompt = """You are an expert crypto market analyst specializing in 
        on-chain data analysis. You focus on holder behavior and volume patterns 
        as leading indicators before traditional chart signals.

        Analyze the provided data and return a JSON response with:
        - signal: "buy", "sell", "hold", or "avoid"
        - confidence: 0.0 to 1.0
        - reasoning: detailed explanation
        - risk_level: "low", "medium", "high"
        - suggested_position_size_pct: recommended position size as % of portfolio
        - key_indicators: list of specific signals you identified
        """

        user_prompt = f"""Analyze this token opportunity:

        Token Data:
        {json.dumps(token_data, indent=2)}

        Holder Data:
        {json.dumps(holder_data, indent=2)}

        Volume Data:
        {json.dumps(volume_data, indent=2)}

        Return your analysis as valid JSON."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = await self.chat_completion(
            messages=messages,
            model="llama-3.3-70b",
            temperature=0.3,
            max_tokens=2048,
            venice_parameters={
                "include_venice_system_prompt": False,
                "disable_thinking": True,
            },
        )

        content = response["choices"][0]["message"]["content"]

        # Extract JSON from response
        try:
            # Try to find JSON in the response
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0]
            else:
                json_str = content

            analysis = json.loads(json_str.strip())
            return analysis

        except (json.JSONDecodeError, IndexError) as e:
            logger.error("failed_to_parse_analysis", content=content, error=str(e))
            return {
                "signal": "avoid",
                "confidence": 0.0,
                "reasoning": f"Failed to parse AI analysis: {str(e)}",
                "risk_level": "high",
                "suggested_position_size_pct": 0.0,
                "key_indicators": [],
            }

    async def generate_service_pitch(
        self,
        service_name: str,
        target_audience: str,
        features: list[str],
    ) -> str:
        """Generate a marketing pitch for a service offering."""
        messages = [
            {
                "role": "system",
                "content": "You are a persuasive but honest sales copywriter for AI-powered business services.",
            },
            {
                "role": "user",
                "content": f"""Create a compelling pitch for {service_name} targeting {target_audience}.

                Key features:
                {chr(10).join(f"- {f}" for f in features)}

                Keep it under 200 words, focus on value and ROI.""",
            },
        ]

        response = await self.chat_completion(
            messages=messages,
            model="llama-3.3-70b",
            temperature=0.8,
            max_tokens=500,
        )

        return response["choices"][0]["message"]["content"]

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
