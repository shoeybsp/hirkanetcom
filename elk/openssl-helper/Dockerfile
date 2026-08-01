FROM alpine:3.21.3

RUN apk add --no-cache openssl

COPY elk/convert-logstash-key.sh /usr/local/bin/convert-logstash-key
RUN chmod 0755 /usr/local/bin/convert-logstash-key

ENTRYPOINT ["/usr/local/bin/convert-logstash-key"]
