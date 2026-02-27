from sqlalchemy import Boolean, Column, Integer, String, DateTime, func, text
from .db import Base

class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(120), nullable=False)
    whatsapp = Column(String(30), nullable=False)
    email = Column(String(120), nullable=True)
    origem = Column(String(40), nullable=True)  # instagram/whatsapp/igreja/escola
    email_pagamento = Column(String(120), nullable=True)  # conferência simples (MVP)
    cpf = Column(String(20), nullable=True)

    logradouro = Column(String(140), nullable=True)
    numero = Column(String(20), nullable=True)
    complemento = Column(String(80), nullable=True)
    bairro = Column(String(80), nullable=True)
    cidade = Column(String(80), nullable=True)
    uf = Column(String(2), nullable=True)
    cep = Column(String(20), nullable=True)

    status = Column(String(20), nullable=False, server_default=text("'cadastrado'"))

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(30), nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, server_default=text("true"), index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    action = Column(String(60), nullable=False, index=True)
    admin_user = Column(String(120), nullable=True, index=True)

    student_id = Column(Integer, nullable=True, index=True)
    student_name = Column(String(120), nullable=True)
    student_whatsapp = Column(String(30), nullable=True)

    ip = Column(String(45), nullable=True)
