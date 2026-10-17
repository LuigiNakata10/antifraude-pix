from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Text, UniqueConstraint, func

from models.base import Base
from models import PixAnalysis


class AccountLink(Base):
    __tablename__ = "account_link"

    id = Column(BigInteger, primary_key=True)
    pix_analysis_id = Column(BigInteger, ForeignKey(PixAnalysis.id), nullable=False)
    from_key = Column(Text, nullable=False)
    to_key = Column(Text, nullable=False)
    link_type = Column(Text, nullable=False)
    amount = Column(BigInteger, nullable=True)
    seen_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("pix_analysis_id", "link_type", "from_key", "to_key"),)
