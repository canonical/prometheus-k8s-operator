# Centralized justfile for the Canonical Observability charms
set shell := ["bash", "-uc"]

charm_name := `echo ${PWD##*/} | sed 's/-operator$//'`  # Get the charm name from the folder name

export UV_FROZEN := "true"  # Prevent `uv run` from updating the lockfile
export PYTHONPATH := ".:./lib:./src"


[private]
@default:
    just --list

# Print the charm name
[group("info")]
@name:
  echo "{{charm_name}}"


# Update uv.lock dependencies
[group("maintenance")]
lock:
    unset UV_FROZEN; uv lock --upgrade --no-cache

# Scan for security vulnerabilities
[group("maintenance")]
scan:
    @echo "Scanning for security vulnerabilities..."
    uvx uv-secure

# Fetch centralized files from canonical/observability
[group("maintenance")]
refresh:
    #!/usr/bin/env bash
    which -s gh || { echo "gh not found"; exit 1; }
    refresh_folder="blueprints/charms"
    api_path="repos/canonical/observability/contents/$refresh_folder"
    for file in charms.just .tfdocs.yaml; do
      echo "Fetching latest '$file' from canonical/observability ..."
      gh api "$api_path/$file" --jq '.content' | base64 --decode > "$file"
      echo "✓ $file updated"
    done


# Format the codebase
[group("dev")]
format: sync
    # Fix generic linting issues
    uv run ruff check --fix-only
    # Fix import-related issues (including ordering)
    uv run ruff check --select=I --fix-only
    # Format the code
    uv run ruff format

alias fmt := format

# Lint the codebase
[group("dev")]
lint: sync
    # Lint the code
    uv run ruff check
    # Run static checks
    uv run ty check src
    # Check for misspellings
    uv run codespell src
    # Check for dead code (heuristic, so failures are ignored)
    uv run vulture src --min-confidence=80 || true
    # Run actionlint on GitHub Actions workflows
    test -d .github/workflows && uvx --from=actionlint-py actionlint
    @echo "✓ Linting passed!"


# Run all quality checks: formatting, linting and unit tests
[group("dev")]
check: sync format lint unit
    @echo; echo "✓ All checks passed!"

# Sync the virtual environment (.venv)
[group("dev")]
sync:
    uv sync --all-groups --all-extras

# Sync and activate the virtual environment (.venv)
[group("dev")]
venv:
    @echo "Activating virtual environment..."
    @uv sync --all-groups --all-extras
    @. .venv/bin/activate; exec "$SHELL" -i


# Run unit tests
[group("test")]
unit *args: sync
    uv run coverage run --source=src -m pytest tests/unit {{ args }}

# Run integration tests
[group("test")]
integration *args: sync
    uv run pytest --exitfirst tests/integration {{ args }}

# Pretty print all feature files
[group("info")]
features:
    #!/usr/bin/env bash
    set -euo pipefail
    features_dir="tests/integration/features"
    if [ ! -d "$features_dir" ]; then
        echo "No features directory found at $features_dir"
        exit 1
    fi
    # Calculate totals first
    total_features=$(find "$features_dir" -name "*.feature" -type f | wc -l)
    total_scenarios=$(grep -rh "^[[:space:]]*Scenario:" "$features_dir" 2>/dev/null | wc -l || echo "0")
    printf "Total: \033[1m%d features\033[0m with \033[1m%d scenarios\033[0m\n" "$total_features" "$total_scenarios"
    echo ""
    for feature_file in "$features_dir"/*.feature; do
        [ -f "$feature_file" ] || continue
        filename=$(basename "$feature_file")
        feature_name="${filename%.feature}"
        # Extract the Feature: line
        feature_title=$(grep -m1 "^Feature:" "$feature_file" | sed 's/Feature: //')
        # Extract feature description (lines after Feature: until first Scenario, skipping blank lines)
        description=$(awk '/^Feature:/{found=1; next} found && /^[[:space:]]*Scenario/{exit} found && /^[[:space:]]*$/{next} found{gsub(/^[[:space:]]+/, ""); print}' "$feature_file" | head -3)
        # Count scenarios
        scenario_count=$(grep -c "^[[:space:]]*Scenario:" "$feature_file" || echo "0")
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        printf "\033[1m%s\033[0m (%d scenarios)\n" "$feature_title" "$scenario_count"
        echo "   $feature_file"
        echo ""
        if [ -n "$description" ]; then
            echo "$description" | while IFS= read -r line; do
                echo "   $line"
            done
            echo ""
        fi
        # List scenarios
        grep "^[[:space:]]*Scenario:" "$feature_file" | sed 's/^[[:space:]]*Scenario:[[:space:]]*//' | while IFS= read -r scenario; do
            echo "   - $scenario"
        done
        echo ""
    done


