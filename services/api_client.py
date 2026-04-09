import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
from loguru import logger
from typing import Dict, Any, Optional

from config import settings

def is_retryable_exception(exception: BaseException) -> bool:
    """
    Menentukan apakah suatu Exception layak untuk di-retry.
    Hanya retry jika terjadi error jaringan (Timeout/Connection Error)
    atau Server Error (5xx). TIDAK me-retry error 4xx (Client Error).
    """
    if isinstance(exception, httpx.RequestError):
        return True  # Retry untuk timeout, DNS error, dll.
    
    if isinstance(exception, httpx.HTTPStatusError):
        # Retry hanya jika Node.js mengembalikan error 500 ke atas (Server down/overload)
        return exception.response.status_code >= 500
        
    return False

def log_retry_attempt(retry_state):
    """Callback Loguru setiap kali Tenacity melakukan retry."""
    logger.warning(
        f"Gagal menghubungi API Node.js. "
        f"Mencoba ulang... (Percobaan ke-{retry_state.attempt_number})"
    )

class AnalogAPIClient:
    """
    HTTPX Client Wrapper menggunakan pola Singleton.
    Memastikan TCP Connection Pool dipertahankan (tidak dibongkar-pasang).
    """
    _instance = None
    _client: Optional[httpx.AsyncClient] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AnalogAPIClient, cls).__new__(cls)
        return cls._instance

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazy initialization untuk HTTPX AsyncClient."""
        if self._client is None:
            # Header Injection: X-API-KEY otomatis menempel di setiap request
            headers = {
                "x-api-key": settings.internal_api_key,
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            self._client = httpx.AsyncClient(
                base_url=settings.node_js_url,
                headers=headers,
                timeout=10.0  # Timeout rasional (10 detik)
            )
            logger.info("HTTPX AsyncClient (Singleton) berhasil diinisialisasi.")
        return self._client

    async def close(self):
        """Menutup koneksi HTTPX secara anggun saat Worker dimatikan."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("HTTPX AsyncClient ditutup.")

    @retry(
        stop=stop_after_attempt(3), # Maksimal 3 kali percobaan
        wait=wait_exponential(multiplier=1, min=2, max=10), # Backoff: 2s, 4s, 8s...
        retry=retry_if_exception(is_retryable_exception),
        before_sleep=log_retry_attempt
    )
    async def post_request(self, path: str, data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Fungsi helper standar untuk mengirim POST request ke Internal API Node.js.
        Dilengkapi dengan Retry Mechanism (Tenacity) dan Error Handling.
        """
        logger.debug(f"Mengirim POST request ke endpoint: {path}")

        try:
            # Mengirim Request
            response = await self.client.post(path, json=data or {})
            
            # Memeriksa status HTTP (akan trigger HTTPStatusError jika 4xx atau 5xx)
            response.raise_for_status()

            logger.success(f"Request ke {path} sukses! (Status: {response.status_code})")
            return response.json()

        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            
            if 400 <= status_code < 500:
                # ERROR 4xx (Misal: 400 Bad Request, 404 Not Found, 403 Forbidden)
                # Kesalahan logika/data -> Catat di Log, tapi JANGAN DI-RETRY.
                logger.error(f"Client Error {status_code} di {path}: {e.response.text}")
                return None # Mengembalikan None agar Worker bisa lanjut ke Order ID berikutnya
            else:
                # ERROR 5xx -> Lemparkan kembali agar ditangkap oleh Tenacity (Retry)
                logger.error(f"Server Error {status_code} di {path}. Node.js bermasalah.")
                raise e
                
        except httpx.RequestError as e:
            # ERROR Jaringan (Timeout, Connection Refused) -> Lemparkan untuk di-retry
            logger.error(f"Network Error saat menghubungi {path}: {str(e)}")
            raise e


    # ==========================================
    # INTEGRATION TASKS (API CALLERS)
    # ==========================================
    
    async def trigger_auto_cancel(self, order_id: str) -> Optional[Dict[str, Any]]:
        """
        Memanggil API Node.js untuk membatalkan pesanan yang belum dibayar (>24 jam).
        """
        path = f"/api/internal/auto-cancel/{order_id}"
        logger.info(f"[TASK] Mengirim instruksi Auto-Cancel untuk Order ID: {order_id}")
        return await self.post_request(path)

    async def trigger_auto_complete(self, order_id: str) -> Optional[Dict[str, Any]]:
        """
        Memanggil API Node.js untuk menyelesaikan pesanan dan merilis Escrow (>48 jam dikirim).
        (Asumsi endpoint ini akan kita buat nanti di Node.js).
        """
        path = f"/api/internal/auto-complete/{order_id}"
        logger.info(f"[TASK] Mengirim instruksi Auto-Complete untuk Order ID: {order_id}")
        return await self.post_request(path)


# Export instance Singleton agar bisa langsung diimport oleh modul tasks
api_client = AnalogAPIClient()