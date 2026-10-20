from jobscout.db.models import Base
from jobscout.db.session import engine


def main():
    Base.metadata.create_all(engine)
    print("Database ready. Tables:", ", ".join(Base.metadata.tables))


if __name__ == "__main__":
    main()
