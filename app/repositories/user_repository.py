import uuid

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self.session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        return self.session.scalar(select(User).where(func.lower(User.email) == email.lower()))

    def any_exist(self) -> bool:
        return bool(self.session.scalar(select(exists().select_from(User))))

    def add(self, user: User) -> User:
        self.session.add(user)
        self.session.flush()
        return user
