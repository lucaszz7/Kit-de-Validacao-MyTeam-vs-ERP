import urllib.request
import urllib.error

OPTIMIZER_HOST = "sysdev-route-api-pt.dyndns.org"
OPTIMIZER_PORT = 288
OPTIMIZER_URL = f"http://{OPTIMIZER_HOST}:{OPTIMIZER_PORT}/vroom"

def is_optimizer_port_open() -> bool:
    """
    Valida o estado do Otimizador.
    Envia um pedido POST sem body para a API externa. 
    Se o servidor responder (mesmo que seja o erro HTTP 400 Bad Request),
    significa que o serviço está ativo e acessível na rede.
    """
    
    req = urllib.request.Request(OPTIMIZER_URL, data=b"", method="POST")
    
    try:
        
        with urllib.request.urlopen(req, timeout=3) as response:
            
            return response.status in (200, 201, 204)
            
    except urllib.error.HTTPError as e:
        
        if e.code == 400:
            return True
        return False
        
    except Exception:
        
        return False