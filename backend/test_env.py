from dotenv import load_dotenv
import os
from pathlib import Path

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

print("Secret Key:", os.getenv("INTASEND_SECRET_KEY"))
