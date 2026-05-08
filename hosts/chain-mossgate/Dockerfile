FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    openssh-server sudo vim-tiny curl nmap default-mysql-client \
    iproute2 netcat-openbsd iputils-ping net-tools wget \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/run/sshd

RUN useradd -m -s /bin/bash infra-ops \
    && echo 'infra-ops:Bm6yLs9k' | chpasswd \
    && echo 'infra-ops ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/infra-ops \
    && chmod 440 /etc/sudoers.d/infra-ops

RUN echo 'pwned_by_vim_root' > /root/flag.txt

WORKDIR /app

COPY app.py ./

RUN pip install --no-cache-dir flask requests

EXPOSE 80 22

CMD ["bash", "-c", "/usr/sbin/sshd -D & exec python /app/${APP_FILE:-app.py}"]
