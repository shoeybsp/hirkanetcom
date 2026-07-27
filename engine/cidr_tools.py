import ipaddress

def to_network(addr: str):
    if not addr:
        return None
    try:
        if "/" not in addr:
            return ipaddress.ip_network(addr + "/32", strict=False)
        return ipaddress.ip_network(addr, strict=False)
    except ValueError:
        return None

def is_subset(child: str, parent: str):
    c = to_network(child)
    p = to_network(parent)
    return c and p and c.subnet_of(p)

def any_overlap(a: str, b: str):
    n1 = to_network(a)
    n2 = to_network(b)
    return n1 and n2 and n1.overlaps(n2)

def is_covered_by(requested: str, policy_addr: str):
    requested_net = to_network(requested)
    policy_net = to_network(policy_addr)
    return requested_net and policy_net and requested_net.subnet_of(policy_net)
