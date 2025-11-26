from flask import Flask
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = "sqlite:///lux.db"
db = SQLAlchemy(app)

@app.route("/")
def home():
    return "Lux rodando!"

if __name__ == "__main__":
    app.run()
