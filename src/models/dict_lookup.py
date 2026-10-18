from sqlalchemy import BigInteger, Column, DateTime, Text, func
from sqlalchemy.dialects.postgresql import JSONB

from models.base import Base


class DictLookup(Base):
    __tablename__ = "dict_lookup"

    id = Column(BigInteger, primary_key=True)
    account_key = Column(Text, nullable=False)
    response = Column(JSONB, nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
