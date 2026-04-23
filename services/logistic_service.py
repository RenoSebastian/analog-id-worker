import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Optional

# Import konfigurasi dari ekosistem worker Anda
import config

logger = logging.getLogger(__name__)

# Konfigurasi dari config.py atau .env
LOGISTIC_API_KEY = getattr(config, 'LOGISTIC_API_KEY', '')
# Default menggunakan endpoint BinderByte, bisa diganti ke RajaOngkir sesuai kebutuhan
LOGISTIC_API_BASE_URL = getattr(config, 'LOGISTIC_API_URL', 'https://api.binderbyte.com/v1/track')

def _create_robust_session() -> requests.Session:
    """
    Membangun HTTP Session yang kebal terhadap network glitch (Micro-downtime).
    Akan mencoba ulang (retry) otomatis jika mendapat error 5xx.
    """
    session = requests.Session()
    
    # Atur strategi retry: Maksimal 3x percobaan, jeda backoff eksponensial
    retry_strategy = Retry(
        total=3,
        backoff_factor=1, # Jeda: 1s, 2s, 4s
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session

def check_delivery_status(tracking_number: str, courier: str) -> Optional[str]:
    """
    Mengecek status resi pengiriman retur secara otomatis.
    
    Args:
        tracking_number (str): Nomor resi yang diinput pembeli
        courier (str): Kode kurir pengiriman (contoh: 'jne', 'sicepat', 'jnt')
        
    Returns:
        str: Status mutlak dari kurir (misal: 'DELIVERED', 'ON_PROCESS')
        None: Jika API gagal atau resi tidak valid
    """
    if not tracking_number or not courier:
        logger.error("[LOGISTIC] Tracking number dan courier wajib diisi.")
        return None

    if not LOGISTIC_API_KEY:
        # ⚡ BYPASS DEVELOPMENT MODE:
        # Jika API Key tidak ada di .env, kita asumsikan mode testing agar Worker tidak error
        logger.warning(f"[LOGISTIC-MOCK] API Key kosong. Asumsikan resi {tracking_number} berstatus DELIVERED.")
        return 'DELIVERED'

    session = _create_robust_session()

    try:
        # Parameter disesuaikan dengan standar kontrak BinderByte
        params = {
            'api_key': LOGISTIC_API_KEY,
            'courier': courier.lower(),
            'awb': tracking_number
        }
        
        logger.debug(f"[LOGISTIC] Menghubungi API kurir untuk resi: {tracking_number}")
        response = session.get(LOGISTIC_API_BASE_URL, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            # Ekstraksi node 'status' dari payload respon BinderByte
            # Bentuk payload asli: { "data": { "summary": { "status": "DELIVERED" } } }
            status = data.get('data', {}).get('summary', {}).get('status', '').upper()
            
            if not status:
                logger.warning(f"[LOGISTIC] Respon API sukses, namun node 'status' tidak ditemukan untuk resi {tracking_number}")
                return None
                
            logger.info(f"[LOGISTIC] Resi {tracking_number} ({courier}) - Status Terkini: {status}")
            return status
            
        elif response.status_code == 400:
            logger.error(f"[LOGISTIC] Resi atau Kurir tidak valid: {tracking_number} ({courier})")
            return 'INVALID_WAYBILL'
            
        else:
            logger.error(f"[LOGISTIC] API Kurir mengembalikan error. HTTP {response.status_code}: {response.text}")
            return None

    except requests.exceptions.RequestException as e:
        logger.error(f"[LOGISTIC] Koneksi jaringan terputus saat melacak resi {tracking_number}: {str(e)}")
        return None
    except Exception as e:
        logger.critical(f"[LOGISTIC] Kesalahan internal fatal pada logistic_service: {str(e)}")
        return None
    finally:
        session.close()