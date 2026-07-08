# app/api/v1/opay.py
"""app/api/v1/opay.py — Tenant Opay configuration: bank details, subaccounts."""
import logging
from fastapi import APIRouter, Depends
from app.utils.responses import api_response

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Opay"])

