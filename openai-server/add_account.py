#!/usr/bin/env python3
"""往 accounts.json 增加 / 更新一个 Gemini 账号，然后重启服务。

用法（在 89 上）：
    cd ~/apps/gemini-webapi-server
    ./.venv/bin/python add_account.py <label> <__Secure-1PSID> <__Secure-1PSIDTS> [proxy]

例：
    ./.venv/bin/python add_account.py alt1 g.a000xxxx sidts-yyyy
"""
import json, os, sys, subprocess, pathlib

def main():
    if len(sys.argv) < 4:
        print(__doc__); sys.exit(1)
    label, psid, psidts = sys.argv[1], sys.argv[2], sys.argv[3]
    proxy = sys.argv[4] if len(sys.argv) > 4 else None

    f = pathlib.Path(__file__).with_name("accounts.json")
    accts = []
    if f.exists():
        try:
            accts = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            accts = []
    # 按 label 去重更新
    accts = [a for a in accts if a.get("label") != label]
    accts.append({"label": label, "secure_1psid": psid, "secure_1psidts": psidts, "proxy": proxy})
    f.write_text(json.dumps(accts, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(f, 0o600)
    print("[OK] accounts.json now has %d account(s): %s" % (len(accts), ", ".join(a["label"] for a in accts)))

    print("[..] restarting gemini-webapi.service")
    subprocess.run(["systemctl", "--user", "restart", "gemini-webapi.service"], check=False)
    print("[done] 用 curl http://127.0.0.1:18090/health 查看各账号 ready 状态")

if __name__ == "__main__":
    main()
