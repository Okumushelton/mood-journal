import os
from dotenv import load_dotenv
from intasend import APIService
from pathlib import Path

# Load .env file
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY")
INTASEND_TEST_MODE = os.getenv("INTASEND_TEST_MODE", "True").lower() == "true"

if not INTASEND_SECRET_KEY:
    raise Exception("❌ Missing IntaSend Secret Key in .env")

# Initialize IntaSend APIService with Secret Key
service = APIService(
    token=INTASEND_SECRET_KEY,
    test=INTASEND_TEST_MODE,
)
