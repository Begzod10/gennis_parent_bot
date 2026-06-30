from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool
from app.config import DATABASE_URL

# Small pool for the webhook server (web workers)
engine = create_engine(DATABASE_URL, echo=False, pool_size=3, max_overflow=2)
Base = declarative_base()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# NullPool engine for Celery tasks — creates/destroys connections per-use
# so Celery doesn't hold open connections between task runs
celery_engine = create_engine(DATABASE_URL, echo=False, poolclass=NullPool)
CelerySession = sessionmaker(autocommit=False, autoflush=False, bind=celery_engine)
