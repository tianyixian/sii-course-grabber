"""SII 统一身份认证（CAS）自动登录模块

复现浏览器登录流程：
  1. 向教务后端要 CAS 授权地址（OAuth2 authorize）
  2. 打开 CAS 登录页，取 execution 表单令牌
  3. 用页面内置 RSA 公钥加密密码，提交表单
  4. 跟随重定向链拿到授权 code
  5. 用 code 向教务后端换取 JWT token
"""
import re
import requests
from urllib.parse import urlparse, parse_qs

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# CAS 登录页内置的 RSA 公钥（公钥，非机密）
RSA_E = 0x010001
RSA_N = int(
    "008aed7e057fe8f14c73550b0e6467b023616ddc8fa91846d2613cdb7f7621e3c"
    "ada4cd5d812d627af6b87727ade4e26d26208b7326815941492b2204c3167ab2d"
    "53df1e3a2c9153bdb7c8c2e968df97a5e7e01cc410f92c4c2c2fba529b3ee988e"
    "bc1fca99ff5119e036d732c368acf8beba01aa2fdafa45b21e4de4928d0d403", 16)
CHUNK_BYTES = 126  # 2 * biHighIndex(n)


def rsa_encrypt_password(password: str) -> str:
    """复现 CAS 前端 ohdave RSAUtils.encryptedString：小端分块 pow 加密"""
    a = [ord(ch) & 0xFF for ch in password]
    while len(a) % CHUNK_BYTES != 0:
        a.append(0)
    blocks = []
    for i in range(0, len(a), CHUNK_BYTES):
        block_int = int.from_bytes(bytes(a[i:i + CHUNK_BYTES]), "little")
        blocks.append(format(pow(block_int, RSA_E, RSA_N), "x"))
    return " ".join(blocks)


def login(backend_base: str, username: str, password: str, timeout: int = 20) -> str:
    """完整 CAS 登录流程，返回教务系统 JWT token。失败抛 RuntimeError。

    backend_base: 教务后端地址，如 https://xspy.sii.edu.cn/educationalAdministrationBackend
    """
    s = requests.Session()
    s.headers["User-Agent"] = UA
    s.verify = False

    # 1. 拿 CAS 授权地址
    r = s.post(backend_base + "/cas/getCasServerAddress", json={"clientType": "1"}, timeout=timeout)
    authorize_url = r.json()["data"]["casAddress"]
    cas_host = "{0.scheme}://{0.netloc}".format(urlparse(authorize_url))

    # 2. 打开 CAS 登录页
    r = s.get(authorize_url, timeout=timeout, allow_redirects=True)
    if "/cas/login" not in r.url:
        code = parse_qs(urlparse(r.url).query).get("code", [None])[0]
        if code:
            return _exchange_code(s, backend_base, code)
        raise RuntimeError(f"CAS 页面异常: {r.url}")
    m = re.search(r'name="execution"[^>]*value="([^"]+)"', r.text)
    if not m:
        raise RuntimeError("未找到 execution 字段（CAS 页面结构可能已变更）")

    # 3. 提交加密后的登录表单
    data = {
        "username": username,
        "password": rsa_encrypt_password(password),
        "encrypted": "true",
        "_eventId": "submit",
        "loginType": "1",
        "execution": m.group(1),
    }
    r = s.post(cas_host + "/cas/login", data=data, timeout=timeout, allow_redirects=False)
    if r.status_code != 302:
        raise RuntimeError(f"CAS 登录失败（HTTP {r.status_code}）："
                           f"请检查账号密码是否正确")

    # 4. 跟随重定向链直到回到教务系统回调地址（带 code）
    url = r.headers["Location"]
    for _ in range(10):
        if "code=" in url and cas_host not in url:
            break
        r = s.get(url if url.startswith("http") else cas_host + url,
                  timeout=timeout, allow_redirects=False)
        nxt = r.headers.get("Location")
        if not nxt:
            break
        url = nxt
    code = parse_qs(urlparse(url).query).get("code", [None])[0]
    if not code:
        raise RuntimeError(f"未取得授权 code: {url}")

    # 5. code 换 token
    return _exchange_code(s, backend_base, code)


def _exchange_code(s: requests.Session, backend_base: str, code: str) -> str:
    r = s.post(backend_base + "/cas/loginByGrantCode",
               json={"grantCode": code, "clientType": "1"}, timeout=20)
    j = r.json()
    if j.get("errorCode") != "00000":
        raise RuntimeError(f"code 换 token 失败: {j}")
    return j["data"]["token"]
