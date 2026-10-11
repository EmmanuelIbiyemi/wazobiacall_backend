FROM python:3.11-slim

# Hugging Face runs the container as user 1000
RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1
WORKDIR /home/user/app

# CPU-only PyTorch is much smaller than the default (the free Space has no GPU anyway)
RUN pip install --no-cache-dir torch --extra-index-url https://download.pytorch.org/whl/cpu

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .
USER user

EXPOSE 7860
CMD ["uvicorn", "main:call", "--host", "0.0.0.0", "--port", "8000"]