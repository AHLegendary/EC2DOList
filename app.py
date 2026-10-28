import os
import time

import psycopg2
from flask import Flask, jsonify, redirect, render_template_string, request

app = Flask(__name__)


def get_conn():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ.get("DB_NAME", "todos"),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        connect_timeout=3,
    )


def init_db(retries=10):
    for attempt in range(retries):
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    """CREATE TABLE IF NOT EXISTS todos (
                        id SERIAL PRIMARY KEY,
                        title TEXT NOT NULL,
                        done BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )"""
                )
            return
        except psycopg2.OperationalError:
            time.sleep(2)
    raise RuntimeError("Database not reachable")


PAGE = """
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>To-Do List</title>
<style>
 body{font-family:system-ui,sans-serif;max-width:520px;margin:3rem auto;padding:0 1rem}
 form.add{display:flex;gap:.5rem;margin-bottom:1rem}
 input[type=text]{flex:1;padding:.6rem;border:1px solid #ccc;border-radius:6px}
 button{padding:.6rem 1rem;border:0;border-radius:6px;background:#f7941d;color:#fff;cursor:pointer}
 li{display:flex;align-items:center;gap:.5rem;padding:.5rem 0;border-bottom:1px solid #eee}
 li.done span{text-decoration:line-through;color:#888}
 li span{flex:1} ul{list-style:none;padding:0}
 .link{background:none;color:#c00;padding:.2rem .5rem}
 .toggle{background:#eee;color:#333;padding:.2rem .6rem}
</style></head><body>
<h1>To-Do List</h1>
<form class="add" method="post" action="/add">
  <input type="text" name="title" placeholder="What needs doing?" required maxlength="200">
  <button>Add</button>
</form>
<ul>
{% for t in todos %}
  <li class="{{ 'done' if t[2] else '' }}">
    <form method="post" action="/toggle/{{ t[0] }}"><button class="toggle">{{ '↺' if t[2] else '✓' }}</button></form>
    <span>{{ t[1] }}</span>
    <form method="post" action="/delete/{{ t[0] }}"><button class="link">✕</button></form>
  </li>
{% else %}<li><span>Nothing yet. Add your first task!</span></li>{% endfor %}
</ul>
<p><small><a href="/health">health</a></small></p>
</body></html>
"""


@app.get("/")
def index():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, title, done FROM todos ORDER BY id")
        todos = cur.fetchall()
    return render_template_string(PAGE, todos=todos)


@app.post("/add")
def add():
    title = request.form["title"].strip()[:200]
    if title:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO todos (title) VALUES (%s)", (title,))
    return redirect("/")


@app.post("/toggle/<int:todo_id>")
def toggle(todo_id):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE todos SET done = NOT done WHERE id = %s", (todo_id,))
    return redirect("/")


@app.post("/delete/<int:todo_id>")
def delete(todo_id):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM todos WHERE id = %s", (todo_id,))
    return redirect("/")


@app.get("/health")
def health():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
        return jsonify(app="ok", database="ok"), 200
    except Exception as e:
        return jsonify(app="ok", database="down", error=type(e).__name__), 503


init_db()
