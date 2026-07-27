import json
from engine.cidr_tools import is_covered_by, to_network
from engine.interface_selector import select_interface_for_ip

class SecureTrackLite:
    def __init__(self):
        self.policies = self._load("data/policies.json")
        self.addresses = self._load("data/addresses.json")
        self.routes = self._load("data/routes.json")
        self.services = self._load("data/services.json")

        self.addr_map = self._map_addresses()
        self.service_map = self._map_services()
        self.policies = self._normalize_policies()

    def _load(self, path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _normalize_name_list(self, values):
        return [
            (x.get("name", "") if isinstance(x, dict) else x).lower()
            for x in values
            if (x.get("name") if isinstance(x, dict) else x)
        ]

    def _map_addresses(self):
        out = {}
        for a in self.addresses:
            name = a.get("name", "").lower()
            if a.get("group"):
                out[name] = {
                    "group": [
                        x.get("name", x).lower() if isinstance(x, dict) else x.lower()
                        for x in a.get("group", [])
                    ]
                }
                continue
            if "subnet" in a:
                out[name] = a["subnet"].replace(" ", "/")
            elif "iprange" in a:
                start = a["iprange"].split()[0]
                out[name] = start + "/32"
            elif a.get("type") == "all":
                out[name] = "0.0.0.0/0"
        return out

    def _map_services(self):
        return {
            s.get("name", "").lower(): {
                **s,
                "name": s.get("name", "").lower(),
                "group": [x.lower() for x in s.get("group", [])],
                "protocol": s.get("protocol", "").lower(),
            }
            for s in self.services
            if s.get("name")
        }

    def _expand_address_names(self, names, seen=None):
        seen = seen or set()
        expanded = []
        for name in names:
            name = name.lower()
            if name in seen:
                continue
            seen.add(name)
            value = self.addr_map.get(name)
            if isinstance(value, dict) and value.get("group"):
                expanded.extend(self._expand_address_names(value["group"], seen))
            else:
                expanded.append(name)
        return expanded

    def _request_networks(self, values):
        networks = []
        for value in values:
            name = value.lower()
            if name in self.addr_map:
                for expanded_name in self._expand_address_names([name]):
                    network = self._resolve(expanded_name)
                    if network:
                        networks.append(network)
            else:
                networks.append(value)
        return networks

    def _normalize_policies(self):
        pols = []
        for p in self.policies:
            if p.get("action") != "accept":
                continue
            if p.get("status", "enable") != "enable":
                continue
            srcaddr = self._expand_address_names(self._normalize_name_list(p.get("srcaddr", [])))
            dstaddr = self._expand_address_names(self._normalize_name_list(p.get("dstaddr", [])))
            pols.append({
                "policyid": p.get("policyid"),
                "name": p.get("name"),
                "srcaddr": srcaddr,
                "dstaddr": dstaddr,
                "service": self._normalize_name_list(p.get("service", [])),
                "srcintf": self._normalize_name_list(p.get("srcintf", [])),
                "dstintf": self._normalize_name_list(p.get("dstintf", [])),
            })
        return pols

    def _resolve(self, name):
        value = self.addr_map.get(name.lower())
        if isinstance(value, dict):
            return None
        return value

    def _is_broad_network(self, name):
        net = to_network(self._resolve(name))
        return bool(net and net.prefixlen == 0)

    def _service_aliases(self, name, seen=None):
        name = name.lower()
        seen = seen or set()
        if name in seen:
            return set()
        seen.add(name)

        aliases = {name}
        if name.isdigit():
            aliases.add(f"tcp-{name}")
            aliases.add(f"udp-{name}")

        svc = self.service_map.get(name)
        if not svc:
            return aliases

        for member in svc.get("group", []):
            aliases |= self._service_aliases(member, seen)

        for key in ("tcp-portrange", "udp-portrange"):
            port_range = svc.get(key)
            if not port_range:
                continue
            proto = key.split("-")[0]
            aliases.add(f"{proto}-{port_range}")
            if "-" in port_range:
                start, end = port_range.split("-", 1)
                aliases.add(f"{proto}-{start}-{end}")

        return aliases

    def _service_matches(self, requested, policy_service):
        requested_aliases = self._service_aliases(requested)
        policy_aliases = self._service_aliases(policy_service)

        if requested_aliases & policy_aliases:
            return True

        for req in requested_aliases:
            try:
                proto, port = req.split("-", 1)
                port = int(port)
            except ValueError:
                continue
            for alias in policy_aliases:
                parts = alias.split("-")
                if len(parts) != 3 or parts[0] != proto:
                    continue
                try:
                    start = int(parts[1])
                    end = int(parts[2])
                except ValueError:
                    continue
                if start <= port <= end:
                    return True
        return False

    def _has_required_matches(self, srcs, dsts, srvs, src_matches, dst_matches, srv_matches):
        return (
            (not srcs or src_matches > 0)
            and (not dsts or dst_matches > 0)
            and (not srvs or srv_matches > 0)
        )

    def _interface_matches(self, policy_interfaces, route_interface):
        if not route_interface:
            return True
        if any(itf in ("all", "any") for itf in policy_interfaces):
            return True
        return route_interface.lower() in policy_interfaces

    def _interface_has_route(self, policy_interfaces, route_interface):
        if not route_interface:
            return False
        return route_interface.lower() in policy_interfaces

    def _address_proximity(self, requested, policy_addr):
        requested_net = to_network(requested)
        policy_net = to_network(policy_addr)
        if not requested_net or not policy_net:
            return 0

        req_int = int(requested_net.network_address)
        pol_int = int(policy_net.network_address)
        common_prefix = 32 - (req_int ^ pol_int).bit_length()
        common_prefix = max(0, min(common_prefix, 32))

        if common_prefix >= 31:
            return 50
        if common_prefix >= 28:
            return 35
        if common_prefix >= 24:
            return 18
        if common_prefix >= 22:
            return 12
        if common_prefix >= 16:
            return 6
        return 0

    def _best_address_proximity(self, requested, policy_addresses):
        best = 0
        for policy_address in policy_addresses:
            resolved = self._resolve(policy_address)
            if resolved:
                best = max(best, self._address_proximity(requested, resolved))
        return best

    def score_policy(self, pol, srcs, dsts, srvs):
        score = 0
        s_match = d_match = v_match = 0
        missing = []

        for s in srcs:
            matched = False
            for pa in pol["srcaddr"]:
                a = self._resolve(pa)
                if a and is_covered_by(s, a):
                    s_match += 1
                    matched = True
                    break
            if matched:
                score += 40
            if not matched:
                score += self._best_address_proximity(s, pol["srcaddr"])
                missing.append("srcaddr")

        for d in dsts:
            matched = False
            for pa in pol["dstaddr"]:
                a = self._resolve(pa)
                if a and is_covered_by(d, a):
                    d_match += 1
                    matched = True
                    break
            if matched:
                score += 40
            if not matched:
                score += self._best_address_proximity(d, pol["dstaddr"])
                missing.append("dstaddr")

        for sv in srvs:
            matched = False
            for pa in pol["service"]:
                if self._service_matches(sv, pa):
                    v_match += 1
                    matched = True
                    break
            if matched:
                score += 20

        score -= min(10, len(pol["srcaddr"]) - s_match)
        score -= min(10, len(pol["dstaddr"]) - d_match)
        score -= min(5, len(pol["service"]) - v_match)

        if "all" in pol["srcaddr"]:
            score -= 15
        if "all" in pol["dstaddr"]:
            score -= 15
        score -= 15 * sum(1 for src in pol["srcaddr"] if self._is_broad_network(src))
        score -= 15 * sum(1 for dst in pol["dstaddr"] if self._is_broad_network(dst))

        return score, s_match, d_match, v_match, sorted(set(missing))

    def _is_extension_candidate(
        self,
        srcs,
        dsts,
        srvs,
        src_matches,
        dst_matches,
        srv_matches,
        dstintf_has_route,
    ):
        if srvs and srv_matches == 0:
            return False
        if dsts and dst_matches == 0:
            return bool(srvs and srv_matches > 0 and dstintf_has_route)
        if srcs and dsts:
            return dst_matches > 0
        if srcs:
            return src_matches > 0
        if dsts:
            return dst_matches > 0
        return True

    def evaluate(self, srcs, dsts, srvs):
        srcs = [x.strip().lower() for x in srcs if x and x.strip()]
        dsts = [x.strip().lower() for x in dsts if x and x.strip()]
        srvs = [x.strip().lower() for x in srvs if x and x.strip()]
        srcs = self._request_networks(srcs)
        dsts = self._request_networks(dsts)
        if not srcs and not dsts and not srvs:
            return []
        route_srcintf = select_interface_for_ip(srcs[0], self.routes) if srcs else None
        route_dstintf = select_interface_for_ip(dsts[0], self.routes) if dsts else None

        results = []
        for p in self.policies:
            sc, sm, dm, vm, missing = self.score_policy(p, srcs, dsts, srvs)
            srcintf_matches = self._interface_matches(p["srcintf"], route_srcintf)
            dstintf_matches = self._interface_matches(p["dstintf"], route_dstintf)
            dstintf_has_route = self._interface_has_route(p["dstintf"], route_dstintf)
            if not self._is_extension_candidate(srcs, dsts, srvs, sm, dm, vm, dstintf_has_route):
                continue
            if srcs and srcintf_matches:
                sc += 10
            elif srcs:
                sc -= 5
            if dsts and dstintf_matches:
                sc += 10
            elif dsts:
                sc -= 5

            results.append({
                "policyid": p["policyid"],
                "name": p["name"],
                "score": sc,
                "src_matches": sm,
                "dst_matches": dm,
                "srv_matches": vm,
                "missing": missing,
                "candidate_action": "add " + ", ".join(missing) if missing else "already covered",
                "srcintf": p["srcintf"],
                "dstintf": p["dstintf"],
                "route_srcintf": route_srcintf,
                "route_dstintf": route_dstintf,
                "srcintf_matches": srcintf_matches,
                "dstintf_matches": dstintf_matches,
            })
        return sorted(results, key=lambda x: x["score"], reverse=True)
