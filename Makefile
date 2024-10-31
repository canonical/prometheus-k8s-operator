PROJECT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

SRC := $(PROJECT)src
TESTS := $(PROJECT)tests
ALL := $(SRC) $(TESTS)

export PYTHONPATH = $(PROJECT):$(PROJECT)/lib:$(SRC)

# Update uv.lock, including upgrading/downgrading existing dependencies and adding new ones
update-dependencies:
	# TODO: uv lock vs uv sync?
	uv lock -U --no-cache

clean: clean-charm clean-requirements

clean-charm:
	rm -f *.charm

clean-requirements:
	rm -f requirements*.txt

generate-requirements: clean-requirements
	uv pip compile -q --no-cache pyproject.toml -o requirements.txt

# Because we want the version of formatting/linting tools to be to controlled by
# pyproject.toml, use `uv run` here instead of `uv tool run`, with args:
# * --extra X: to install the dependencies for X
# * --isolated: to use an isolated ephemeral project, not the main project, so we don't accidentally mess with the main project's dependencies
# We use this instead of `uv tool run X` because `uv tool run` has no way of consuming
# optional dependency groups from a pyproject.toml.
#
# A variation on this could be to have an extra dependency group for each tool, eg:
# ruff, then we only install that tool's stuff.  But installing ruff and codespell at
# the same time in uv is really cheap
fmt: EXTRA_DEPENDENCIES = --extra lint
fmt:
	uv run --isolated $(EXTRA_DEPENDENCIES) ruff check --fix $(ALL)
	uv run --isolated $(EXTRA_DEPENDENCIES) ruff format $(ALL)

lint: EXTRA_DEPENDENCIES = --extra lint
lint:
	uv run --isolated $(EXTRA_DEPENDENCIES) ruff check $(ALL)
	uv run --isolated $(EXTRA_DEPENDENCIES) ruff format --check --diff $(ALL)
	uv run --isolated $(EXTRA_DEPENDENCIES) codespell $(PROJECT) --skip $(PROJECT)src/manifests 

static-charm: EXTRA_DEPENDENCIES = --extra unit
static-charm:
	exit 1

static-lib: EXTRA_DEPENDENCIES = --extra unit
static-lib:
	exit 1

unit: EXTRA_DEPENDENCIES = --extra unit
unit:
	uv run $(EXTRA_DEPENDENCIES) \
		coverage run \
		--source=$(SRC) \
		-m pytest \
		$(TESTS)/unit \
		--tb native \
		-v \
		-s \
		$(ARGS)
	uv run $(EXTRA_DEPENDENCIES) coverage report

scenario: EXTRA_DEPENDENCIES = --extra scenario
scenario:
	uv run $(EXTRA_DEPENDENCIES) \
		coverage run \
		--source=$(SRC) \
		-m pytest \
		$(TESTS)/scenario \
		--tb native \
		-v \
		-s \
		$(ARGS)
	uv run $(EXTRA_DEPENDENCIES) coverage report


integration: EXTRA_DEPENDENCIES = --extra integration
integration:
	uv run $(EXTRA_DEPENDENCIES) \
		pytest -v \
		-s \
		--tb native \
		$(TESTS)/integration \
		--log-cli-level=INFO \
		$(ARGS)