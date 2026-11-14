"""Start the Flask editor locally (Docker uses Gunicorn)."""
import os
from photo_retouch.web import create_app


def main():
    create_app().run(host='127.0.0.1', port=int(os.environ.get('PORT', '5000')))


if __name__ == '__main__':
    main()
