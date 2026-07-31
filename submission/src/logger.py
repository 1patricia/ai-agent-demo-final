# 日志模块
import logging
import os

def setup_logger():
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.mkdir(log_dir)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("logs/runtime.log", encoding="utf-8"),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger("interview_assistant")

logger = setup_logger()