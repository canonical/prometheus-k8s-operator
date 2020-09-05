import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="prometheus-charm",
    version="0.0.1",
    author="Balbir Thomas",
    author_email="balbir.thomas@canonical.com",
    description="Kubernetes Charm/Operator for Prometheus",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/balbirthomas/prometheus-charm",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.5',
)
