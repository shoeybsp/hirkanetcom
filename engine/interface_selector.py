import ipaddress

def _route_network(route):
    return route.get("network") or route.get("dst")

def _route_interface(route):
    return route.get("interface") or route.get("device")

def _normalize_network(net):
    if not net:
        return None
    return net.replace(" ", "/")

def select_interface_for_ip(ip_str, routes):
    try:
        target = ipaddress.ip_address(ip_str.split("/")[0])
    except ValueError:
        return None

    best = None
    best_len = -1

    for r in routes:
        if r.get("status", "enable") != "enable":
            continue
        net = _normalize_network(_route_network(r))
        itf = _route_interface(r)
        if not net or not itf:
            continue

        try:
            n = ipaddress.ip_network(net, strict=False)
        except ValueError:
            continue

        if target in n and n.prefixlen > best_len:
            best_len = n.prefixlen
            best = itf

    if not best:
        for r in routes:
            if r.get("status", "enable") != "enable":
                continue
            net = _normalize_network(_route_network(r))
            if net == "0.0.0.0/0" or net == "0.0.0.0/0.0.0.0":
                return _route_interface(r)

    return best
