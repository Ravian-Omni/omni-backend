"""One-shot completions on the default chat model (copy rewrites, starter prompts)."""

from openai import AsyncOpenAI

from src.configs.llm_configs_manager import LLMConfigManager


async def complete(system: str, user: str, max_tokens: int = 800, json_mode: bool = False) -> str:
    """The model's reply text; json_mode asks for a single JSON object."""
    cfg = (LLMConfigManager.get_config("default").get("config_list") or [{}])[0]
    client = AsyncOpenAI(api_key=cfg.get("api_key"), base_url=cfg.get("base_url"))
    r = await client.chat.completions.create(
        model=cfg.get("model"), extra_body=cfg.get("extra_body"), max_completion_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        **({"response_format": {"type": "json_object"}} if json_mode else {}),
    )
    return (r.choices[0].message.content or "").strip()


async def describe_image(data: bytes, mime: str, ask: str) -> str:
    """What the model sees in an image (an ad creative), for agents that only read text."""
    import base64

    cfg = (LLMConfigManager.get_config("default").get("config_list") or [{}])[0]
    client = AsyncOpenAI(api_key=cfg.get("api_key"), base_url=cfg.get("base_url"))
    r = await client.chat.completions.create(
        model=cfg.get("model"), extra_body=cfg.get("extra_body"), max_completion_tokens=500,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": ask},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}},
        ]}],
    )
    return (r.choices[0].message.content or "").strip()
