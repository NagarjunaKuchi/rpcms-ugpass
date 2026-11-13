from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read from RPCMS_UGPASS_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="RPCMS_UGPASS_", env_file=".env", extra="ignore")

    jwt_key: str = Field(min_length=16)
    jwt_algorithm: str = "HS256"
    jwt_audience: str | None = None

    # Shared secret for HMAC-SHA256 over the raw callback body. ASSUMED scheme: confirm what
    # UGPass actually uses to authenticate callbacks and replace verify_callback if different.
    callback_secret: str = Field(min_length=16)

    database_url: str = "sqlite:///./rpcms_ugpass.db"
    # True (default, dev/tests): create tables at startup. Set False in production and run `alembic upgrade head`.
    create_tables: bool = True
    public_base_url: str = "https://rpcms.example.org"
    client_impl: str = "rpcms_ugpass.upstream.MockUgpassClient"
