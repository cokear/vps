import os
import json
import base64
import sys
import re
from urllib.parse import urlparse, parse_qs, unquote

def fix_ipv6_url(url):
    """修复纯 IPv6 地址的 URL，确保 urlparse 能正确解析"""
    pattern = r'^(\w+://)([^@]+@)?(?!\[)([\da-fA-F:]+):(\d+)(.*)$'
    match = re.match(pattern, url)
    if match:
        scheme_part = match.group(1)
        userinfo = match.group(2) or ""
        host = match.group(3)
        port = match.group(4)
        rest = match.group(5) or ""
        if host.count(':') >= 2:
            return f"{scheme_part}{userinfo}[{host}]:{port}{rest}"
    return url

def get_insecure(params):
    """兼容 insecure 和 allow_insecure 两种参数名"""
    val = params.get("insecure", params.get("allow_insecure", ["0"]))[0]
    return val in ["1", "true"]

def generate_config(proxy_url):
    proxy_url = proxy_url.strip()
    if proxy_url.startswith('{') and proxy_url.endswith('}'):
        try:
            json.loads(proxy_url)
            return proxy_url
        except:
            pass

    # 去掉 fragment（#xxx）
    proxy_url = proxy_url.split('#')[0]

    # 修复裸 IPv6 地址
    proxy_url = fix_ipv6_url(proxy_url)

    parsed = urlparse(proxy_url)
    scheme = parsed.scheme.lower()
    
    outbound = {
        "tag": "proxy"
    }

    if scheme == "tuic":
        outbound["type"] = "tuic"
        outbound["server"] = parsed.hostname
        outbound["server_port"] = parsed.port
        
        if outbound["server"] is None or outbound["server_port"] is None:
            print(f"Failed to parse TUIC host/port from: {proxy_url}")
            sys.exit(1)
        
        auth_user = unquote(parsed.username or "")
        auth_pass = unquote(parsed.password or "")
        
        if auth_pass:
            outbound["uuid"] = auth_user
            outbound["password"] = auth_pass
        elif ":" in auth_user:
            outbound["uuid"], outbound["password"] = auth_user.split(":", 1)
        else:
            outbound["uuid"] = auth_user
            outbound["password"] = ""
        
        params = parse_qs(parsed.query)
        outbound["congestion_control"] = params.get("congestion_control", ["bbr"])[0]
        outbound["udp_relay_mode"] = params.get("udp_relay_mode", ["quic-rfc"])[0]
        
        outbound["tls"] = {"enabled": True}
        if "sni" in params: outbound["tls"]["server_name"] = params["sni"][0]
        if "alpn" in params: outbound["tls"]["alpn"] = params["alpn"][0].split(',')
        if get_insecure(params): outbound["tls"]["insecure"] = True

    elif scheme in ["hysteria2", "hy2"]:
        outbound["type"] = "hysteria2"
        outbound["server"] = parsed.hostname
        outbound["server_port"] = parsed.port
        outbound["password"] = unquote(parsed.username or "")
            
        params = parse_qs(parsed.query)
        outbound["tls"] = {"enabled": True}
        if "sni" in params: outbound["tls"]["server_name"] = params["sni"][0]
        if get_insecure(params): outbound["tls"]["insecure"] = True

    elif scheme == "vless":
        outbound["type"] = "vless"
        outbound["server"] = parsed.hostname
        outbound["server_port"] = parsed.port
        outbound["uuid"] = unquote(parsed.username or "")
        
        params = parse_qs(parsed.query)
        outbound["flow"] = params.get("flow", [""])[0]
        
        tls_enabled = params.get("security", [""])[0] in ["tls", "reality"]
        if tls_enabled:
            outbound["tls"] = {"enabled": True}
            if "sni" in params: outbound["tls"]["server_name"] = params["sni"][0]
            if "fp" in params: outbound["tls"]["utls"] = {"enabled": True, "fingerprint": params["fp"][0]}
            if "pbk" in params: outbound["tls"]["reality"] = {"enabled": True, "public_key": params["pbk"][0], "short_id": params.get("sid", [""])[0]}
            if get_insecure(params): outbound["tls"]["insecure"] = True
        
        network = params.get("type", ["tcp"])[0]
        if network == "ws":
            outbound["transport"] = {"type": "ws", "path": params.get("path", ["/"])[0], "headers": {"Host": params.get("host", [""])[0]}}
        elif network == "grpc":
            outbound["transport"] = {"type": "grpc", "service_name": params.get("serviceName", [""])[0]}

    elif scheme == "trojan":
        outbound["type"] = "trojan"
        outbound["server"] = parsed.hostname
        outbound["server_port"] = parsed.port
        outbound["password"] = unquote(parsed.username or "")
        
        params = parse_qs(parsed.query)
        outbound["tls"] = {"enabled": True}
        if "sni" in params: outbound["tls"]["server_name"] = params["sni"][0]
        if get_insecure(params): outbound["tls"]["insecure"] = True

    elif scheme in ["ss", "shadowsocks"]:
        outbound["type"] = "shadowsocks"
        outbound["server"] = parsed.hostname
        outbound["server_port"] = parsed.port
        
        if parsed.username:
            try:
                decoded = base64.b64decode(parsed.username + "==").decode()
                if ":" in decoded:
                    outbound["method"], outbound["password"] = decoded.split(":", 1)
            except:
                outbound["method"] = unquote(parsed.username)
                outbound["password"] = unquote(parsed.password or "")

    elif scheme == "vmess":
        try:
            v_info = json.loads(base64.b64decode(parsed.netloc + "==").decode())
            outbound["type"] = "vmess"
            outbound["server"] = v_info.get("add")
            outbound["server_port"] = int(v_info.get("port", 443))
            outbound["uuid"] = v_info.get("id")
            outbound["security"] = v_info.get("scy", "auto")
            outbound["alter_id"] = int(v_info.get("aid", 0))
            
            if v_info.get("tls") == "tls":
                outbound["tls"] = {"enabled": True, "server_name": v_info.get("sni", v_info.get("host"))}
            
            if v_info.get("net") == "ws":
                outbound["transport"] = {"type": "ws", "path": v_info.get("path", "/"), "headers": {"Host": v_info.get("host", "")}}
            elif v_info.get("net") == "grpc":
                outbound["transport"] = {"type": "grpc", "service_name": v_info.get("path", "")}
        except:
            print("Failed to parse VMess config")
            sys.exit(1)

    elif scheme == "socks5":
        outbound["type"] = "socks"
        outbound["server"] = parsed.hostname
        outbound["server_port"] = parsed.port
        user = unquote(parsed.username or "")
        passwd = unquote(parsed.password or "")
        if user:
            outbound["username"] = user
            outbound["password"] = passwd

    else:
        print(f"Unknown scheme: {scheme}, please use full JSON for complex configs.")
        sys.exit(1)

    config = {
        "log": {"level": "info"},
        "inbounds": [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": 1080
            }
        ],
        "outbounds": [
            outbound,
            {"type": "direct", "tag": "direct"}
        ],
        "route": {
            "rules": [
                {
                    "inbound": ["mixed-in"],
                    "outbound": "proxy"
                }
            ]
        }
    }
    return json.dumps(config, indent=2)

if __name__ == "__main__":
    proxy_str = os.environ.get("PROXY_STR", "")
    if not proxy_str:
        print("PROXY_STR is empty")
        sys.exit(1)
        
    final_config = generate_config(proxy_str)
    with open("config.json", "w") as f:
        f.write(final_config)
    print("Successfully generated config.json")
