import sys

from app import app, limiter

if __name__ == "__main__":
    limiter.enabled = False
    app.run(port=int(sys.argv[1]))
