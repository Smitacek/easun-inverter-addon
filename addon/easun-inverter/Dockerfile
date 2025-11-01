ARG BUILD_FROM
FROM ${BUILD_FROM}

SHELL ["/bin/ash", "-o", "pipefail", "-c"]

RUN apk add --no-cache bash curl jq

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . /app
# Ensure entrypoint script is executable
RUN chmod +x /app/run.sh

# Rely on shebang (with-contenv bashio) in run.sh
CMD ["/app/run.sh"]
