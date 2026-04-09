"""
Telecoupling AI - Application Configuration

Loads settings from environment variables / .env file.
"""

from pydantic_settings import BaseSettings
from typing import List
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # --- LLM Provider ---
    # "purdue" uses Purdue GenAI Studio (OpenAI-compatible, free)
    # "gemini" uses Google Gemini
    llm_provider: str = "purdue"

    # --- Purdue GenAI Studio ---
    purdue_api_key: str = ""
    purdue_base_url: str = "https://genai.rcac.purdue.edu/api"
    purdue_model: str = "llama3.1:latest"

    # --- Google Gemini (fallback) ---
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # --- MCP Servers ---
    invest_mcp_port: int = 54320
    qgis_mcp_port: int = 54321

    # --- Backend ---
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    cors_origins: List[str] = ["http://localhost:5173"]

    # --- Data Paths ---
    invest_sample_data_dir: str = "./data/sample-inputs"
    invest_output_dir: str = "./data/outputs"
    workspace_dir: str = "./data/outputs"
    upload_dir: str = "./data/uploads"

    # --- Logging ---
    log_level: str = "INFO"

    model_config = {
        "env_file": os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            ".env",
        ),
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }

    @property
    def active_model(self) -> str:
        if self.llm_provider == "purdue":
            return self.purdue_model
        return self.gemini_model


settings = Settings()
