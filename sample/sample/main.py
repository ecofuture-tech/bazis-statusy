import os


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sample.settings')

from bazis.core.app import app


if __name__ == "__main__":
    app.uvicorn_start()
