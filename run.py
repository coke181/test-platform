import os
from app import app, init_db
init_db()
app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
