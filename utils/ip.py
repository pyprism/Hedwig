import socket


def get_local_ip():
    hostname = socket.gethostname()
    _internal_ips = ["127.0.0.1"]
    try:
        resolved_ips = socket.gethostbyname_ex(hostname)[2]
        _internal_ips += resolved_ips
        _internal_ips += [ip.rsplit(".", 1)[0] + ".1" for ip in resolved_ips]
    except Exception as e:
        raise RuntimeError(f"Failed to resolve local IP addresses: {e}")
    return _internal_ips
