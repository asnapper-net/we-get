FROM debian:buster-slim
RUN apt-get update && apt-get install -y python3 python3-pip jq
WORKDIR /app
ADD . .
RUN pip3 install .