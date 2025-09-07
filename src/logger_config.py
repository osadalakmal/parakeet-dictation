import logging
import os
from dotenv import load_dotenv

class ColoredFormatter(logging.Formatter):
    """Custom logging formatter with color support."""
    
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[1;31m' # Bold Red
    }
    RESET = '\033[0m'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_colors = os.getenv('NO_COLOR', 'false').lower() != 'true'
    
    def format(self, record):
        if self.use_colors:
            level_color = self.COLORS.get(record.levelname, '')
            record.levelname = f"{level_color}{record.levelname}{self.RESET}"
            
            log_message = super().format(record)
            
            if level_color:
                parts = log_message.split(' - ', 2)
                if len(parts) >= 3:
                    timestamp, level, message = parts[0], parts[1], ' - '.join(parts[2:])
                    return f"{timestamp} - {level} - {level_color}{message}{self.RESET}"
            
            return log_message
        else:
            return super().format(record)

def setup_logging():
    """Setup logging configuration with color support."""
    load_dotenv()
    
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S',
        handlers=[]
    )
    
    handler = logging.StreamHandler()
    handler.setFormatter(ColoredFormatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S'))
    
    logger = logging.getLogger()
    logger.handlers = []
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, log_level, logging.INFO))
    
    return logger