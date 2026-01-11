import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def get_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=0.1)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('https://', adapter)
    return session

def measure_rest_latency(url: str, iterations: int = 5) -> None:
    session = get_session()
    latencies: list[float] = []

    print(f"Target: {url}")
    
    # Warmup request to cache DNS/SSL context if strictly measuring subsequent API speed
    try:
        session.get(url, timeout=5)
    except Exception as e:
        print(f"Warmup failed: {e}")
        return

    for i in range(iterations):
        try:
            start_ns: int = time.perf_counter_ns()
            # GET /ok is the standard health check endpoint for Polymarket CLOB
            resp: requests.Response = session.get(f"{url}/ok", timeout=5)
            end_ns: int = time.perf_counter_ns()
            
            if resp.status_code == 200:
                latency_ms: float = (end_ns - start_ns) / 1_000_000
                latencies.append(latency_ms)
                print(f"Run {i+1}: {latency_ms:.2f} ms")
            else:
                print(f"Run {i+1}: Failed (Status {resp.status_code})")
        except requests.RequestException as e:
            print(f"Run {i+1}: Error - {str(e)}")

    if latencies:
        avg_latency: float = sum(latencies) / len(latencies)
        print(f"\nAverage Application Latency: {avg_latency:.2f} ms")

if __name__ == "__main__":
    measure_rest_latency("https://clob.polymarket.com")