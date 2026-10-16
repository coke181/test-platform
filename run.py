from app import app, init_db
init_db()
app.run(host="127.0.0.1", port=5000, debug=False)
