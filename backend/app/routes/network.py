from fastapi import APIRouter

from app.services.network_service import network_status

router = APIRouter()


@router.get("/status")
def status():
    return network_status()
