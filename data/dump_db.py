import sqlite3, json, sys

c = sqlite3.connect(r'D:\PyProject\chanel-agent\data\chanel.db')
rows = c.execute('SELECT * FROM thought_chains ORDER BY id').fetchall()

for r in rows:
    print(f"ID={r[0]} chain={r[1]} session={r[2]} ts={r[3]}")
    obs = r[4]
    if obs:
        try:
            d = json.loads(obs)
            print(f"  Window: {d.get('active_window','?')}")
            print(f"  App: {d.get('active_app','?')}")
            print(f"  Idle: {d.get('user_idle','?')}")
            print(f"  Time: {d.get('time','?')}")
        except:
            print(f"  Obs(raw): {str(obs)[:100]}")
    print(f"  Inference: {r[5]}")
    print(f"  Action: {r[6]}")
    print(f"  Content: {str(r[7])[:100]}")
    print(f"  Outcome: {str(r[8])[:100]}")
    print("---")
