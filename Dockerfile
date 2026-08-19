# Cloud Run image for the Ben-powered analysis engine (analysis/cloudrun.py).
# Carries the external Ben checkout (GPL-3.0, github.com/lorserker/ben —
# used, not vendored into this repo; the image lives in the project's own
# private Artifact Registry) pinned to the same commit + rollout patch as
# scripts/setup_ben.sh.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git patch \
    && rm -rf /var/lib/apt/lists/*

ENV BEN_HOME=/opt/ben \
    PYTHONUNBUFFERED=1

# Ben checkout, pinned exactly like scripts/setup_ben.sh; BBA/EPBot binaries
# removed (never used here), .git dropped to slim the image.
ARG BEN_COMMIT=2b534146415dcacb2f783bd9015b36df44dcf2bb
RUN git clone https://github.com/lorserker/ben.git /opt/ben \
    && git -C /opt/ben checkout -q "$BEN_COMMIT" \
    && rm -rf /opt/ben/bin/BBA /opt/ben/BBA
COPY scripts/ben_rollout_context.patch /tmp/ben_rollout_context.patch
RUN git -C /opt/ben apply /tmp/ben_rollout_context.patch \
    && rm -rf /opt/ben/.git

# Ben pins psutil==5.9.0, which predates Python 3.12 and ships no cp312
# wheel — pip would try to compile it, and this slim image carries no C
# compiler (that is exactly how the first Cloud Build failed). 5.9.8 is the
# oldest 5.9.x with cp312 wheels; Ben only uses psutil for server-side
# process stats, so the bump is behavior-neutral for the rollout path.
# tensorflow comes from requirements.txt (pinned there) — installing it
# separately first would download a second, newer copy only to downgrade it.
RUN sed -i 's/^psutil==5\.9\.0[[:space:]]*$/psutil==5.9.8/' /opt/ben/requirements.txt \
    && grep -q '^psutil==5.9.8$' /opt/ben/requirements.txt \
    && pip install --no-cache-dir -r /opt/ben/requirements.txt \
    && pip install --no-cache-dir firebase-admin

COPY . /app
RUN pip install --no-cache-dir /app

# fail the BUILD, not the first request, if the engine cannot load
RUN python -c "import sys, os; sys.path.insert(0, '/opt/ben/src'); \
    from ddsolver.ddsolver import DDSolver; print('ben dds ok')"

CMD ["python", "-m", "bridge_trainer.analysis.cloudrun"]
