from sqlalchemy import CHAR, BigInteger, Boolean, Column, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from models.base import Base
from models import PayerAccount


class PixAnalysis(Base):
    __tablename__ = "pix_analysis"

    id = Column(BigInteger, primary_key=True)
    transaction_id = Column(Text, nullable=False)
    analysis_key = Column(CHAR(36), nullable=False)
    payer_account_id = Column(BigInteger, ForeignKey(PayerAccount.id), nullable=False)
    amount = Column(BigInteger, nullable=False)
    transaction_date = Column(DateTime(timezone=True), nullable=False)
    source_opening_date = Column(DateTime(timezone=True), nullable=False)
    payer_document = Column(Text, nullable=False)
    device_id = Column(Text, nullable=False)
    destination_key = Column(Text, nullable=False)
    destination_document = Column(Text, nullable=False)
    destination_opening_date = Column(DateTime(timezone=True), nullable=False)
    payer_dict_e1 = Column(Boolean, nullable=True)
    payer_dict_e4 = Column(Boolean, nullable=True)
    destination_dict_e1 = Column(Boolean, nullable=True)
    destination_dict_e4 = Column(Boolean, nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=False)
    analyzed_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(Text, nullable=False)
    reason_code = Column(Text, nullable=False)
    policy_version = Column(Text, nullable=False)
    # `metadata` é um nome reservado do declarative_base: o atributo muda de
    # nome, a coluna continua `metadata`.
    analysis_metadata = Column("metadata", JSONB, nullable=False)
    analysis_details = Column(JSONB, nullable=False, server_default="{}")
    request_payload = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("transaction_id"),
        UniqueConstraint("analysis_key"),
    )

    payer_account = relationship("PayerAccount", foreign_keys=[payer_account_id])
