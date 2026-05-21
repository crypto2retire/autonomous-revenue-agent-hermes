import httpx, asyncio, os, json

async def test():
    key = os.environ.get("VENICE_API_KEY","")
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.venice.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": "claude-opus-4.6",
                "messages": [{"role": "user", "content": "Analyze token NAM at price 0.0001, volume 5000, liquidity 10000. Return ONLY JSON with fields: signal (buy/sell/hold/avoid), confidence (0-1), reasoning (string), risk_level (low/medium/high), tags (string)"}],
                "max_tokens": 500,
            },
        )
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        print("Raw content:")
        print(content)
        print()
        # Try to extract JSON
        if "json" in content and content.count("```") >= 2:
            content = content.split("```")[1].replace("json", "").strip()
        try:
            parsed = json.loads(content.strip())
            print("Parsed:", parsed)
        except Exception as e:
            print("Parse error:", e)

asyncio.run(test())
