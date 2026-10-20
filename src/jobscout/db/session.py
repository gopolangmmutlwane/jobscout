from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from jobscout.config import DATABASE_URL

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session():
    return SessionLocal()
