FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src PHOTO_RETOUCH_DATA=/data
ENV U2NET_HOME=/opt/models OMP_NUM_THREADS=1
WORKDIR /app
COPY photo_retouch_app/requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt && useradd --create-home editor && mkdir /data && chown editor:editor /data
RUN pip uninstall -y opencv-contrib-python opencv-python-headless && pip install --no-cache-dir 'opencv-contrib-python-headless>=4.10,<5'
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
RUN python -c "from rembg import new_session; new_session('u2netp', providers=['CPUExecutionProvider'])" && chmod -R a+rX /opt/models
RUN python -c "import urllib.request; urllib.request.urlretrieve('https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task', '/opt/models/pose_landmarker.task')"
COPY photo_retouch_app/src ./src
COPY photo_retouch_app/tests ./tests
USER editor
EXPOSE 5000
HEALTHCHECK --interval=15s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')"
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "600", "photo_retouch.web:create_app()"]
