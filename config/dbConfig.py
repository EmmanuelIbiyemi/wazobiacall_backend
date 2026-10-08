from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyHttpUrl, PostgresDsn, field_validator
import os
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    PROJECT_NAME: str = "ECO DASH SECTION"
    API_V1_STR: str = "/api/v1"

    # Database
    SQLALCHEMY_DATABASE_URI: Optional[str] = None

    # Redis
    # REDIS_HOST: str = str(os.getenv("REDIS_HOST"))
    # REDIS_PORT: str = str(os.getenv("REDIS_PORT"))
    # REDIS_DB: int = int(os.getenv("REDIS_DB", 0))
    # REDIS_PASSWORD: Optional[str] = str(os.getenv("REDIS_PASSWORD"))

   
    
    def assemble_db_connection(self) -> str:
        if self.SQLALCHEMY_DATABASE_URI:
            return self.SQLALCHEMY_DATABASE_URI

        return str(PostgresDsn.build(
            scheme="postgresql",
            username=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            host=os.getenv("DB_HOST"),
            port=int(os.getenv("DB_PORT", 5432)),
            path=f"{os.getenv('DB_DATABASE')}",
        ))

    def get_database_url(self) -> str:
        return self.assemble_db_connection()

    
    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        extra="allow"
    )


# instantiate settings
settings = Settings()
