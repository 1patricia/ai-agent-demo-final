"""全局配置模块 —— 双模式一键切换（Ollama 本地 / DeepSeek 云端）"""
import os
from pathlib import Path

# 加载 .env 文件（优先项目根目录）
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    with open(_env_path, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _, _val = _line.partition("=")
            os.environ.setdefault(_key.strip(), _val.strip())


# ============================================================
# 一键切换：修改 .env 中 LLM_MODE=ollama 或 LLM_MODE=deepseek
# ============================================================
LLM_MODE = os.getenv("LLM_MODE", "ollama")  # "ollama" | "deepseek"


# ============================================================
# 本地 Ollama 配置
# ============================================================
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen:7b-q3_K_M")


# ============================================================
# DeepSeek 云端配置（OpenAI 兼容接口）
# ============================================================
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# 通用推理参数（本地 num_predict / 云端 max_tokens 统一用此值）
MAX_TOKENS = 1024
TEMPERATURE = 0.05
