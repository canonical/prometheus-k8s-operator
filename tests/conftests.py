from _pytest.config.argparsing import Parser


def pytest_addoption(parser: Parser):
    parser.addoption(
        "--charm-path",
        help="Pre-built charm file to deploy, rather than building from source",
    )
