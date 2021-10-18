FROM python:slim

MAINTAINER balbir.thomas@gmail.com

RUN pip install prometheus_client

WORKDIR /tester

COPY prometheus.py tester.py

ENTRYPOINT ["python"]

CMD ["/tester/tester.py"]

EXPOSE 8000 8000