# Update the Terraform README with auto-generated content
[group("terraform")]
terraform-docs:
    which terraform-docs > /dev/null 2>&1 || { echo "× terraform-docs not found"; exit 1; }
    terraform-docs --config .tfdocs.yaml .
    @echo "✓ Terraform docs updated"

# Lint and validate the Terraform module
[group("terraform")]
terraform-lint:
    which terraform > /dev/null 2>&1 || { echo "× terraform not found"; exit 1; }
    cd terraform && terraform init -backend=false && terraform validate
    terraform fmt -recursive -check
    @echo "✓ Terraform lint passed"


# Release a .charm file to Charmhub
[group("release")]
release charm_file channel:
    #!/usr/bin/env bash
    set -euo pipefail
    # Upload the charm and get the revision
    echo "Uploading charm {{ charm_file }}..."
    upload_output=$(charmcraft upload "{{ charm_file }}" --format=json)
    charm_revision=$(echo "$upload_output" | jq -r '.revision')
    echo "✓ Uploaded charm revision: $charm_revision"
    # Get resources from charmcraft.yaml
    resource_args=""
    if [ -f charmcraft.yaml ]; then
        while IFS= read -r resource_name; do
            upstream=$(yq -r ".resources.\"$resource_name\".\"upstream-source\" // empty" charmcraft.yaml)
            if [ -n "$upstream" ]; then
                echo "Uploading resource '$resource_name' from $upstream..."
                res_output=$(charmcraft upload-resource "{{ charm_name }}" "$resource_name" --image="docker://$upstream" --format=json)
                res_revision=$(echo "$res_output" | jq -r '.revision')
            else
                echo "Fetching latest revision for resource '$resource_name'..."
                res_revision=$(charmcraft resource-revisions "{{ charm_name }}" "$resource_name" --format=json | jq -r '.[0].revision')
            fi
            echo "✓ Resource '$resource_name' revision: $res_revision"
            resource_args="$resource_args --resource=$resource_name:$res_revision"
        done < <(yq -r '.resources | keys | .[]' charmcraft.yaml 2>/dev/null || true)
    fi
    # Release the charm
    echo "Releasing {{ charm_name }} to {{ channel }}..."
    # shellcheck disable=SC2086
    charmcraft release "{{ charm_name }}" --revision="$charm_revision" --channel="{{ channel }}" $resource_args
    echo "✓ Released {{ charm_name }} revision $charm_revision to {{ channel }}"

# Print all commits between the current branch and the merge-base with `ref`
[group("release")]
[arg("ref", help="Branch (or generic ref) from to get the changelog from")]
changelog ref:
    #!/usr/bin/env python3
    import re
    import subprocess

    def git(*args):
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()

    # Get repo path from remote URL
    remote_url = git("remote", "get-url", "origin")
    match = re.search(r"github\.com[:/]([^/]+/[^/.]+)", remote_url)
    repo_path = match.group(1) if match else ""

    # Resolve ref
    ref = "{{ ref }}"
    try:
        git("rev-parse", "--verify", ref)
    except subprocess.CalledProcessError:
        ref = f"origin/{ref}"

    # Get merge-base and commits
    base = git("merge-base", "HEAD", ref)
    log_output = git("log", f"--format=%H\t%s", f"{base}..HEAD")

    # Categorize commits
    categories = {"breaking": [], "features": [], "fixes": [], "others": []}

    for line in log_output.splitlines():
        if not line:
            continue
        hash, msg = line.split("\t", 1)

        # Skip changelog update commits
        if msg.startswith("chore(changelog)"):
            continue
        short_hash = hash[:7]

        # Format line with links
        pr_match = re.search(r"\(#(\d+)\)", msg)
        if pr_match and repo_path:
            pr_num = pr_match.group(1)
            formatted = f"- {msg.replace(f'(#{pr_num})', f'([#{pr_num}](https://github.com/{repo_path}/pull/{pr_num}))')}"
        elif repo_path:
            formatted = f"- {msg} ([{short_hash}](https://github.com/{repo_path}/commit/{hash}))"
        else:
            formatted = f"- {msg} ({short_hash})"

        # Categorize
        if re.match(r"^[a-z]+(\(.+\))?!:", msg):
            categories["breaking"].append(formatted)
        elif re.match(r"^feat(\(.+\))?:", msg):
            categories["features"].append(formatted)
        elif re.match(r"^fix(\(.+\))?:", msg):
            categories["fixes"].append(formatted)
        else:
            categories["others"].append(formatted)

    # Print changelog
    print("# Changelog\n")
    sections = [("Breaking Changes", "breaking"), ("Features", "features"), ("Fixes", "fixes"), ("Others", "others")]
    for title, key in sections:
        if categories[key]:
            print(f"## {title}\n")
            print("\n".join(categories[key]))
            print()



