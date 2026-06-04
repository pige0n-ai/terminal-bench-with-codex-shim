from __future__ import annotations


PROVIDER_ENV: dict[str, tuple[str, str, str | None]] = {
    "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"),
    "openai": ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"),
    "openrouter": ("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", None),
    "xiaomi-mimo": ("XIAOMI_MIMO_API_KEY", "XIAOMI_MIMO_BASE_URL", "XIAOMI_MIMO_MODEL"),
    "novita": ("NOVITA_API_KEY", "NOVITA_BASE_URL", None),
    "fireworks": ("FIREWORKS_API_KEY", "FIREWORKS_BASE_URL", None),
    "siliconflow": ("SILICONFLOW_API_KEY", "SILICONFLOW_BASE_URL", "SILICONFLOW_MODEL"),
    "arcee": ("ARCEE_API_KEY", "ARCEE_BASE_URL", "ARCEE_MODEL"),
    "moonshot": ("MOONSHOT_API_KEY", "MOONSHOT_BASE_URL", "KIMI_MODEL"),
    "sglang": ("SGLANG_API_KEY", "SGLANG_BASE_URL", "SGLANG_MODEL"),
    "vllm": ("VLLM_API_KEY", "VLLM_BASE_URL", "VLLM_MODEL"),
    "ollama": ("OLLAMA_API_KEY", "OLLAMA_BASE_URL", "OLLAMA_MODEL"),
    "atlascloud": ("ATLASCLOUD_API_KEY", "ATLASCLOUD_BASE_URL", "ATLASCLOUD_MODEL"),
    "wanjie-ark": ("WANJIE_ARK_API_KEY", "WANJIE_ARK_BASE_URL", "WANJIE_ARK_MODEL"),
    "volcengine": ("VOLCENGINE_API_KEY", "VOLCENGINE_BASE_URL", "VOLCENGINE_MODEL"),
}


def provider_env_names(provider: str) -> tuple[str, str, str | None]:
    if provider not in PROVIDER_ENV:
        known = ", ".join(sorted(PROVIDER_ENV))
        raise ValueError(f"unsupported codewhale provider '{provider}'. Known providers: {known}")
    return PROVIDER_ENV[provider]
