from dataclasses import dataclass
from os import environ

@dataclass
class DbConfig:
    user: str
    password: str
    database: str
    host: str

@dataclass
class BotConfig:
    token: str
    channel_id: int

@dataclass
class SecurityConfig:
    encryption_key: str

@dataclass
class RedisConfig:
    host: str
    port: int

@dataclass
class Config:
    bot: BotConfig
    db: DbConfig
    security: SecurityConfig
    redis: RedisConfig

def load_config() -> Config:
    """Loads configuration from environment variables."""
    return Config(
        bot=BotConfig(
            token=environ.get("TELEGRAM_BOT_TOKEN"),
            channel_id=int(environ.get("TARGET_CHANNEL_ID"))
        ),
        security=SecurityConfig(
            encryption_key=environ.get("ENCRYPTION_KEY")
        ),
        db=DbConfig(
            user=environ.get("DB_USER", "postgres"),
            password=environ.get("DB_PASS", "postgres"),
            database=environ.get("DB_NAME", "auksion"),
            host=environ.get("DB_HOST", "localhost")
        ),
        redis=RedisConfig(
            host=environ.get("REDIS_HOST", "localhost"),
            port=int(environ.get("REDIS_PORT", 6379))
        )
    )
