import socket 

OPTIMIZER_PORT= 288


def is_optimizer_port_open():

    try:

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:

            s.settimeout(2)

            return s.connect_ex(
                ("localhost", OPTIMIZER_PORT)
            ) == 0

    except:
        
        return False