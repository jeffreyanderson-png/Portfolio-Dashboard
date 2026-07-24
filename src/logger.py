from sqlmodel import Session, select
from sqlalchemy import create_engine
from datetime import datetime
from src.models import SystemLog, AppConfig

DB_URL = "sqlite:///data/portfolio.db"
engine = create_engine(DB_URL)

def get_config(key: str, default: str = "") -> str:
    """Retrieves a configuration value from the database."""
    with Session(engine) as session:
        config = session.exec(select(AppConfig).where(AppConfig.config_key == key)).first()
        return config.config_value if config else default

def set_config(key: str, value: str, description: str = ""):
    """Sets a configuration value and updates the timestamp."""
    with Session(engine) as session:
        config = session.exec(select(AppConfig).where(AppConfig.config_key == key)).first()
        if config:
            config.config_value = str(value)
            config.last_updated = datetime.now()
        else:
            config = AppConfig(config_key=key, config_value=str(value), description=description)
            session.add(config)
        session.commit()

def log_event(level: str, source: str, message: str):
    """Writes a log to the database and auto-prunes based on MAX_LOG_SIZE."""
    with Session(engine) as session:
        # 1. Insert the new log
        new_log = SystemLog(level=level, source=source, message=message)
        session.add(new_log)
        session.commit()
        
        # 2. Fetch the Max Log Size limit
        max_size_str = get_config("MAX_LOG_SIZE", "100")
        try:
            max_size = int(max_size_str)
        except ValueError:
            max_size = 100
            
        # 3. Auto-Pruning: Delete oldest logs if we exceed the limit
        count = session.query(SystemLog).count()
        if count > max_size:
            excess = count - max_size
            oldest_logs = session.exec(
                select(SystemLog).order_by(SystemLog.timestamp.asc()).limit(excess)
            ).all()
            
            for log in oldest_logs:
                session.delete(log)
            session.commit()