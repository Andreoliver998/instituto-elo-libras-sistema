from sqlalchemy import Column, Integer, String, DateTime, func, text
from .db import Base

class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(120), nullable=False)
    whatsapp = Column(String(30), nullable=False)
    email = Column(String(120), nullable=True)
    origem = Column(String(40), nullable=True)  # instagram/whatsapp/igreja/escola
    email_pagamento = Column(String(120), nullable=True)  # conferência simples (MVP)

    logradouro = Column(String(140), nullable=True)
    numero = Column(String(20), nullable=True)
    complemento = Column(String(80), nullable=True)
    bairro = Column(String(80), nullable=True)
    cidade = Column(String(80), nullable=True)
    uf = Column(String(2), nullable=True)
    cep = Column(String(20), nullable=True)

    status = Column(String(20), nullable=False, server_default=text("'cadastrado'"))

    created_at = Column(DateTime(timezone=True), server_default=func.now())
