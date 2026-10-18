from sqlalchemy import BigInteger, Column, DateTime, String, UniqueConstraint, func

from models.base import Base


class PayerAccount(Base):
    __tablename__ = "payer_account"

    id = Column(BigInteger, primary_key=True)
    branch = Column(String(10), nullable=False)
    account_number = Column(String(20), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("branch", "account_number"),)
