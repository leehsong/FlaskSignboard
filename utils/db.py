def db_select_all(sql, params=(), use=None):
    c = use.getconn()
    try:
        cur = c.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return rows
    finally: use.putconn(c)

def db_select_all_dict(sql, params=(), use=None):
    c = use.getconn()
    try:
        cur = c.cursor()
        cur.execute(sql, params)
        desc = [d[0] for d in cur.description]
        rows = cur.fetchall()
        cur.close()
        return [dict(zip(desc, r)) for r in rows]
    finally: use.putconn(c)

def db_execute(sql, params=(), use=None):
    c = use.getconn()
    try:
        cur = c.cursor()
        cur.execute(sql, params)
        if hasattr(c, "commit"): c.commit()
        cur.close()
    finally: use.putconn(c)
